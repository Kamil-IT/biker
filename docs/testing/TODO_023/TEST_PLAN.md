# Test plan — TODO-023 Remove five search filters

**Test basis:** `backlog/TODO_023_REMOVE_SEARCH_FILTERS.md` · branch `feature/remove-search-filters`
**Levels / types:** system (UI via Playwright) + API; functional, change-related (confirmation + regression)
**Environment:** backend `:8000` (restarted on branch code), frontend `:5173`, Chromium headless, existing `cache.db`
**Cost guard:** `/v1/bike/search` is intercepted in the browser (`page.route`, mocked response) so UI cases never run
the AI pipeline. API cases use requests already in the cache: generic key `{brand: trek, bike_type: mtb}` and the fresh
search row for Bianchi Oltre Race 105. Only `/v1/bike/parse` runs live (Haiku, ~2 calls, cached afterwards).
**Entry:** build passes, `pytest -m "not llm"` passes, OpenAPI serves the new schema. **Exit:** all High cases pass.

## Requirement traceability

| # | Requirement | Implemented in | Status |
|---|---|---|---|
| R1 | Filters panel shows none of the 5 controls | `frontend/src/components/SearchInput.tsx` | Implemented |
| R2 | Search payload never contains the 5 fields | `SearchInput.tsx` `buildPayload`, `frontend/src/types.ts` | Implemented |
| R3 | Parse sets no suspension/kids/height/weight | `backend/app/prompts/bike_parse.md`, `bike_parser.py`, `schemas.py` `ParseResponse`, `App.tsx` | Implemented |
| R4 | Text mentioning only removed attributes → "Not found" warning | existing 400 path (`main.py`) + `ParseResponse.is_empty()` | Implemented |
| R5 | Enriched query / cache key / API schema never carry the 5 fields | `schemas.py` `SearchRequest`, `main.py` `_fields` | Implemented |
| R6 | `price_max` no longer gates the DB-first path | `main.py` DB-first branch, `store.py` | Implemented |
| R7 | Build, unit tests, smoke tests and docs updated | `test_search.py`, `test_e2e_ui_db.py`, `pytest.ini`, `CLAUDE.md`, `backend/README.md` | Implemented |

## Test conditions

- **TCond-1 (R1, EP):** Basic group = {brand, model, bike type, year, wheel size, frame size} + one toggle (electric); Advanced group unchanged.
- **TCond-2 (R2, EP):** payload key set ⊆ allowed keys for any mix of remaining filters.
- **TCond-3 (R3/R4, EP over parse input):** partitions: (a) text with bike attrs + removed attrs → only bike attrs; (b) text with removed attrs only → 400; (c) text with bike attrs only → unchanged.
- **TCond-4 (R5, EP over API input):** (a) only removed fields → 422; (b) allowed + removed fields → removed ignored (same cache key, no labels).
- **TCond-5 (R6, BVA):** `price_max` = 1 (far below any price) on a DB-first hit → bike still served.
- **TCond-6 (state):** free text → parse fills filters (state *filters shown*, no search) → 2nd submit → search.

## Test cases

