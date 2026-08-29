# Cross-Alps Trip

Single-page roadbook for a three-day drive from Munich Airport across Austria and Italy,
plus an arrival evening.
Three switchable route options, per-day roadbooks with altitude
profiles, a schematic and a terrain map, tolls, hotels and a pre-departure checklist.

## Files

| File | What it is |
|---|---|
| `index.html` | The whole site. No build step, no framework, no dependencies to install. |
| `og.png` | 1200×630 link preview image. |
| `favicon.svg` | Tab icon. |
| `.nojekyll` | Stops GitHub Pages running the file through Jekyll. Must stay. |

## Publishing to GitHub Pages

```bash
git init
git add .
git commit -m "Cross-Alps roadbook"
git branch -M main
git remote add origin git@github.com:USER/REPO.git
git push -u origin main
```

Then in the repo: **Settings → Pages → Source: Deploy from a branch → main / (root)**.
Live at `https://USER.github.io/REPO/` within a minute or two.

Two things that will otherwise waste your time:

- The repo must be **public** unless you're on a paid plan.
- Don't link people to `raw.githubusercontent.com`. It serves `text/plain`, so the browser
  shows source code instead of a page.

### Absolute URL for the preview image

Link previews on Slack, WhatsApp, iMessage and X need an absolute URL. Once you know the
live address, change the one line in `index.html`:

```html
<meta property="og:image" content="https://USER.github.io/REPO/og.png">
```

Relative paths work in some scrapers and fail in others, so set this before sharing.
After changing it, re-scrape with Facebook's Sharing Debugger or just append `?v=2` to the
shared link — most platforms cache previews aggressively.

## External dependencies

The page loads two things from the network:

1. **Leaflet 1.9.4** from cdnjs — the terrain map.
2. **Map tiles** from OpenTopoMap, with an OpenStreetMap layer as an alternative.
3. **Fonts** from Google Fonts (Bricolage Grotesque, IBM Plex Sans, IBM Plex Mono).

Everything else — the schematic map, all altitude profiles, the hero panorama, every icon —
is generated in the page and works offline. If Leaflet or the tiles are blocked, the page
detects it, says so, and falls back to the schematic map.

### Vendoring Leaflet (optional)

If you'd rather not depend on cdnjs:

```bash
curl -O https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js
curl -O https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css
```

Then change the two tags in `index.html` to `href="leaflet.min.css"` and `src="leaflet.min.js"`.
Tiles still come from OpenTopoMap; there's no offline option for those.

## Known gaps, in priority order

1. **Theme choice doesn't persist.** It resets to light on reload. Two lines fix it once
   you're on your own domain — see below.
2. **Hotel "Website" links are Google searches**, not official domains. Search engines return
   OTA aggregators for all 19 hotels, so the domains were never verified. Replace them with
   real URLs for whichever three you actually book.
3. **Route lines are straight between waypoints**, not traced roads. The per-day Google Maps
   buttons build the real driving route.

### Persisting the theme

In `index.html`, find `function setTheme(dark)` and add the storage calls:

```js
function setTheme(dark){
  document.body.classList.toggle('dark',dark);
  document.getElementById('themeIcon').setAttribute('href', dark?'#i-sun':'#i-moon');
  document.getElementById('themeBtn').setAttribute('aria-pressed',dark);
  try{ localStorage.setItem('theme', dark?'dark':'light'); }catch(e){}
}
setTheme(localStorage.getItem('theme')==='dark');
```

Replacing the existing `setTheme(false);` line. This only works on a real domain — it's
disabled in the Claude artifact sandbox, which is why it isn't already in there.

## Editing

Everything lives in `index.html`. The parts you'll actually want to change:

- `const D = {…}` — the three route options. Each day is `pts: [[km, altitude, name, kind,
  country, note], …]` where `kind` is `'pass'`, `'stop'` or empty. Add a waypoint and the
  roadbook, both maps and the altitude profile all pick it up.
- `const GEO = {…}` — latitude/longitude per waypoint name. **Any new waypoint needs an entry
  here**, or it silently vanishes from the maps while still appearing in the roadbook.
- `const NOTES = {…}` — the descriptive line per waypoint, applied by name across all routes.
- `const TODO = […]` — the pre-departure checklist.
- `stays: […]` inside each day — hotels, with `pid` being the Google Place ID.

## Licensing and attribution

Map data © OpenStreetMap contributors (ODbL). Elevation from SRTM. OpenTopoMap style is
CC-BY-SA. The attribution control in the map carries this and must stay.
