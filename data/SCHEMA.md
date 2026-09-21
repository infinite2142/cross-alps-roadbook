# passes.json — record schema

Every field is static, authored data. Nothing here is fetched or generated at runtime.

```jsonc
{
  "id": "stelvio",                    // stable slug, used in URLs and edge keys
  "name": "Passo dello Stelvio",
  "alt_names": ["Stilfser Joch"],
  "countries": ["IT"],                // ISO-2; multi-country passes list both
  "region": "ortler",                 // groups for filtering + map clustering
  "summit_m": 2757,
  "coord": [46.5286, 10.4534],
  "roads": ["SS38"],

  "season": {
    "year_round": false,
    "typical_open": "05-25",          // month-day, TYPICAL, not a promise
    "typical_close": "11-05",
    "spread_days": 14,                // how much year-to-year variance to warn about
    "note": "Late openings in heavy-snow years; can shut for days after autumn storms."
  },

  "access": {
    "night_closure": null,            // e.g. {"from":"20:00","to":"05:00"}
    "timed_or_booked": false,         // Tre Cime / Grossglockner-style gates
    "vehicle_limits": "Caravans and trailers strongly discouraged; buses restricted."
  },

  "toll": {
    "type": "none",                   // none | road_toll | area_vignette | tunnel
    "band": null,                     // "free" | "under_20" | "20_50" | "over_50"
    "note": null
  },

  "drive": {
    "length_km": 49,
    "hairpins": 88,
    "difficulty": 4,                  // 1 easy .. 5 demanding
    "width": "two_lane_narrow",
    "surface": "paved",
    "typical_minutes": 95             // summit-to-summit driving time, not including stops
  },

  "scenic": 5,                        // 1..5, used to weight the generator
  "highlights": ["48 numbered hairpins on the north ramp", "Umbrail link into Switzerland"],

  "verify_url": "https://www.stelviopark.bz.it/",
  "confidence": "high",               // high | medium — surfaced in the UI
  "last_checked": "2026-09-21"
}
```

## Rules

- `typical_open` / `typical_close` are historical norms and are labelled as such everywhere
  they surface. The UI never says "open" — it says "usually open by late May, check before
  you go" with the verify link.
- `confidence: medium` renders a visible caveat.
- `toll.band` rather than a price. Prices change yearly; bands don't, and a wrong price is
  worse than no price.
- `last_checked` drives a staleness badge. Anything over 12 months old shows as unverified.
