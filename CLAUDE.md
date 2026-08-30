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
- `TODO_ALL` — the Check before you drive list. Each item carries a `when:` predicate using the
  `has(s, name)` and `country(s, cc)` helpers, so items appear only on routes they apply to.

## Traps that have already caused bugs here

- A later `header{position:…}` rule silently overrode `position:sticky`. Check for duplicate
  selectors before adding CSS.
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

## Verifying a change

Open `index.html` in a browser and check: **all five option tabs**, both map views, light and
dark, and a narrow viewport (~360px). Prefer measuring over eyeballing — collisions, alignment
and coverage are all countable in the console, and several bugs here looked fine and measured
wrong.

The Chrome tool's `resize_window` frequently reports success without changing `innerWidth`.
Check `window.innerWidth` before trusting a "responsive" check; if it has not moved, apply the
media query's declarations directly to validate the layout and say the breakpoint is unverified.
