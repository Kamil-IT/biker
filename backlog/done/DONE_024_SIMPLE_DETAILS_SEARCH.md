# TODO-024 — Replace category search with a simple details search

## Goal
Remove the category-based pipeline from `POST /v1/bike/search` and replace it with a simple search driven only by
the existing `SearchRequest` fields: **DB first, then one AI call**. No new request fields, no UI change.

## Decisions (agreed 2026-09-23)
1. **DB first, AI fallback.** Query `cache.db` first. If it returns **≥1** matching bike, return only those
   (may be fewer than 5) and make **no** AI call. Only when the DB returns nothing, make **one** Claude call.
2. **DB matching uses existing tables — no new columns / migration.** `bike` → `bike_detail` →
   `bike_detail_component` (`category` / `subcategory` / `element_name` / `spec_key` / `spec_value`).
3. **Only checkable fields filter.** A bike matches when **every given checkable field** matches. Fields the DB
   cannot check (`bike_type`, `year`, free-text `search`) are ignored by the DB step.
4. **Same response shape.** DB hits and AI hits both return `BikeResult` (`brand`, `model`, `accessories`,
   `match_score`, `explanation`). `BikeSearchResponse` and `ResultCard.tsx` stay as they are — no `category` field.
5. **Remove all category code and prompts** (list under Scope).

### Field → DB mapping
| `SearchRequest` field | Source in DB |
|---|---|
| `brand`, `model` | `bike.brand` / `bike.model` (case-insensitive, normalised in Python — not SQL `lower()`) |
| `frame_material` | `Frame / Frame`, `spec_key='Material'` |
| `wheel_size` | `spec_key='Wheel Size'`, or `Wheels/*` `Size` |
| `frame_size` | `spec_key='Sizes'` / `'Size'` on `Frame` |
| `gender` | `spec_key='Gender'` |
| `is_electric` | `true` → bike has an `Electric / Powertrain` category; `false` → it has none |
| `battery_capacity_wh` | `Electric / Powertrain / Battery`, `spec_key='Capacity'` (parse the Wh number) |
| `brake_type` | `Brakes/*` — `element_name` / `spec_key='Type'` text match |
| `drivetrain` | `Drivetrain/*` — `element_name` / `Speeds` text match |
| `belt_drive` | `Drivetrain/*` `element_name` contains "belt" |
| `bike_type`, `year`, `search` | **not checkable** → ignored by the DB step |

### Assumptions (confirm during implementation)
- A request with **only** non-checkable fields (e.g. only `bike_type`, or only `search`) skips the DB and goes
  straight to AI. Otherwise the DB would return every bike.
- A bike **missing** the relevant spec row (e.g. no `Gender`) does **not** match that field.
- DB-hit `match_score` / `explanation` / `accessories` come from `search_bike_rating_cache` when a row exists.
  Otherwise use a fixed score (all checkable fields matched → 10) and a generated sentence listing the matched
  fields, e.g. "Matches: carbon frame, 29\", hydraulic disc brakes", with `accessories=[]`.

## Behaviour
```
POST /v1/bike/search
  1. generic cache (get_cached)                 → hit: return
  2. DB details search (checkable fields ≥1)    → ≥1 bike: return (no AI, no set_cached)
  3. ONE Claude call (new prompt, enriched query) → up to 5 BikeResult
     → set_cached + save_search (happy path only)
```
- The AI call uses a new prompt `app/prompts/bike_search.md` that receives the enriched query and returns up to 5
  bikes as JSON `BikeResult`s. Parse with the shared `app/json_extract.extract_json()`. On a parse error, return an
  empty list, never a 502.
- The DB step replaces the current brand+model-only shortcut (TODO-009) and adds the other checkable fields.

## Scope
**Remove**
- `backend/app/categories.py`, `backend/app/anthropic_scorer.py`
- Category logic in `backend/app/bike_finder.py` (`filter_top_categories`, `allocate_bikes`,
  `find_bikes_for_category`, `find_all_bikes`). Replace the module with a single-call finder.
- Prompts: `app/prompts/{road,mountain,gravel,hybrid,electric,bmx,cruiser,touring,folding,cyclocross,kids}.md`
  and all `app/prompts/bike_search_{slug}.md`
- `CategoryResult` in `app/schemas.py`; `scripts/test_scoring.py`
- The scoring/allocation block in `main.py` `bike_search` (currently ~L102-145)

**Keep untouched**: `bike_details_*` prompts and finder, equipment categories, `/v1/bike/parse`,
`/v1/bike/search-cache`, `/v1/bike/details-cache`, frontend.

**Add**
- `repository.find_bikes_by_details(req: SearchRequest) -> list[BikeResult]` (or in `store.py`, next to
  `find_bike_by_brand_model`)
- `app/prompts/bike_search.md` plus the single-call finder
- Smoke tests in `backend/scripts/test_search.py`: a DB-hit case (a known bike from `cache.db` → no AI call,
  200) and a DB-miss case (→ AI, 200, ≤5 bikes)

**Docs**: `CLAUDE.md`, `README.md`, `backend/README.md` (endpoint Flow: 11+N calls → 0 or 1 call).

## Out of scope
- New `SearchRequest` fields, new DB columns or migrations
- Topping up DB results with AI results to reach 5
- Any frontend / `ResultCard` change
- Matching `bike_type` / `year` / free text in the DB

## Acceptance criteria
- [ ] No reference to `categories.py`, `anthropic_scorer`, `CATEGORY_PROMPTS` or `BIKE_CATEGORIES` remains in `backend/app`.
- [ ] A search whose checkable fields match ≥1 DB bike returns only DB bikes, with **zero** Anthropic calls (verify in logs).
- [ ] A search with no DB match makes exactly **one** Anthropic call and returns ≤5 `BikeResult`s.
- [ ] A search with only non-checkable fields goes straight to the AI call.
- [ ] Response shape is unchanged. The frontend works without modification.
- [ ] `scripts/test_search.py` passes against a running local server. Docs are updated.
