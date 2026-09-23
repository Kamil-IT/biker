# Test plan — TODO-024 Simple details search

**Test basis:** `backlog/TODO_024_SIMPLE_DETAILS_SEARCH.md` · **Change set:** uncommitted working tree on `main`
**Levels:** system (API) + system (UI, Playwright) · **Oracle for "which path ran":** backend log — count of
`POST https://api.anthropic.com/v1/messages` lines per request, plus the generic-cache row side effect.

## Requirement traceability

| # | Requirement | Implemented in | Status |
|---|---|---|---|
| R1 | No `categories.py` / `anthropic_scorer` / `CATEGORY_PROMPTS` / `BIKE_CATEGORIES` in `backend/app` | files deleted; `main.py` imports | Implemented |
| R2 | DB first over `bike` → `bike_detail` → `bike_detail_component` | `repository.py` `find_bikes_by_details` | Implemented |
| R3 | Only checkable fields filter; every given field must match | `repository.py` `_MATCHERS`, `checkable_fields` | Implemented |
| R4 | ≥1 DB match → only DB bikes, zero AI calls, no `set_cached` | `main.py` `bike_search` | Implemented |
| R5 | DB miss → exactly one Claude call, ≤5 `BikeResult`, `extract_json`, parse error → `[]` not 502 | `bike_finder.py` `find_bikes`, `prompts/bike_search.md` | Implemented |
| R6 | Only non-checkable fields (`bike_type`, `year`, `search`) → straight to AI | `find_bikes_by_details` returns `[]` when no checkable field | Implemented |
| R7 | Missing spec row ≠ match | matchers return False when no values | Implemented |
| R8 | DB-hit score/explanation/accessories from `search_bike_rating_cache`, else 10 + "Matches: …" + `[]` | `_latest_ratings`, `_describe_match` | Implemented |
| R9 | Response shape unchanged; frontend unmodified | `BikeSearchResponse`; no `frontend/` diff | Implemented |
| R10 | Smoke tests: DB-hit + DB-miss in `test_search.py` | TC-20/21/22/24 | Implemented |
| R11 | Docs updated (CLAUDE.md, README.md, backend/README.md) | — | Implemented |
| X1 | (not specified) DB results capped at 5, sorted by score | `MAX_DB_RESULTS` | Extra — design choice, flagged |
| X2 | (not specified) battery match tolerance ±10 %; Male/Female also match "Unisex" | `BATTERY_TOLERANCE`, `_GENDER_PATTERNS` | Extra — design choice, flagged |
| X3 | AI result cached only when non-empty | `main.py` | Extra — avoids pinning a parse failure |

## Test conditions (EP / BVA)

| Cond | Partition | Technique |
|---|---|---|
| C1 | request with checkable fields that match DB bikes | EP (valid, DB-hit) |
| C2 | request with checkable fields that match nothing | EP (DB-miss) |
| C3 | request with only non-checkable fields | EP |
| C4 | boolean fields true / false (`is_electric`, `belt_drive`) | EP both partitions |
| C5 | `battery_capacity_wh` at tolerance edges (±10 %) | BVA |
| C6 | case / Unicode brand variants | EP |
| C7 | empty payload | EP invalid |

## Test cases

