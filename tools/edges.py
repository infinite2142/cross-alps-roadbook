#!/usr/bin/env python3
"""Build data/edges.json — the drive-time matrix for the route generator.

Python 3 stdlib only: no package manager, in keeping with the project's
constraints. Run it from this machine; cloud sessions have restricted egress.

    python3 tools/edges.py nodes     # assemble and validate the node set
    python3 tools/edges.py plan      # API budget, no network
    python3 tools/edges.py fetch     # call the routing API, resumable
    python3 tools/edges.py verify    # calibrate against Option C

Node set = data/passes.json  +  places.
Places currently come from the GEO map inside index.html, which stays the
single source of truth for them until data/places.json exists; if that file
appears it wins and GEO is ignored, so the two never both count.
"""

import argparse
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
PASSES = os.path.join(ROOT, "data", "passes.json")
PLACES = os.path.join(ROOT, "data", "places.json")
EDGES = os.path.join(ROOT, "data", "edges.json")
CACHE = os.path.join(ROOT, "data", ".edges-cache.json")

# ORS free tier. Confirm against current docs before a large run — these are
# the numbers the budget in `plan` is based on, and they do change.
ORS_URL = "https://api.openrouteservice.org/v2/matrix/driving-car"
ORS_MAX_CELLS = 2500      # sources x destinations per request
ORS_CALLS_PER_DAY = 500
ORS_CALLS_PER_MIN = 40


# ---------------------------------------------------------------- node set

