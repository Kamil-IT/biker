# TODO-003 — Add Basic Filters to Bike Search

## Goal
Expose the structured search fields already supported by the backend (`brand`, `year`, `wheel_size`, `is_electric`, `has_suspension`, `is_kids`) as UI controls on the search form.

## Behaviour
- Filters are optional; user can search with free text only (existing behaviour).
- Submitting with any filter populated sends the structured fields alongside `search`.
- Backend already assembles them into an enriched query via `SearchRequest.enriched_query()` — no backend changes needed.

## Fields to add

### Already in backend (`SearchRequest`) — frontend only
| Field | UI control | Type |
|---|---|---|
| Brand | Text input | string |
| Year | Number input | integer |
| Wheel size | Dropdown: 12" / 14" / 16" / 20" / 24" / 26" / 27.5" / 28" / 29" / 700c | string |
| Electric | Toggle / checkbox | bool |
| Suspension | Toggle / checkbox | bool |
| Kids | Toggle / checkbox | bool |

### New fields — require backend + frontend changes

**High priority** (most searched across Kross, Romet, Centrum Rowerowe):
| Field | UI control | Type | Values |
|---|---|---|---|
| `bike_type` | Dropdown | string | Road, MTB, Gravel, Hybrid/Commuter, Touring, BMX, Cruiser, Folding |
| `price_max` | Number input (PLN) | integer | budget ceiling |
| `frame_size` | Dropdown | string | XS, S, M, L, XL, XXL |
| `rider_height_cm` | Number input (cm) | integer | 80–210 |

**Medium priority** (fit + technical buyers):
| Field | UI control | Type | Values |
|---|---|---|---|
| `gender` | Dropdown | string | Male, Female, Universal |
| `frame_material` | Dropdown | string | Aluminum, Carbon, Steel |
| `brake_type` | Dropdown | string | Hydraulic Disc, Mechanical Disc, V-brake, Rim |

**Low priority** (niche / advanced):
| Field | UI control | Type | Values |
|---|---|---|---|
| `drivetrain` | Dropdown | string | 1x, 2x, 3x |
| `belt_drive` | Toggle / checkbox | bool | — |
| `battery_capacity_wh` | Number input (Wh) | integer | shown only when `is_electric=true` |

## Scope
### Frontend
- `src/components/SearchInput.tsx` — add an expandable "Filters" section below the main search bar; show/hide with a toggle button. Group into Basic (brand, bike type, wheel size, frame size, rider height, price max) and Advanced (gender, frame material, brake type, drivetrain, belt drive, battery capacity).
- `src/App.tsx` — pass filter state down to `SearchInput` and include all fields in the `/v1/bike/search` request body.
- `src/types.ts` — add `SearchFilters` interface covering all fields.

### Backend
- `app/schemas.py` — add new fields to `SearchRequest`: `bike_type`, `price_max`, `frame_size`, `rider_height_cm`, `gender`, `frame_material`, `brake_type`, `drivetrain`, `belt_drive`, `battery_capacity_wh` (all optional).
- `app/schemas.py` — update `SearchRequest.enriched_query()` to incorporate the new fields into the enriched query string passed to Claude.

## Acceptance criteria
- [ ] Filters panel toggles open/closed.
- [ ] Submitting with brand="Trek" sends `{ "search": "...", "brand": "Trek" }`.
- [ ] Toggles send boolean values correctly.
- [ ] Clearing filters resets to free-text-only search.
- [ ] Wheel size dropdown includes all sizes from 12" to 700c.
- [ ] New high-priority fields (bike_type, price_max, frame_size, rider_height_cm) appear in the Basic filters group.
- [ ] Medium and low priority fields appear in an Advanced filters group, collapsed by default.
- [ ] `battery_capacity_wh` input is only shown/enabled when `is_electric` is toggled on.
- [ ] All new fields are included in the `/v1/bike/search` request body when set.
- [ ] Backend `enriched_query()` incorporates all new fields into the query string.
