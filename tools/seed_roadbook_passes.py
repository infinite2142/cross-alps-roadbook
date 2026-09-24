#!/usr/bin/env python3
"""One-off: give the roadbook's own passes catalogue records.

The catalogue was seeded with the wider Alpine arc, so 24 passes the five
authored trips actually drive had no record. The generator only routes over
catalogue passes, which is why it could reach 8 of 34 and why a longer day
changed nothing — there was nowhere further to go.

Everything derivable is derived rather than retyped: the coordinate comes from
GEO, the altitude and country from the authored routes, the highlight from
NOTES, and the winter behaviour from PASS_SEASON. Only judgement fields are
written here, and none of them invents an opening date — `season.clearance`
carries PASS_SEASON's three-way classification onto the record so the page
keeps saying exactly what it says today.

Because each record reuses GEO's coordinate unchanged, its edges are unchanged
too: the drive-time matrix is rekeyed from `geo_<slug>` to the new id rather
than refetched, so this costs no API calls.

    python3 tools/seed_roadbook_passes.py --dry-run
    python3 tools/seed_roadbook_passes.py
"""

import argparse
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
PASSES = os.path.join(ROOT, "data", "passes.json")
EDGES = os.path.join(ROOT, "data", "edges.json")
CACHE = os.path.join(ROOT, "data", ".edges-cache.json")
TODAY = "2026-09-24"