def _balanced(src, start):
    """Return the {...} block beginning at or after `start`."""
    i = src.index("{", start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise ValueError("unbalanced block")


def read_geo():
    src = open(INDEX, encoding="utf-8").read()
    m = re.search(r"const GEO\s*=\s*\{", src)
    if not m:
        raise SystemExit("GEO not found in index.html")
    blk = _balanced(src, m.start())
    return {
        k: (float(a), float(b))
        for k, a, b in re.findall(
            r"['\"]([^'\"]+)['\"]\s*:\s*\[\s*([\d.\-]+)\s*,\s*([\d.\-]+)\s*\]", blk
        )
    }


def slug(name):
    x = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", x).strip("_")


def load_nodes():
    """[(id, name, (lat, lon), kind)] — passes first, then places."""
    nodes, seen = [], set()

    for p in json.load(open(PASSES, encoding="utf-8")):
        nodes.append((p["id"], p["name"], tuple(p["coord"]), "pass"))
        seen.add(p["id"])

    if os.path.exists(PLACES):
        for q in json.load(open(PLACES, encoding="utf-8")):
            if q["id"] in seen:
                continue
            nodes.append((q["id"], q["name"], tuple(q["coord"]), q.get("kind", "place")))
            seen.add(q["id"])
        src = "data/places.json"
    else:
        for name, coord in read_geo().items():
            sid = "geo_" + slug(name)
            if sid in seen:
                continue
            nodes.append((sid, name, coord, "geo"))
            seen.add(sid)
        src = "index.html GEO (transitional)"

    return nodes, src


def haversine(a, b):
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# -------------------------------------------------------------- subcommands

def cmd_nodes(args):
    nodes, src = load_nodes()
    kinds = {}
    for _, _, _, k in nodes:
        kinds[k] = kinds.get(k, 0) + 1
    print(f"places source: {src}")
    print(f"nodes: {len(nodes)}  " + "  ".join(f"{k}={v}" for k, v in sorted(kinds.items())))

    bad = [(i, n, c) for i, n, c, _ in nodes
           if not (43.0 <= c[0] <= 49.5 and 4.0 <= c[1] <= 17.0)]
    if bad:
        print(f"\n{len(bad)} node(s) outside the Alpine bounding box:")
        for i, n, c in bad:
            print(f"  {i:<34}{n:<34}{c}")

    # Coordinates that collide are a silent map bug: two nodes, one pin.
    by_coord = {}
    for i, n, c, _ in nodes:
        by_coord.setdefault((round(c[0], 4), round(c[1], 4)), []).append(i)
    dupes = {c: v for c, v in by_coord.items() if len(v) > 1}
    if dupes:
        print(f"\n{len(dupes)} coordinate collision(s):")
        for c, v in dupes.items():
            print(f"  {c}  {', '.join(v)}")
    if not bad and not dupes:
        print("\nno coordinate problems found")
    return 0


def cmd_plan(args):
    nodes, src = load_nodes()
    n = len(nodes)
    full = n * (n - 1) // 2

    print(f"places source: {src}")
    print(f"nodes: {n}   unordered pairs: {full}\n")

    print("straight-line pruning, for reference:")
    for r in (100, 150, 200, 250):
        c = sum(1 for x in range(n) for y in range(x + 1, n)
                if haversine(nodes[x][2], nodes[y][2]) <= r)
        print(f"  <= {r:>3} km: {c:>7} pairs  ({100 * c / full:.0f}% of full)")

    side = math.ceil(math.sqrt(ORS_MAX_CELLS))
    tiles = math.ceil(n / side) ** 2
    print(f"\nfull matrix via {side}x{side} tiles: {tiles} requests"
          f"  ({ORS_CALLS_PER_DAY}/day, {ORS_CALLS_PER_MIN}/min on the ORS free tier)")
    print(f"minutes at the rate limit: {tiles / ORS_CALLS_PER_MIN:.1f}")
    print("\nThe full matrix costs a few dozen requests, so pruning buys nothing"
          "\nand risks dropping long legs. `fetch` computes the full matrix.")
    return 0


def _ors_matrix(key, locs, src_idx, dst_idx):
    body = json.dumps({
        "locations": locs,
        "sources": src_idx,
        "destinations": dst_idx,
        "metrics": ["duration", "distance"],
        "units": "m",
    }).encode()
    req = urllib.request.Request(
        ORS_URL, data=body,
        headers={"Authorization": key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def cmd_fetch(args):
    key = args.key or os.environ.get("ORS_API_KEY")
    if not key:
        print("no API key: pass --key or set ORS_API_KEY", file=sys.stderr)
        return 2

    nodes, src = load_nodes()
    n = len(nodes)
    locs = [[c[1], c[0]] for _, _, c, _ in nodes]   # ORS takes lon,lat
    side = int(math.sqrt(ORS_MAX_CELLS))

    cache = json.load(open(CACHE, encoding="utf-8")) if os.path.exists(CACHE) else {}
    tiles = [(a, b) for a in range(0, n, side) for b in range(0, n, side)]
    todo = [t for t in tiles if f"{t[0]}:{t[1]}" not in cache]
    print(f"places source: {src}\nnodes {n}  tiles {len(tiles)}  remaining {len(todo)}")
    if args.dry_run:
        return 0

    for k, (a, b) in enumerate(todo, 1):
        si = list(range(a, min(a + side, n)))
        di = list(range(b, min(b + side, n)))
        for attempt in range(5):
            try:
                res = _ors_matrix(key, locs, si, di)
                cache[f"{a}:{b}"] = {
                    "sources": si, "destinations": di,
                    "durations": res.get("durations"), "distances": res.get("distances"),
                }
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 503) and attempt < 4:
                    wait = 2 ** attempt * 5
                    print(f"  {e.code}, retrying in {wait}s")
                    time.sleep(wait)
                    continue
                print(f"tile {a}:{b} failed: {e.code} {e.read()[:200]!r}", file=sys.stderr)
                json.dump(cache, open(CACHE, "w"))
                return 1
        json.dump(cache, open(CACHE, "w"))
        print(f"  [{k}/{len(todo)}] tile {a}:{b}")
        time.sleep(60.0 / ORS_CALLS_PER_MIN)

    edges, ids = {}, [i for i, _, _, _ in nodes]
    for tile in cache.values():
        for x, si in enumerate(tile["sources"]):
            for y, di in enumerate(tile["destinations"]):
                if si >= di:
                    continue
                dur = (tile["durations"] or [[None]])[x][y]
                dist = (tile["distances"] or [[None]])[x][y]
                if dur is None or dist is None:
                    continue
                edges[f"{ids[si]}|{ids[di]}"] = [round(dist / 1000, 1), round(dur / 60)]

    json.dump({
        "_comment": "km and minutes between node pairs. Built by tools/edges.py.",
        "generated": time.strftime("%Y-%m-%d"),
        "profile": "driving-car", "source": "openrouteservice",
        "nodes": len(nodes), "edges": edges,
    }, open(EDGES, "w"), indent=0)
    print(f"wrote {EDGES}: {len(edges)} edges")
    return 0


def cmd_verify(args):
    """Option C's day totals were verified on the ground in September 2026."""
    src = open(INDEX, encoding="utf-8").read()
    m = re.search(r"\bC\s*:\s*\{", src)
    blk = _balanced(src, m.start())
    days = re.findall(
        r"\{n:(\d+),from:'([^']*)',to:'([^']*)',km:(\d+),time:'(\d+)h (\d+)m'", blk)

    print("Option C, measured on the ground:\n")
    print(f"{'day':<5}{'from -> to':<48}{'km':>6}{'min':>6}")
    tk = tm = 0
    for n, f, t, km, h, mi in days:
        mins = int(h) * 60 + int(mi)
        tk += int(km)
        tm += mins
        print(f"{n:<5}{f + ' -> ' + t:<48}{km:>6}{mins:>6}")
    print(f"{'':<5}{'total':<48}{tk:>6}{tm:>6}")

    if not os.path.exists(EDGES):
        print("\nno data/edges.json yet — nothing to calibrate against.")
        return 0

    data = json.load(open(EDGES, encoding="utf-8"))
    edges = data["edges"]
    nodes, _ = load_nodes()
    by_name = {n.lower(): i for i, n, _, _ in nodes}

    print("\nrouted vs measured:")
    worst = 0.0
    for n, f, t, km, h, mi in days:
        a, b = by_name.get(f.lower()), by_name.get(t.lower())
        e = edges.get(f"{a}|{b}") or edges.get(f"{b}|{a}") if a and b else None
        if not e:
            print(f"  day {n}: no edge for {f} -> {t}")
            continue
        meas = int(h) * 60 + int(mi)
        dev = abs(e[1] - meas) / meas
        worst = max(worst, dev)
        flag = "  <-- over 10%" if dev > 0.10 else ""
        print(f"  day {n}: routed {e[0]:>6} km {e[1]:>4} min | "
              f"measured {km:>5} km {meas:>4} min | {dev * 100:>5.1f}%{flag}")
    print(f"\nworst deviation {worst * 100:.1f}% (brief's gate: 10%)")
    print("A direct A->B route is not the day's actual road: the generator must"
          "\nchain each day's waypoints. Treat this as a floor, not the check itself.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("nodes", help="assemble and validate the node set")
    sub.add_parser("plan", help="API budget, no network")
    f = sub.add_parser("fetch", help="call the routing API, resumable")
    f.add_argument("--key", help="ORS API key (or set ORS_API_KEY)")
    f.add_argument("--dry-run", action="store_true")
    sub.add_parser("verify", help="calibrate against Option C")
    args = ap.parse_args()
    return {"nodes": cmd_nodes, "plan": cmd_plan,
            "fetch": cmd_fetch, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