| ID | Req | Pri | Type | Data | Expected |
|---|---|---|---|---|---|
| TC-024-01 | R1 | High | static | grep `backend/app` | no category references |
| TC-024-02 | R2,R4,R8 | High | API | `{"frame_material":"Carbon","wheel_size":"29\""}` | 200, 1–5 bikes, 0 Anthropic calls, no generic-cache row |
| TC-024-03 | R4,C6 | High | API | `{"brand":"trek","model":"MARLIN 5"}` | 200, only Trek Marlin 5, 0 AI calls |
| TC-024-04 | R3,C4 | High | API | `{"is_electric":true}` | every bike's details-cache has `Electric / Powertrain`; 0 AI calls |
| TC-024-05 | R3,C4 | Med | API | `{"is_electric":false,"frame_material":"Steel"}` | no returned bike has `Electric / Powertrain`; every frame Material steel-like |
| TC-024-06 | R3,C5 | Med | API | `{"is_electric":true,"battery_capacity_wh":625}` | every returned battery Capacity within 562.5–687.5 Wh |
| TC-024-07 | R3,C4 | Med | API | `{"belt_drive":true}` | every bike has a Drivetrain element containing "belt" |
| TC-024-08 | R5,C2 | High | API | `{"brand":"Trek","frame_material":"Carbon"}` | 200, 1–5 bikes, exactly 1 Anthropic call |
| TC-024-09 | R6,C3 | High | API | `{"bike_type":"Gravel","year":2024}` | 200, 1–5 bikes, exactly 1 Anthropic call, DB not consulted (log `find_bikes_by_details` absent or 0 fields) |
| TC-024-10 | R9 | High | API | response of 02 and 08 | keys exactly `search`,`bikes`; bike keys `brand,model,accessories,match_score,explanation` |
| TC-024-11 | C7 | Med | API | `{}` | 422 |
| TC-024-12 | R4,R9 | High | UI | Filters: Frame material Carbon + Wheel size 29" → Search | result cards render; card explanation "Matches: …"; 0 AI calls |
| TC-024-13 | R5,R9 | High | UI | Filters: Bike type Gravel only → Search | ≤5 cards render; exactly 1 AI call |
| TC-024-14 | R9 | Med | UI | click a DB-hit card | details view opens for that bike (regression) |

## Regression set

| ID | Area | Expected |
|---|---|---|
| RG-01 | generic cache: repeat TC-024-08 request | same JSON, 0 AI calls |
| RG-02 | `GET /v1/bike/search-cache?brand=Trek` | 200 |
| RG-03 | `GET /v1/bike/details-cache` for a DB-hit bike | 200 |
| RG-04 | full smoke `scripts/test_search.py` | exit 0 |
| RG-05 | no console errors in UI runs | none |

## Execution results — 2026-09-23 (final round 5)

**18 passed · 0 failed · 0 blocked** · smoke `scripts/test_search.py`: exit 0 (RG-04)

| Case | Result | Evidence |
|---|---|---|
| TC-024-01 | Pass | no category references in `backend/app` |
| TC-024-02 | Pass | 5 bikes, 0 AI calls, no generic-cache row |
| TC-024-03 | Pass | only Trek Marlin 5 (case-insensitive), 0 AI calls |
| TC-024-04 | Pass | all 5 bikes have `Electric / Powertrain` |
| TC-024-05 | Pass | all 5 steel, non-electric |
| TC-024-06 | Pass | all capacities within 562.5–687.5 Wh (e.g. 636.4 Wh) |
| TC-024-07 | Pass | all 5 have a belt drivetrain element |
| TC-024-08 | Pass | DB miss → exactly 1 AI call, 5 bikes |
| TC-024-09 | Pass | bike_type + year → DB skipped, exactly 1 AI call |
| TC-024-10 | Pass | response/bike keys unchanged |
| TC-024-11 | Pass | `{}` → 422 |
| TC-024-12 | Pass | UI: 5 "Matches: carbon frame, 29" wheels." cards, 0 AI calls |
| TC-024-13 | Pass | UI: Gravel → 1 AI call, all 5 bikes rendered |
| TC-024-14 | Pass | UI: DB-hit card opens details view |
| RG-01/02/03/05 | Pass | generic-cache repeat identical with 0 calls; search-cache 200; details-cache 200; no console errors |

**Oracle corrections during execution (expected results unchanged):** rounds 1–4 failures were all in the
test harness, not the product — `details-cache` 30 d TTL used as a spec oracle (switched to reading
`cache.db` directly), a CSS-uppercased "Back to results" text check, a battery regex that missed decimals,
and AI calls from a previously opened details page leaking into measured windows (now waits for the log
to go quiet and clicks only bikes with fresh details).

**Observation (pre-existing, out of scope):** opening a details page for a bike whose details are older
than 30 days re-runs the details AI pipeline and rewrites its `bike_detail_component` rows, so the set of
bikes a DB search matches can shift after browsing.
