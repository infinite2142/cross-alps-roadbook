# Notes for Claude Code

Single-file static site. `index.html` contains all HTML, CSS and JS — no build, no bundler,
no package manager. Edit it directly; there is nothing to compile.

Live at https://infinite2142.github.io/cross-alps-roadbook/ — GitHub Pages builds from `main`,
so a push deploys. Allow a minute, and append a cache-buster when checking, or you will read a
stale copy and draw the wrong conclusion.

## Conventions

- Vanilla JS, no framework. All rendering goes through `render(key)` where key is `'A'` to `'E'`
  — five route options, defined in `const D`. `Object.values(D)` order is tab order.
- CSS custom properties on `:root` drive the light theme; `body.dark` overrides them. **Never
  hardcode a colour** in new CSS or in generated SVG — use the tokens, or dark mode breaks.
- Both maps and all altitude profiles are generated SVG strings, redrawn on resize via
  `paintMap()` and `paintProfiles()`. They size their own text from the container's real pixel
  width, so don't add fixed `font-size` values to SVG text.
- The sticky header is `z-index:1100`, deliberately above Leaflet's panes. Don't lower it.
  Day and section headings stick under it at `z-index:900`.

## Data shapes

- `D[key].days[i].pts` — `[km, altitude, name, kind, country, note]`. `kind` is `'pass'`,
  `'stop'`, `'thru'` or empty. **`'thru'` means: show it in the roadbook and on the maps, but
  never hand it to Google as a routing stop** — for places the road merely passes, like Brescia.
- `GEO` — latitude/longitude per waypoint name. **Any new waypoint needs an entry here**, or it
  silently vanishes from every map while still appearing in the roadbook.
- `NOTES` — a descriptive line per waypoint name, applied across all routes. It only fills in
  where a point has no note of its own; it does not concatenate.
- `stays` — hotels per day: `{n, pick, loc, why, tel, pid}`. `tel` and `pid` are optional and
  the card degrades without them. `pid` is a Google Place ID; absent, the map link falls back to
  a name search. **Do not invent hotel names, phone numbers or Place IDs.** A day with
  `stays: []` renders a "Not chosen yet" card using its `staysNote`.
- `PASS_SEASON` — per-pass winter behaviour: `'winter'` shuts for the season, `'storm'` is cleared
  but closes for a day or two after heavy snow, `'open'` is a through route. **A pass you are not
  sure about goes in `'storm'`** — that is the claim that holds either way. Drives the season card's
  route-aware closure list, so a new pass needs an entry or it is silently treated as fine.
- `seasonLabel` — the calendar season at month granularity ("Late summer"), shown in the hero and
  the sticky header. It is deliberately **not** the same thing as the `SEASONS` band: in March the
  header reads "Early spring" while the band is still winter, because the passes are. Band labels
  therefore describe the roads, never the season's name, or the two contradict each other on screen.
- `SEASONS` — five bands keyed off today's date (`seasonFor`), each with a lede and points; winter
  wraps the year end and so is resolved separately from the others. `seasonLive` layers the live
  seven-day forecast on top. **The page must read correctly in any month** — never write a season
  into prose that is not gated on this. `TODO_ALL` items can gate on it too via `when`.
- `TODO_ALL` — the Check before you drive list. Each item carries a `when:` predicate using the
  `has(s, name)` and `country(s, cc)` helpers, so items appear only on routes they apply to.

## Traps that have already caused bugs here

- A later `header{position:…}` rule silently overrode `position:sticky`. Check for duplicate
  selectors before adding CSS. **A media query does not raise specificity**: `.sechead .ic`
  written after an `@media(max-width:760px)` block beat the rule inside it, so the narrow-viewport
  icon size never applied. Base rules go above their media blocks, not below.
- Leaflet must be visible before `fitBounds`, or it measures a zero-size box and zooms out fully.
- `localStorage` is fine here but fails in the Claude artifact sandbox — keep it in a try/catch.
- **Boot order.** `render('A')` runs last in the script on purpose: it calls `wxLoad()`, which
  touches `let`-bound state declared further down. Move the boot call up and every load throws.
