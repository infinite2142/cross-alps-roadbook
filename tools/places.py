#!/usr/bin/env python3
"""Resolve data/places.json coordinates from OpenStreetMap, once, at build time.

The towns are authored by hand; the coordinates are not. Typing sixty Alpine
coordinates from memory would put a base in the wrong valley sooner or later
and nothing downstream would notice — the generator would simply route you
there. So each record carries a `query` and the coordinate is fetched from
Nominatim, then checked against the passes the town is supposed to serve.

Nominatim is the OpenStreetMap gazetteer. Its usage policy allows occasional
low-volume scripted use with a real User-Agent and at most one request a
second, which is what this does: about sixty requests, run once, and never
again unless a town is added. Results are written back into places.json and
committed, so this is not a dependency of the build — it is how the file was
made. Nothing here runs in the browser.

    python3 tools/places.py geocode          # fill in missing coordinates
    python3 tools/places.py geocode --force  # re-resolve every record
    python3 tools/places.py check            # validate, no network
"""

import argparse
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLACES = os.path.join(ROOT, "data", "places.json")
PASSES = os.path.join(ROOT, "data", "passes.json")

UA = "cross-alps-roadbook/1.0 (static site build script; contact via github.com/infinite2142)"
ENDPOINT = "https://nominatim.openstreetmap.org/search"
PAUSE = 1.1                  # the policy is one a second; leave a margin

# The Alps, generously. A result outside this is wrong whatever it claims.
BBOX = (43.0, 49.6, 4.0, 17.2)          # lat lo, lat hi, lon lo, lon hi
MAX_KM_TO_SERVED = 70.0                 # a base further than this serves nothing


def haversine(a, b):
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


SETTLEMENT = {"city", "town", "village", "hamlet", "municipality", "locality",
              "isolated_dwelling", "suburb", "neighbourhood"}