# Judgement only. id, region, roads, difficulty, width, scenic, toll, verify.
# Anything measurable is read from the page instead of being repeated here.
# scenic drives the search's ranking; difficulty and width are descriptive.
SEED = [
    # id            roadbook name                    region        roads       diff width          scenic toll         verify
    ("brenner",     "Brenner Pass",                  "tirol",      ["SS12"],     1, "two_lane",        2, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("fernpass",    "Fernpass",                      "tirol",      ["B179"],     2, "two_lane",        3, "none",      "https://www.tirol.gv.at/verkehr/"),
    ("hahntennjoch","Hahntennjoch",                  "tirol",      ["L21"],      3, "two_lane_narrow", 4, "none",      "https://www.tirol.gv.at/verkehr/"),
    ("norbertshohe","Norbertshöhe",                  "tirol",      [],           2, "two_lane",        3, "none",      "https://www.tirol.gv.at/verkehr/"),
    ("reschenpass", "Reschenpass",                   "vinschgau",  ["SS40"],     1, "two_lane",        3, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("jaufenpass",  "Jaufenpass",                    "south_tyrol",["SS44"],     3, "two_lane",        4, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("mendola",     "Passo della Mendola",           "south_tyrol",[],           2, "two_lane",        3, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("palade",      "Passo delle Palade",            "south_tyrol",[],           2, "two_lane",        3, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("sella",       "Passo Sella",                   "dolomites",  ["SS242"],    3, "two_lane",        5, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("gardena",     "Passo Gardena",                 "dolomites",  ["SS243"],    3, "two_lane",        5, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("pordoi",      "Passo Pordoi",                  "dolomites",  ["SS48"],     3, "two_lane",        5, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("campolongo",  "Passo Campolongo",              "dolomites",  ["SS244"],    2, "two_lane",        4, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("falzarego",   "Passo Falzarego",               "dolomites",  ["SS48"],     3, "two_lane",        5, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("valparola",   "Passo Valparola",               "dolomites",  ["SP24"],     3, "two_lane_narrow", 5, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("giau",        "Passo Giau",                    "dolomites",  ["SP638"],    4, "two_lane_narrow", 5, "none",      "https://www.veneto.info/"),
    ("fedaia",      "Passo Fedaia",                  "dolomites",  ["SS641"],    4, "two_lane_narrow", 5, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("costalunga",  "Passo di Costalunga",           "dolomites",  ["SS241"],    2, "two_lane",        4, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("tonale",      "Passo del Tonale",              "adamello",   ["SS42"],     2, "two_lane",        3, "none",      "https://www.stradeanas.it/"),
    ("foscagno",    "Passo di Foscagno",             "livigno",    ["SS301"],    3, "two_lane",        3, "none",      "https://www.livigno.eu/en"),
    ("eira",        "Passo d'Eira",                  "livigno",    ["SS301"],    2, "two_lane",        3, "none",      "https://www.livigno.eu/en"),
    ("forcola",     "Forcola di Livigno",            "livigno",    [],           3, "two_lane_narrow", 4, "none",      "https://www.tcs.ch/en/travel-camping/travel-advice/alpine-passes.php"),
    ("ofenpass",    "Ofenpass / Pass dal Fuorn",     "engadine",   ["Route 28"], 2, "two_lane",        4, "none",      "https://www.tcs.ch/en/travel-camping/travel-advice/alpine-passes.php"),
    ("staller",     "Staller Sattel",                "hohe_tauern",[],           3, "two_lane_narrow", 4, "none",      "https://www.suedtirol.info/en/information/mobility"),
    ("rossfeld",    "Rossfeld Panoramastrasse",      "berchtesgaden", [],        2, "two_lane",        4, "road_toll", "https://www.rossfeldpanoramastrasse.de/"),
]

# Roadbook names that a record already covers, so they must not become records.
# The first three are viewpoints and a tunnel portal on one road, not passes of
# their own — the `grossglockner` record already stands for that road, and
# giving each a record would let the search count the same climb three times.
ALREADY = {
    "Edelweissspitze": "grossglockner",
    "Fuscher Törl": "grossglockner",
    "Hochtor tunnel": "grossglockner",
    "Rifugio Auronzo · Tre Cime": "tre_cime",
}


def balanced(src, start):
    i = src.index("{", start)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    raise ValueError("unbalanced")


Q = r"""(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")"""
unq = lambda s: re.sub(r"\\(.)", r"\1", s)


def slug(name):
    x = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", x).strip("_")


def read_page():
    src = open(INDEX, encoding="utf-8").read()
    geo = {unq(a or b): [float(x), float(y)] for a, b, x, y in re.findall(
        Q + r"\s*:\s*\[\s*([\d.\-]+)\s*,\s*([\d.\-]+)\s*\]",
        balanced(src, re.search(r"const GEO\s*=\s*\{", src).start()))}
    season = {unq(a or b): k for a, b, k in re.findall(
        Q + r"\s*:\s*'(winter|storm|open)'",
        balanced(src, re.search(r"const PASS_SEASON\s*=\s*\{", src).start()))}
    notes = {unq(a or b): unq(c or d) for a, b, c, d in re.findall(
        Q + r"\s*:\s*" + Q,
        balanced(src, re.search(r"const NOTES\s*=\s*\{", src).start()))}
    facts = {}
    for m in re.finditer(r"\[\s*[\d.]+\s*,\s*(\d+)\s*,\s*" + Q + r"\s*,\s*'[a-z]*'\s*,\s*'([A-Z]{2})'", src):
        alt, a, b, cc = m.groups()
        facts.setdefault(unq(a or b), {"alt": int(alt), "cc": cc})
    return geo, season, notes, facts


def build(geo, season, notes, facts):
    out, problems = [], []
    for pid, name, region, roads, diff, width, scenic, toll, verify in SEED:
        if name not in geo:
            problems.append(f"{name}: not in GEO"); continue
        if name not in season:
            problems.append(f"{name}: not in PASS_SEASON"); continue
        f = facts.get(name)
        if not f:
            problems.append(f"{name}: no altitude/country in the authored routes"); continue
        kind = season[name]
        alt_names = [p.strip() for p in re.split(r"\s*/\s*", name) if p.strip()]
        alt_names = [a for a in alt_names if a != name]
        note = ("Cleared rather than closed for the season, but heavy snow shuts it for "
                "a day or two." if kind == "storm" else
                "Shut through the winter; the reopening date moves from year to year."
                if kind == "winter" else None)
        out.append({
            "id": pid, "name": name,
            **({"alt_names": alt_names} if alt_names else {}),
            "countries": [f["cc"]], "region": region,
            "summit_m": f["alt"], "coord": geo[name], "roads": roads,
            "season": {
                "year_round": kind == "open",
                # PASS_SEASON's own judgement, carried over rather than replaced
                # by a window nobody has verified. Add typical_open/typical_close
                # to a record once a real source is checked and it upgrades to
                # the dated branch on its own.
                "clearance": kind,
                "typical_open": None, "typical_close": None,
                "spread_days": 0, "note": note,
            },
            "access": {"night_closure": None, "timed_or_booked": False, "vehicle_limits": None},
            "toll": {"type": toll, "band": "free" if toll == "none" else "under_20", "note": None},
            # Not measured. The generator times legs from edges.json, not from
            # here, so a guessed number would be decoration with a false sense
            # of precision. Left null until somebody drives it or sources it.
            "drive": {"length_km": None, "hairpins": None, "difficulty": diff,
                      "width": width, "surface": "paved", "typical_minutes": None},
            "scenic": scenic,
            "highlights": [notes[name]] if notes.get(name) else [],
            "verify_url": verify,
            "confidence": "medium",
            "last_checked": TODAY,
        })
    return out, problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    geo, season, notes, facts = read_page()
    cat = json.load(open(PASSES, encoding="utf-8"))
    have = {r["id"] for r in cat}
    new, problems = build(geo, season, notes, facts)

    for p in problems:
        print("  ! " + p, file=sys.stderr)
    clash = [r["id"] for r in new if r["id"] in have]
    if clash:
        print("id already in the catalogue: " + ", ".join(clash), file=sys.stderr)
        return 1

    # Names an existing record should answer to, so the roadbook waypoint
    # resolves to it instead of becoming a second node for the same road.
    byid = {r["id"]: r for r in cat}
    added_alias = []
    for name, pid in ALREADY.items():
        r = byid.get(pid)
        if not r:
            problems.append(f"{pid}: no such record for alias {name}"); continue
        al = r.setdefault("alt_names", [])
        if name not in al and name != r["name"]:
            al.append(name); added_alias.append(f"{name} -> {pid}")

    # Rekey the matrix: same coordinate, so the same edges.
    edges = json.load(open(EDGES, encoding="utf-8"))
    E = edges["edges"]
    rename = {"geo_" + slug(r["name"]): r["id"] for r in new}
    rekeyed, missing = 0, []
    for r in new:
        old = "geo_" + slug(r["name"])
        if not any(k.split("|")[0] == old or k.split("|")[1] == old for k in E):
            missing.append(f"{r['name']} ({old})")
    out = {}
    for k, v in E.items():
        a, b = k.split("|")
        a2, b2 = rename.get(a, a), rename.get(b, b)
        if a2 != a or b2 != b:
            rekeyed += 1
        out[a2 + "|" + b2] = v

    print(f"new records      : {len(new)}")
    print(f"aliases added    : {len(added_alias)}" + ("  (" + "; ".join(added_alias) + ")" if added_alias else ""))
    print(f"edges rekeyed    : {rekeyed} of {len(E)}")
    print(f"catalogue        : {len(cat)} -> {len(cat) + len(new)}")
    if missing:
        print("  ! no edges found for: " + "; ".join(missing), file=sys.stderr)
    if args.dry_run:
        print("\n-- sample --")
        print(json.dumps(new[0], indent=2, ensure_ascii=False))
        return 0

    json.dump(cat + new, open(PASSES, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    edges["edges"] = out
    edges["rekeyed"] = TODAY
    json.dump(edges, open(EDGES, "w", encoding="utf-8"), indent=0)
    # Tile indices in the resume cache point into the old node order.
    if os.path.exists(CACHE):
        os.remove(CACHE)
        print("removed the fetch resume cache; node order changed")
    print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
