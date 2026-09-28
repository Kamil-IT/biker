# Test plan — remove "Opcje zaawansowane" from the search UI

Request: "Usuń z UI search Opcje zaawansowane", then "Remove also from backend" (round 2).

Run: Vite on :5183, `/v1/bike/search` mocked in Playwright (no backend, no AI calls).

| ID | Case | Expected | Result |
|----|------|----------|--------|
| TC1 | Open Filtry | no "Opcje zaawansowane" toggle | Pass |
| TC2 | Open Filtry | no gender / frame material / brakes / drivetrain / battery fields, no belt-drive checkbox | Pass |
| TC3 | Open Filtry | brand, model, type, year, wheel size, frame size visible | Pass |
| TC4 | Tick e-bike | no battery field appears | Pass |
| TC5 | Brand "Trek" + 29" + e-bike → submit | payload `{brand, wheel_size, is_electric}` only | Pass |
| TC6 | Ukryj filtry | panel collapses | Pass |
| TC7 | Whole run | no console errors | Pass |

Round 1: 7 passed · 0 failed · 0 blocked.

## Round 2 — fields removed from the backend too

Backend on :8013 (local Postgres), no Anthropic API calls.

| ID | Case | Expected | Result |
|----|------|----------|--------|
| TC8 | `POST /v1/bike/search` with only `gender`/`drivetrain`/`belt_drive` | 422 "Provide at least one search field" | Pass |
| TC9 | `{brand: Trek, model: Marlin 5}` vs the same plus `gender`, `frame_material`, `brake_type`, `battery_capacity_wh` | identical 200 response (removed fields ignored) | Pass |
| TC10 | OpenAPI `SearchRequest` | only search, brand, model, year, wheel_size, is_electric, bike_type, frame_size | Pass |
| TC11 | `scripts/test_search.py` (no `--ai`) | all pass | Pass (9 passed, 3 skipped) |

Round 2: 4 passed · 0 failed · 0 blocked.