def geocode(query, cc):
    """Ask for the settlement, not the commune.

    Taking the top hit gave the administrative centroid for several of these,
    and an Alpine commune's centroid is usually a mountainside: Kranjska Gora
    came back at 1,558 m when the village is at 810, and Lanslebourg landed a
    few hundred metres from the Mont-Cenis summit. Fetch a handful of results
    and prefer a `place` node — a town or a village is somewhere you can
    sleep, a boundary polygon is not."""
    q = urllib.parse.urlencode({
        "q": query, "format": "jsonv2", "limit": 8,
        "countrycodes": cc.lower(), "addressdetails": 0,
    })
    req = urllib.request.Request(ENDPOINT + "?" + q, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        out = json.loads(r.read())
    if not out:
        return None
    hit = next((o for o in out
                if o.get("category") == "place" and o.get("type") in SETTLEMENT), None)
    # Some small communes have no settlement node at all — Predazzo, Cavalese
    # and Auronzo are boundaries only. Their centroids sit in the valley with
    # the village, so take them, but record where they came from: the failure
    # this guards against is a centroid on a mountainside, and only a human
    # reading the list can tell those two apart.
    src = "settlement"
    if hit is None:
        hit, src = out[0], "boundary"
    return ([round(float(hit["lat"]), 5), round(float(hit["lon"]), 5)],
            f'{hit.get("type","?")}: {hit.get("display_name","")}', src)


def validate(places, passes):
    by_id = {p["id"]: p for p in passes}
    problems, warnings = [], []
    seen_id, seen_coord = set(), {}
    pass_ids = set(by_id)
    for r in places:
        rid = r["id"]
        if rid in seen_id:
            problems.append(f"{rid}: duplicate id")
        seen_id.add(rid)
        for s in r.get("serves", []):
            if s not in pass_ids:
                problems.append(f"{rid}: serves unknown pass '{s}'")
        c = r.get("coord")
        if not c:
            warnings.append(f"{rid}: no coordinate yet")
            continue
        if not (BBOX[0] <= c[0] <= BBOX[1] and BBOX[2] <= c[1] <= BBOX[3]):
            problems.append(f"{rid}: {c} outside the Alpine box")
            continue
        key = (round(c[0], 3), round(c[1], 3))
        if key in seen_coord:
            problems.append(f"{rid}: same coordinate as {seen_coord[key]}")
        seen_coord[key] = rid
        served = [by_id[s] for s in r.get("serves", []) if s in by_id]
        if served:
            d = min(haversine(c, p["coord"]) for p in served)
            near = min(served, key=lambda p: haversine(c, p["coord"]))
            if d > MAX_KM_TO_SERVED:
                problems.append(f"{rid}: {d:.0f} km from its nearest served pass "
                                f"({near['id']}) — wrong town?")
            r["_km"] = round(d, 1)
    return problems, warnings


def report_boundary(places):
    """A boundary centroid is only a worry when it has drifted uphill.

    Most communes here are compact enough that their centroid is the town, and
    listing all thirty-nine of them trains you to ignore the warning. The one
    that matters is a centroid that has climbed out of the valley, and altitude
    is the tell: an Alpine settlement above 1,600 m is unusual enough to be
    worth a look, and that is where the bad ones showed up."""
    b = [r for r in places if r.get("geo_src") == "boundary"]
    odd = [r for r in b if (r.get("alt") or 0) > 1600]
    print(f"\n{len(b)} of {len(places)} from a boundary centroid "
          f"(no settlement node in OSM); {len(odd)} of those above 1,600 m")
    for r in odd:
        print(f"  · {r['id']} at {r['alt']} m — check it is the town, not a hillside")


def cmd_geocode(args):
    places = json.load(open(PLACES, encoding="utf-8"))
    passes = json.load(open(PASSES, encoding="utf-8"))
    todo = [r for r in places if args.force or not r.get("coord")]
    print(f"{len(todo)} of {len(places)} to resolve, about {len(todo)*PAUSE:.0f}s\n")
    failed = []
    for i, r in enumerate(todo, 1):
        try:
            got = geocode(r.get("query") or r["name"], r["cc"])
        except Exception as e:                       # noqa: BLE001 - report and carry on
            got = None
            print(f"  ! {r['id']}: {e}", file=sys.stderr)
        if got:
            r["coord"], got_name, r["geo_src"] = got
            print(f"  [{i}/{len(todo)}] {r['id']:<22}{r['coord']}  {got_name[:58]}")
        else:
            failed.append(r["id"])
            print(f"  [{i}/{len(todo)}] {r['id']:<22}NOT FOUND")
        time.sleep(PAUSE)

    problems, warnings = validate(places, passes)
    for r in places:
        r.pop("_km", None)
    if failed:
        print("\nnot found: " + ", ".join(failed), file=sys.stderr)
    if problems:
        print("\nPROBLEMS — nothing written:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    json.dump(places, open(PLACES, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"\nwritten. {sum(1 for r in places if r.get('coord'))} of {len(places)} have coordinates")
    report_boundary(places)
    for w in warnings:
        print("  · " + w)
    return 0


def cmd_elevate(args):
    """Altitudes from Open-Meteo, which the page already calls for weather.

    A place node needs one: the roadbook row prints it, the altitude profile
    plots it, and `ascent()` sums it. GEO's places get theirs from the authored
    routes; these have no such source. One request covers all of them."""
    places = json.load(open(PLACES, encoding="utf-8"))
    todo = [r for r in places if r.get("coord") and (args.force or r.get("alt") is None)]
    if not todo:
        print("nothing to do")
        return 0
    lat = ",".join(str(r["coord"][0]) for r in todo)
    lon = ",".join(str(r["coord"][1]) for r in todo)
    url = f"https://api.open-meteo.com/v1/elevation?latitude={lat}&longitude={lon}"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=45) as r:
        got = json.loads(r.read()).get("elevation")
    if not got or len(got) != len(todo):
        print(f"expected {len(todo)} elevations, got {got and len(got)}", file=sys.stderr)
        return 1
    odd = []
    for rec, e in zip(todo, got):
        rec["alt"] = int(round(e))
        if not (150 <= rec["alt"] <= 2600):
            odd.append(f"{rec['id']} {rec['alt']} m")
    if odd:
        print("implausible for an Alpine town: " + ", ".join(odd), file=sys.stderr)
        return 1
    json.dump(places, open(PLACES, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    lo = min(todo, key=lambda r: r["alt"]); hi = max(todo, key=lambda r: r["alt"])
    print(f"{len(todo)} altitudes written; {lo['id']} {lo['alt']} m .. {hi['id']} {hi['alt']} m")
    return 0


def cmd_check(args):
    places = json.load(open(PLACES, encoding="utf-8"))
    passes = json.load(open(PASSES, encoding="utf-8"))
    problems, warnings = validate(places, passes)
    have = [r for r in places if r.get("coord")]
    print(f"places: {len(places)}   with coordinates: {len(have)}")
    if have:
        far = sorted((r for r in have if "_km" in r), key=lambda r: -r["_km"])[:8]
        print("\nfurthest from the nearest pass they serve:")
        for r in far:
            print(f"  {r['id']:<24}{r['_km']:>6.1f} km")
    report_boundary(places)
    for w in warnings:
        print("  · " + w)
    for p in problems:
        print("  ! " + p, file=sys.stderr)
    return 1 if problems else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("geocode")
    g.add_argument("--force", action="store_true")
    e=sub.add_parser("elevate")
    e.add_argument("--force", action="store_true")
    sub.add_parser("check")
    args = ap.parse_args()
    return {"geocode": cmd_geocode, "elevate": cmd_elevate, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