| ID | Req | Pri | Preconditions / data | Steps | Expected |
|---|---|---|---|---|---|
| TC-023-01 | R1 | High | app open | Open Filters, then Advanced options | No "Rider height", "Rider weight", "Max price", "Has suspension", "Kids bike" text/inputs (`#bike-rider-height`, `#bike-rider-weight`, `#bike-price-max` absent); Brand, Model, Bike type, Year, Wheel size, Frame size + "Electric bike (e-bike) only" present; Advanced fields present |
| TC-023-02 | R1 | Medium | — | Tick Electric, open Advanced | "Battery capacity (Wh)" field appears |
| TC-023-03 | R2 | High | search mocked | Fill brand=Trek, model=Marlin 7, type=MTB, year=2022, wheel 29", frame M, Electric, battery 500, gender Universal, material Aluminum, brakes Hydraulic Disc, drivetrain 1x, belt drive; submit | Exactly one `/v1/bike/search` request; body keys ⊆ allowed; none of the 5 removed keys; mocked results render |
| TC-023-04 | R3, TCond-6 | High | parse live, search mocked | Type "Trek Marlin 7 with front suspension for my kid" → submit | `/v1/bike/parse` 200; Brand=Trek, Model=Marlin 7 filled; filters shown; **no** search request; response has no removed keys. Second submit → one search request without removed keys |
| TC-023-05 | R4 | High | parse live | Type "Mam 185 cm wzrostu i ważę 100 kg" → submit | parse 400; warning "Bike not available in our database" above the box; no search request |
| TC-023-06 | R5 | High | API | POST `/v1/bike/search` `{is_kids, has_suspension, price_max, rider_height_cm, rider_weight_kg}` | 422 |
| TC-023-07 | R5 | High | API, generic key `{brand: trek, bike_type: mtb}` cached | POST `{brand: Trek, bike_type: MTB, price_max: 3000, is_kids: true, rider_height_cm: 180}` | 200 in < 5 s (same cache key as without the removed fields); `search` contains none of the removed labels |
| TC-023-08 | R5 | Medium | API | GET `/openapi.json` | `SearchRequest` and `ParseResponse` do not list the 5 fields |
| TC-023-09 | R6 | High | fresh DB row Bianchi Oltre Race 105 | POST `{brand: Bianchi, model: Oltre Race 105, price_max: 1}` | 200 in < 5 s; ≥1 bike, all Bianchi Oltre Race 105; no "Max price" in `search` |
| TC-023-10 | R3 | Medium | API | POST `/v1/bike/parse` `{"text": "Trek Marlin 7 2022, 29 inch, with suspension, non-electric"}` | 200; brand Trek, year 2022; keys ⊆ {brand, model, year, wheel_size, is_electric} |

## Regression set

| ID | Area | Check |
|---|---|---|
| RG-01 | Filters → search | TC-023-03 doubles as regression for all remaining filters |
| RG-02 | Parse → 2nd submit flow | TC-023-04 |
| RG-03 | 400 Not-found warning | TC-023-05 |
| RG-04 | DB-first brand+model hit | TC-023-09 |
| RG-05 | Console | No console errors on the search page during TC-023-01..05 |
| RG-06 | Build/unit | `npm run build`, `pytest -m "not llm"` green |

## Results — round 1 (2026-09-23)

**10 passed · 0 failed · 0 blocked** (functional cases), plus RG-05 (see note) and RG-06 green.

| Case | Result | Evidence |
|---|---|---|
| TC-023-01 | Pass | Removed controls absent; 6 Basic fields + electric toggle; 2 checkboxes total (electric, belt drive) |
| TC-023-02 | Pass | Battery field appears after ticking Electric |
| TC-023-03 | Pass | One search request; body has only allowed keys, incl. `battery_capacity_wh: 500`, `belt_drive: true` |
| TC-023-04 | Pass | Parse → `{brand: Trek, model: Marlin 7}` only; no search on 1st submit; 2nd-submit body has no removed keys |
| TC-023-05 | Pass | Parse 400 → "Bike not available in our database" warning; no search request |
| TC-023-06 | Pass | 422 |
| TC-023-07 | Pass | 200 in 2.36 s (generic-cache hit, same key); `search = "Brand: Trek, Type: MTB"` |
| TC-023-08 | Pass | OpenAPI schemas carry none of the 5 fields |
| TC-023-09 | Pass | `price_max: 1` → Bianchi Oltre Race 105 served from DB in 2.31 s |
| TC-023-10 | Pass | Parse keys ⊆ {brand, model, year, wheel_size, is_electric} |
| RG-05 | Pass* | *Only console entry was Chromium's network log of the **expected** 400 from TC-023-05; no application errors |
| RG-06 | Pass | `npm run build` ok; `pytest -m "not llm"` 16 passed |

Not run: the full `scripts/test_search.py` smoke suite (TC-21/TC-22 trigger paid AI-pipeline runs).
Screenshots: session scratchpad `tc023/`.
