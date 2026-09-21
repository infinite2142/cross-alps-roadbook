# Route generator — handover brief

Written 2026-09-21. Read this with `CLAUDE.md`, which still describes the site as it is today.
This brief describes where it is going.

## What is changing

The site is a hand-authored roadbook for one trip: five fixed options (`D.A` … `D.E`) built
around a Munich departure on fixed dates. It is being turned into a public tool: the visitor
picks their own dates, start and end points and a few preferences, and the site assembles an
itinerary from a curated catalogue of Alpine passes covering France, Switzerland, Italy,
Austria and the Julian Alps.

The existing five options stay, as named presets, and become the regression test: the
generator must be able to reproduce something close to Option C.

## Hard constraints

1. **No LLM at runtime, and no server.** Today the page makes exactly one network call —
   Open-Meteo for weather. That property is deliberate and non-negotiable. The generator is
   deterministic JavaScript over static data. Tokens are spent authoring the catalogue, never
   serving it.
2. **The site never asserts that a pass is open.** It states the typical opening window, the
   year-to-year variance, and links to the official source. `confidence: "medium"` records
   render a visible caveat. This is the one thing separating this from the AI-generated
   travel sites already occupying these keywords; it only holds if it is applied without
   exception.
3. **Everything must read correctly in any month.** Already a rule in `CLAUDE.md` via
   `SEASONS` / `seasonFor`. It now extends to generated itineraries: a January visitor
   planning for July must see July's pass availability, not today's.

## Data

- `data/passes.json` — the catalogue. Schema and authoring rules in `data/SCHEMA.md`.
  Currently **34 seeded records**; the target is roughly 110–130 for the full Alpine arc.
  This is the bulk of the remaining work and the part that needs re-verifying each spring.
- `data/edges.json` — **not yet written.** Drive times and distances between catalogue nodes,
  computed once at build time and committed. See "Drive-time matrix" below.

`passes.json` supersedes the inline `PASS_SEASON` map, which only knows three states
(`winter` / `storm` / `open`) and no dates. Migration: derive `PASS_SEASON`-equivalent
behaviour from `season.year_round` and the opening window, and delete the inline map once
every pass it names has a catalogue record. Do not run both as sources of truth.

`GEO` and `NOTES` are likewise absorbed — `coord` and `highlights` live on the record. The
`CLAUDE.md` warning still applies in spirit: **a waypoint with no coordinate vanishes from
every map while still rendering in the roadbook**, so validate on load that every referenced
id resolves.

## Drive-time matrix

The generator needs distance and time between catalogue nodes. Options considered:

- Straight-line distance times a terrain factor — cheap, and wrong enough on pass roads to
  produce itineraries that do not fit in a day.
- Routing API at runtime — breaks constraint 1.
- **Routing API at build time, result committed as `data/edges.json`** — chosen.

Run it from this machine, not from a cloud session; outbound network there is restricted.
Sparse is fine: only edges between nodes within roughly 150 km need computing, which is a few
thousand calls against a free tier, run once and re-run only when the catalogue grows.

Calibration check: the generator's estimate for the existing Option C days should land within
about 10% of the times already in `D.C`, which were verified on the ground in September 2026.

### Built, 2026-09-21 — and what the calibration found

150 nodes (34 passes plus 116 places still read out of `GEO`), 11,175 edges, 9 API requests.
`python3 tools/edges.py verify` chains all twenty authored days through the matrix.

**Distance passes.** Worst case 7%, most days within 3%. Usable as-is.

**Time does not, and not by a constant.** Worst case 31%, and the error changes sign with the
character of the road:

| day type | example | routed vs authored |
|---|---|---|
| hairpin passes | C day 1, Stelvio + Umbrail + Gavia | **−22%** (router too optimistic) |
| hairpin passes | D day 2, Canazei → Zell am See | **−31%** |
| motorway | E day 0, Munich → Zell am See | **+31%** (router too pessimistic) |
| motorway | C day 3, Bruneck → Munich | **+22%** |

Averaged: fast days (≥60 km/h routed) run +12%, slow days −7%. A single scale factor cannot
fix a bias that reverses, so **the generator cannot use ORS durations directly** for its
daily-hours constraint — the one thing that decides whether a day is drivable. This is an
open question, below.

Two bugs the calibration surfaced, both of the silent kind: a node 300 m off its road returned
zero edges while every other node returned 148, and the `GEO` parser mangled every waypoint
name containing an apostrophe. Both are recorded in `CLAUDE.md` under traps; `fetch` now fails
loudly on an unroutable node.

## Generator

Beam search over the node graph. Per candidate itinerary:

- split into days under a max-driving-hours constraint (default 5 h moving time, user
  adjustable — the existing roadbook shows why 7 h of alpine driving is not 7 h of motorway)
- reject or flag any pass whose typical window excludes the chosen dates
- reject anything whose daily driving exceeds usable daylight for those dates — `sunTimes` /
  `sunFor` already compute this locally with no network, for any date
- score on `scenic`, pass count, altitude gained, and a penalty for backtracking
- return the top handful as options, in the existing `D`-shaped structure so `render()`,
  `paintMap()` and `paintProfiles()` keep working unchanged

That last point matters: **the renderer should not need to know whether a route was authored
or generated.** Generate into the existing shape and the whole display layer comes for free.

## Date inputs

Four things change with the chosen dates. All four were requested:

