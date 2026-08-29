# Notes for Claude Code

Single-file static site. `index.html` contains all HTML, CSS and JS — no build, no bundler,
no package manager. Edit it directly; there is nothing to compile.

## Conventions

- Vanilla JS, no framework. All rendering goes through `render(key)` where key is `'A'`, `'B'` or `'C'`.
- CSS custom properties on `:root` drive the light theme; `body.dark` overrides them. **Never
  hardcode a colour** in new CSS or in generated SVG — use the tokens, or dark mode breaks.
- Both maps and all altitude profiles are generated SVG strings, redrawn on resize via
  `paintMap()` and `paintProfiles()`. They size their own text from the container's real pixel
  width, so don't add fixed `font-size` values to SVG text.
- The sticky header is `z-index:1100`, deliberately above Leaflet's panes. Don't lower it.

## Traps that have already caused bugs here

- A later `header{position:…}` rule silently overrode `position:sticky`. Check for duplicate
  selectors before adding CSS.
- Leaflet must be visible before `fitBounds`, or it measures a zero-size box and zooms out fully.
- Adding a waypoint to `D` without a matching `GEO` entry drops it from the maps with no error.
- `localStorage` is fine here but fails in the Claude artifact sandbox — keep it in a try/catch.

## Verifying a change

Open `index.html` in a browser and check: all three option tabs, both map views, light and
dark, and a narrow viewport (~360px) where the profiles drop to two labels.
