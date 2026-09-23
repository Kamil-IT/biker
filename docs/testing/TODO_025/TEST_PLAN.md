# Test Plan — TODO-025 Remove the 5-bike limit from search

**Test basis:** `backlog/TODO_025_REMOVE_SEARCH_RESULT_LIMIT.md` (acceptance criteria R1–R8)
**Change set:** uncommitted diff on `main` — `bike_finder.py`, `prompts/bike_search.md`, `repository.py`, `scripts/test_search.py`, `frontend/src/App.tsx`, docs
**Environment:** backend `uvicorn --reload` :8000, frontend Vite :5173, Chromium (Playwright, headless), `backend/cache.db`
**Techniques:** equivalence partitions + boundaries on result count (0 / 1 / 5 / >5 / many), error guessing (parse failure, truncation), state transition (idle → loading → results / not-found)
**Cost guard:** AI-path cases reuse queries already cached; frontend rendering boundaries use Playwright route interception (no AI calls).

## Requirement traceability

| # | Requirement | Implemented in | Status | Notes |
|---|---|---|---|---|
| R1 | No constant / slice / prompt text limits the count | `bike_finder.py` (TOTAL_BIKES removed), `repository.py` (MAX_DB_RESULTS removed), `prompts/bike_search.md` | Implemented | |
| R2 | DB query with >5 matches returns all | `repository.py` `find_bikes_by_details` returns `results` | Implemented | |
| R3 | Broad AI query can return >5, JSON not truncated | `bike_finder.py` `MAX_TOKENS = 8000` + `stop_reason` warning | Implemented | |
| R4 | Impossible filters → ≥1 closest bike, low score, names unmet filter | `prompts/bike_search.md` "Return at least one bike…" | Implemented | |
| R5 | Parse error → `bikes: []`, 200, not cached, frontend "Not found" | `bike_finder.py` returns `[]`; `main.py` `if bikes:` guard; `App.tsx` not-found alert | Implemented | |
| R6 | Frontend renders 1 / 5 / 10+; skeletons not tied to 5 | `App.tsx` `LOADING_CARDS = 3` | Implemented | |
| R7 | Smoke test asserts `len(bikes) >= 1` | `scripts/test_search.py` (first search, TC-21/22/24, new TC-26) | Implemented | |
| R8 | Docs updated | `CLAUDE.md`, `README.md`, `backend/README.md`, `frontend/README.md` | Implemented | |
| X1 | (extra) card animation delay capped at 8 × 65 ms | `App.tsx` `Math.min(i, 8) * 65` | Extra | keeps a 50-card list from fading in over seconds |

## Test cases

| ID | Req | Pri | Preconditions / data | Steps | Expected result |
|---|---|---|---|---|---|
| TC-025-01 | R1 | High | repo | `grep -rn "TOTAL_BIKES\|normally 5\|MAX_DB_RESULTS" backend/app` | no matches |
| TC-025-02 | R2 | High | cache.db has >5 bikes with 29" wheels | UI: Filters → Wheel size `29"` → Find | results count equals `find_bikes_by_details(wheel_size='29"')` (>5); no AI call (< 5 s) |
| TC-025-03 | R3 | High | `{"bike_type":"Gravel"}` | UI: Filters → Bike type Gravel → Find | > 5 result cards; valid response |
| TC-025-04 | R4 | High | `{"brand":"Trek","is_electric":true,"brake_type":"Rim"}` | API POST | ≥ 1 bike; top `match_score ≤ 4`; explanation mentions rim brakes |
| TC-025-05a | R5 | High | `find_bikes` with the client stubbed to return prose | call `find_bikes()` | returns `[]`, no exception |
| TC-025-05b | R5 | High | FastAPI TestClient, `find_bikes` stubbed → `[]`, unique query | POST /v1/bike/search | 200, `bikes: []`, no generic-cache row written |
| TC-025-05c | R5 | High | Playwright route → `{search, bikes: []}` | submit a search | "Not found:" alert in results section, zero result cards |
| TC-025-06 | R6 | High | route → 1, 5, 12 bikes | submit each | exactly 1 / 5 / 12 cards, rank 1 marked top, no console errors |
| TC-025-07 | R6 | Med | route delayed 3 s | submit, inspect while loading | exactly 3 skeleton cards |
| TC-025-08 | R7 | Med | test file | static review + `py_compile` | asserts are `>= 1`, no `<= 5`; compiles |
| TC-025-09 | R8 | Low | docs | grep for "up to 5 bikes / (5 bikes) / max 5" in search docs | none left |

## Regression set

| ID | Area | Steps | Expected |
|---|---|---|---|
| RG-01 | Cached free-text search | Search "comfortable bike for daily 10 km city commute, mostly paved roads" | results render, served from cache |
| RG-02 | Result card → details | Click first card of RG-01 | details view opens with that bike's name |
| RG-03 | Parse 400 warning | route `/v1/bike/parse` → 400 | "Not found:" warning above search box, no search |

## Results — 2026-09-23

**Round 1:** 2 failures. (1) TC-025-08: `test_search.py` TC-26 had a raw newline inside a string literal (SyntaxError). Fixed in `backend/scripts/test_search.py`. (2) TC-025-06: wrong test oracle. The top card intentionally has no `Rank N` label and `get_by_label("Rank 1")` also matched "Rank 10/11". The locator was corrected; the expected result did not change. The RG-01 test data was swapped from pure free text (a 400 from parse, which is existing TODO-023 behaviour) to "Trek Marlin 5". During exploration, the first run of TC-025-04 scored 7.0 on a bike that did not meet the filters, so the prompt was tightened: a missed filter now means `match_score ≤ 4` and the explanation starts with the missed filter.

**Round 2: 15 passed · 0 failed · 0 blocked**

| Case | Result | Evidence |
|---|---|---|
| TC-025-01 | Pass | grep empty |
| TC-025-02 | Pass | 57 cards = 57 DB matches, 0.3 s (no AI) |
| TC-025-03 | Pass | 7 cards for `bike_type: Gravel` |
| TC-025-04 | Pass | 1 bike, Trek Allant+ 7, score 4.0, "Trek does not offer an e-bike with rim brakes; …" |
| TC-025-05a | Pass | prose reply → `[]` |
| TC-025-05b | Pass | 200, `bikes: []`, 0 cache rows |
| TC-025-05c | Pass | "Not found: No bikes matched this search…" in the results section |
| TC-025-06 (1/5/12) | Pass | exact card counts, all visible, no console errors |
| TC-025-07 | Pass | 3 skeletons while loading, 0 once loaded |
| TC-025-08 | Pass | asserts `>= 1`, compiles |
| TC-025-09 | Pass | no "5 bikes" left in the search docs |
| RG-01 / RG-02 / RG-03 | Pass | parse → search → card → details; parse-400 warning, no search call |

Not run: the full `backend/scripts/test_search.py`, because it triggers many uncached AI calls (details, offers, reviews).