- **Class-name collisions.** `.kw` was already the round waypoint marker in the map key; reusing
  it for a tab label drew a circle around the word. Grep a class name before inventing it.
- **Don't hardcode a measured offset.** The roadbook note's indent must equal the country tag's
  width plus its margin; two guessed values drifted apart between breakpoints. It is measured at
  render time into `--noteIndent`. Do the same for anything that must line up with rendered text.
- **Google Maps takes nine intermediate stops**, and that is the app's limit too, not just the
  URL's. Long days are split into legs by `gdirLegs()` so every waypoint gets through. Pinning
  only the passes lets Google cut corners; dropping a pass sends it down the valley instead.
- Touch fires `mouseover` but often no `mouseout` and never `mousemove`, so hover tooltips
  strand themselves unpositioned. Anything hover-driven needs a scroll/pointerdown escape.
- **Invisible hit targets go last in an SVG.** The day map painted its `.p-hit` circles before the
  pins, so a tap on the marker itself landed on the polygon, `closest('.p-hit')` found nothing, and
  the tooltip handler read it as a tap on blank space and closed. Painting them last fixed hopping
  between points. The altitude profile already appended its hits last, which is why it never had this.
- **Profile labels need reserved sky.** `ridgeSVG` places a label by searching *upward* from its
  marker and rejecting anything that crosses `top`, so a peak near `ALT_MAX` has nowhere to go
  and its label is dropped in silence — no warning, no fallback. `headroom` keeps two label lines
  clear above the highest ground. Count rendered `text.peak-label` against the `'pass'` points in
  the data before believing a profile is complete; the Stelvio was missing for a long time.
- **A profile has four failure modes and they trade against each other.** A pass label can go
  missing, print below its own marker (inside the fill, where it reads as a valley town), print
  out of altitude order, or overlap a neighbour. Fixing any one of them naively worsens another,
  so measure all four at ~1030, 620, 430 and 360px, on the whole-route chart *and* the day
  charts, before and after any change here. `__scan` patterns for this are in the git history.
- **The rules, in priority order.** A pass label outranks a waypoint label. A taller pass carries
  the higher label. A label sits above its own marker. Where they cannot all hold: put the name
  under the line, and failing that leave it out — never sideways, and never out of order.
  A displaced label is a wrong answer; a missing one is only a gap.
- **Ordering rules must be local.** Forbidding a pass label from sitting above *any* taller pass
  chained down the whole chart and pushed the Brenner below a Reschenpass 1000 km away, both of
  them into the fill. Scope it to labels that actually overlap horizontally — side by side is
  the only place the eye compares two heights.
- **`ridgeSVG` runs itself twice.** The first pass lays out with sky sized for the worst cluster
  on any route; the second re-runs with only what this chart used, so a flat day is not padded to
  the height a five-pass day needs. `opts.headroom` set means "this is the second pass" and stops
  the recursion. Cropping the viewBox instead does not work — the country band is pinned near the
  top of the box, so the empty gap is underneath it, not above.
- **A cluster needs reserved rows, not more sky.** Four passes whose markers span ten units
  cannot all fit between those markers and the tallest one's label. Raising `headroom` does
  nothing, because the ceiling was never the blocker. Each pass instead starts its search as
  many rows up as it has shorter passes crowded around it (`reserve`), leaving them the rows
  beneath, and the cluster resolves into a stack in altitude order.

## Verifying a change

Open `index.html` in a browser and check: **all five option tabs**, both map views, light and
dark, and a narrow viewport (~360px). Prefer measuring over eyeballing — collisions, alignment
and coverage are all countable in the console, and several bugs here looked fine and measured
wrong.

The Chrome tool's `resize_window` frequently reports success without changing `innerWidth`.
Check `window.innerWidth` before trusting a "responsive" check; if it has not moved, apply the
media query's declarations directly to validate the layout and say the breakpoint is unverified.