- pass open/closed likelihood, from `season.typical_open` / `typical_close` / `spread_days`
- daylight and driving windows, from `sunFor`
- weather — extend the existing Open-Meteo call where the dates fall inside the forecast
  horizon, and fall back to a seasonal note beyond it. Never present climatology as a forecast.
- seasonal pricing and opening hours — toll bands, gate hours, cable cars and mountain
  restaurants

## Hosting

Moving front-end hosting from GitHub Pages to Cloudflare Pages, connected to this repo so a
push still deploys. Leave the GitHub Pages deployment up with a redirect; the OG image URL and
any shared links point at it. Cloudflare Web Analytics on — free, cookieless, no consent
banner, no per-user tracking.

**OpenTopoMap tiles must be replaced before any real traffic arrives.** It is a volunteer
server with a fair-use policy that a public tool would breach. Protomaps served as static
files from Cloudflare keeps running cost at zero and fits the no-server constraint.

## Decisions taken, 2026-09-21

`CLAUDE.md` opens with "single-file static site … no build, no bundler". A catalogue of 130
passes plus an edge matrix is too large to keep inlining by hand, so that had to give.

**Resolved: (a) keep the single file, add a build step** that inlines `data/*.json` into
`index.html`. Offline use is a real differentiator against the assistants — it mattered on the
actual trip, in valleys with no signal — and a short inlining script is a smaller change than a
service worker. The rejected alternative was splitting the file and fetching the JSON at
runtime. `index.html` stays the artefact that deploys; `data/*.json` becomes the thing humans
edit. **Never hand-edit the inlined block.**

Five design decisions taken at the same time:

- **Both route shapes, loop first.** Round trip from a single base is what most people drive and
  is the harder search; point-to-point falls out of it nearly free. Build the loop first.
- **Fixed dates.** Start date plus nights. Feeds pass windows, `sunFor` daylight and Open-Meteo
  directly. A flexible window ("8 days sometime in June") is a better product and a much larger
  search — revisit once the fixed case is honest.
- **Land on a rendered example.** A first-time visitor sees the existing Option C fully
  rendered, with the planner bar above it inviting change. Not an empty form: a public visitor
  given a form and no output has no reason to fill it in.
- **Three editing operations, no more.** Swap a pass for an alternative within reach, split a
  long day, merge two short ones. Each is a small re-run of the existing search. Anything beyond
  this is a map editor and breaks the "inputs fit in a URL hash" story.
- **Results are labelled by character, not number.** "Most passes", "Gentlest days", "Highest",
  "Least motorway", "Closest to the classic". Nobody can choose between "Option 3" and
  "Option 4". Candidates sharing most of their passes with a better-scoring one are dropped
  rather than shown as a second option.

## Display

The generator returns into the existing `D` shape, so the tab strip changes meaning rather than
disappearing: it holds generated candidates instead of hand-authored options, and `render()`,
`paintMap()` and `paintProfiles()` are untouched. The five hand-authored options become named
presets reachable from the planner.

- **Planner bar** — four visible inputs: from / to (or round-trip-from), start date, nights, and
  one pace control ("how long do you want to be in the car?", default 5 h moving time).
  Everything else — avoid unpaved, avoid tolls and vignettes, avoid gated or timed passes,
  caravan, max altitude — collapses behind "more".
- **Pass status chip**, on every pass row: "usually open late May – early Nov · ±14 days ·
  check", coloured against the chosen dates as in-season / shoulder / usually shut. Per
  constraint 2 there is no green "open" state, in any month, for any pass.
- **"What might be shut, and what you'd do"** — a route-level card above day 1, listing the
  passes near the edge of their window for those dates, each with a concrete detour and the
  minutes it adds. Appears only when it applies. This card is the reason the site is worth
  more than a chatbot answer, and it is only possible because the edge matrix exists.
- **URL hash** carries the inputs. Deterministic search over static data means reopening the
  hash reruns to the same itinerary — shareable and bookmarkable with no server and no storage.

## Still open

**1. Drive time needs a road-character correction.** See the calibration above. The ingredients
are already in the catalogue — `drive.difficulty`, `drive.hairpins`, `drive.typical_minutes` —
and there are twenty authored days to fit against, which is few but real. The honest options
are to fit a two-parameter correction keyed on road character, or to use `typical_minutes` for
the pass segments and the router only for the connecting roads. Until one is chosen, any
generated "5 hours of driving" is wrong by up to a third in whichever direction flatters the
route least.

**2. Inlining does not scale to the full catalogue.** With 150 nodes the matrix inlines to
498 KB — `index.html` is 748 KB raw, 169 KB gzipped, and loads in 135 ms. Fine. But the matrix
is quadratic in nodes, and the target is 110–130 passes plus their places:

| nodes | edges | inlined, raw |
|---|---|---|
| 150 (today) | 11,175 | 0.5 MB |
| 250 | 31,125 | 1.4 MB |
| 430 (target) | 92,235 | **4.2 MB** |

Option (a) was chosen on the basis that the file "grows past 500 KB". At 4 MB that reasoning no
longer holds and offline capability has to be bought another way. Pruning to edges under
~150 km removes 46% of pairs, and a tighter encoding removes more; between them this is
probably survivable, but it should be decided before the catalogue grows rather than after.

**3. The catalogue is 34 of a target 110–130**, and covers only 6 of the 33 passes the existing
roadbook names. The rest fall back to the coarse `PASS_SEASON` classification, which the
closure card states plainly rather than hiding.

**4. OpenTopoMap tiles** must be replaced with Protomaps before any real traffic arrives.
