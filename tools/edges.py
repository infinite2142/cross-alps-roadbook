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

def _balanced(src, start, opener="{", closer="}"):
    """Return the bracketed block beginning at or after `start`."""
    i = src.index(opener, start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == opener:
            depth += 1
        elif src[j] == closer:
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
    # GEO keys are JS string literals and two of them bite. "Cortina
    # d'Ampezzo" is double-quoted, so one character class for both quote types
    # reads the apostrophe as an opening quote and yields "Ampezzo". 'Passo
    # d\'Eira' is single-quoted with the apostrophe backslash-escaped, so a
    # naive [^']* stops inside the name and yields "Eira". Both keep the right
    # coordinate, which is why neither looks broken — the name is simply not
    # the one the roadbook asks for later, and the lookup silently finds
    # nothing. Match quote type and escapes the way JS does.
    pat = r"""(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")\s*:\s*\[\s*([\d.\-]+)\s*,\s*([\d.\-]+)\s*\]"""
    unescape = lambda s: re.sub(r"\\(.)", r"\1", s)
    return {
        unescape(sq if sq is not None and sq != "" else dq): (float(a), float(b))
        for sq, dq, a, b in re.findall(pat, blk)
    }


def slug(name):
    x = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", x).strip("_")


def catkey(s):
    """Mirror of `catKey` in index.html. A GEO waypoint and the catalogue record
    for the same pass must collapse to one node here exactly as they do on the
    page, or the matrix carries both — two nodes on one summit, half the edges
    keyed to a name the generator no longer uses."""
    x = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    x = re.sub(r"\b(passo|pass|col|colle|de|del|dello|della|di|du|le|la)\b", " ", x)
    return re.sub(r"[^a-z0-9]+", "", x)


def load_nodes():
    """[(id, name, (lat, lon), kind)] — passes first, then places."""
    nodes, seen = [], set()
    catnames = set()

    for p in json.load(open(PASSES, encoding="utf-8")):
        nodes.append((p["id"], p["name"], tuple(p["coord"]), "pass"))
        seen.add(p["id"])
        for n in [p["name"]] + p.get("alt_names", []):
            catnames.add(catkey(n))
        catnames.add(catkey(p["id"].replace("_", " ")))

    # GEO and places.json are both place sources and neither supersedes the
    # other yet: GEO holds the waypoints the five authored trips drive through
    # and still feeds the roadbook itself, places.json holds the towns added
    # for the generator. Reading places.json *instead of* GEO, which is what
    # this did, would have silently dropped every base the authored trips use.
    for name, coord in read_geo().items():
        if catkey(name) in catnames:
            continue              # the catalogue record is the canonical node
        sid = "geo_" + slug(name)
        if sid in seen:
            continue
        nodes.append((sid, name, coord, "geo"))
        seen.add(sid)
        catnames.add(catkey(name))

    src = "index.html GEO (transitional)"
    if os.path.exists(PLACES):
        added = 0
        for q in json.load(open(PLACES, encoding="utf-8")):
            if not q.get("coord") or q["id"] in seen:
                continue
            if catkey(q["name"]) in catnames:
                continue          # already here under its GEO or catalogue name
            nodes.append((q["id"], q["name"], tuple(q["coord"]), q.get("kind", "place")))
            seen.add(q["id"])
            catnames.add(catkey(q["name"]))
            added += 1
        src += f" + data/places.json ({added})"

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

    # A node the router cannot snap to a road produces no edges at all, and
    # nothing downstream would say so — the generator would simply never route
    # through it, exactly the way a waypoint with no coordinate silently
    # vanishes from the maps. Count degrees and name the offenders.
    deg = {i: 0 for i, _, _, _ in nodes}
    for k in edges:
        a, b = k.split("|")
        deg[a] += 1
        deg[b] += 1
    orphans = [(i, nm, c) for i, nm, c, _ in nodes if deg[i] == 0]
    thin = [(i, nm, deg[i]) for i, nm, _, _ in nodes if 0 < deg[i] < (len(nodes) - 1) // 2]
    if orphans:
        print(f"\n{len(orphans)} node(s) the router could not reach at all — fix the coordinate:")
        for i, nm, c in orphans:
            print(f"  {i:<30} {nm:<36} {c}")
    if thin:
        print(f"\n{len(thin)} node(s) reachable from under half the network:")
        for i, nm, d in thin:
            print(f"  {i:<30} {nm:<36} {d}/{len(nodes) - 1}")
    if not orphans and not thin:
        print("every node is routable")
    return 1 if orphans else 0


def _split_top(s, opener, closer):
    """Top-level bracketed groups inside `s`, quotes respected."""
    out, depth, start, q, esc = [], 0, None, None, False
    for i, ch in enumerate(s):
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if q:
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
            continue
        if ch == opener:
            if depth == 0:
                start = i
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                out.append(s[start:i + 1])
    return out


def _fields(group):
    """Top-level comma-separated fields of one [...] literal."""
    body = group[1:-1]
    out, cur, depth, q, esc = [], "", 0, None, False
    for ch in body:
        if esc:
            cur += ch
            esc = False
            continue
        if ch == "\\":
            cur += ch
            esc = True
            continue
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in "'\"":
            q = ch
            cur += ch
            continue
        if ch in "[{(":
            depth += 1
        elif ch in "]})":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def _pts_names(pts_block):
    """Waypoint names from a pts array.

    A point is [km, altitude, name, kind, country, note]; a regex over the
    whole block cheerfully matches the country code as a name too, which is
    how this first went wrong. Parse the positions instead of pattern-matching
    the text. 'thru' points are kept: they are real places on the road, and
    it is only Google that must not be handed them as stops.
    """
    names = []
    for grp in _split_top(pts_block[1:-1], "[", "]"):
        f = _fields(grp)
        if len(f) < 3:
            continue
        nm = f[2].strip()
        if len(nm) >= 2 and nm[0] in "'\"" and nm[-1] == nm[0]:
            names.append(nm[1:-1].replace("\\'", "'").replace('\\"', '"'))
    return names


def _routes():
    """Every authored option, as (key, day, [waypoint names], km, minutes).

    Read straight out of index.html: those figures are the only ground truth
    there is, and D is still the source of truth for the authored trip.
    """
    src = open(INDEX, encoding="utf-8").read()
    out = []
    for key in "ABCDE":
        m = re.search(r"\b%s\s*:\s*\{key\s*:\s*'%s'" % (key, key), src)
        if not m:
            continue
        blk = _balanced(src, m.start())
        for d in re.finditer(
                r"\{n:(\d+),from:'([^']*)',to:'([^']*)',km:(\d+),time:'(\d+)h (\d+)m'", blk):
            tail = blk[d.end():]
            pm = re.search(r"pts:\s*\[", tail)
            if not pm:
                continue
            names = _pts_names(_balanced(tail, pm.start(), "[", "]"))
            out.append((key, int(d.group(1)), names,
                        int(d.group(4)), int(d.group(5)) * 60 + int(d.group(6))))
    return out


def cmd_verify(args):
    """Chain every authored day through the matrix and compare.

    A direct A->B route is not the day's road — Option C's day 1 leaves Prad,
    climbs the Stelvio, drops to Bormio over the Umbrail, takes the Gavia and
    comes back east: 288 km where the direct line is 128. The only meaningful
    check walks the waypoints in order, which is also what the generator will
    do. Option C's figures were verified on the ground in September 2026; the
    rest are the author's own estimates and are weaker evidence.
    """
    if not os.path.exists(EDGES):
        print("no data/edges.json yet — run `fetch` first.")
        return 0

    data = json.load(open(EDGES, encoding="utf-8"))
    edges = data["edges"]
    nodes, _ = load_nodes()
    by_name = {n: i for i, n, _, _ in nodes}

    def leg(a, b):
        return edges.get("%s|%s" % (a, b)) or edges.get("%s|%s" % (b, a))

    print("Every authored day, chained waypoint by waypoint through the matrix.\n")
    print("%-9s%-30s%9s%8s%7s   %9s%8s%7s"
          % ("day", "route", "routed", "book", "delta", "routed", "book", "delta"))
    print("%-9s%-30s%9s%8s%7s   %9s%8s%7s"
          % ("", "", "km", "km", "", "min", "min", ""))

    rows, gaps = [], []
    for key, n, names, bkm, bmin in _routes():
        km = mn = 0.0
        ok = True
        for a, b in zip(names, names[1:]):
            ia, ib = by_name.get(a), by_name.get(b)
            e = leg(ia, ib) if ia and ib else None
            if not e:
                gaps.append("%s day %d: %s -> %s" % (key, n, a, b))
                ok = False
                break
            km += e[0]
            mn += e[1]
        if not ok:
            continue
        dk = 100 * (km - bkm) / bkm
        dm = 100 * (mn - bmin) / bmin
        rows.append((key, n, km, bkm, dk, mn, bmin, dm))
        print("%s day %-3d%-30s%9.0f%8d%6.0f%%   %9.0f%8d%6.0f%%"
              % (key, n, (names[0] + " to " + names[-1])[:29], km, bkm, dk, mn, bmin, dm))

    if not rows:
        print("nothing could be chained — check the node names.")
        return 1

    wk = max(abs(r[4]) for r in rows)
    wm = max(abs(r[7]) for r in rows)
    print("\n%d days chained, %d blocked by a missing edge" % (len(rows), len(gaps)))
    for g in gaps:
        print("  gap  " + g)
    print("\nworst deviation: distance %.0f%%   moving time %.0f%%   (gate: 10%%)" % (wk, wm))

    # The interesting part is not the worst case but its sign: the router is
    # optimistic where the road is all hairpins and pessimistic where it is
    # motorway, so a single scale factor cannot fix it.
    fast = [r for r in rows if r[2] / max(r[5] / 60.0, 0.01) >= 60]
    slow = [r for r in rows if r[2] / max(r[5] / 60.0, 0.01) < 60]
    for label, g in (("fast days (>=60 km/h routed)", fast), ("slow days (<60 km/h routed)", slow)):
        if g:
            avg = sum(r[7] for r in g) / len(g)
            print("  %-32s %2d days, mean time error %+.0f%%" % (label, len(g), avg))
    print("\nDistance is usable as-is. Time is not: see docs/route-generator-brief.md.")
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
