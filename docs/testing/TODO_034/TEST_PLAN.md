# Test plan — TODO-034 Popular bikes on the home page

**Branch:** `feature/popular-bikes` · **Task:** `backlog/TODO_034_POPULAR_BIKES.md` · **Date:** 2026-09-28
**Environment:** worktree `biker-wt/feature-popular-bikes`, backend `uvicorn` on `127.0.0.1:8002` (local PostgreSQL 17
`biker-pg`, `bike_popular` seeded with 3 rows), frontend Vite on `localhost:5176` (`BIKER_API_URL=http://localhost:8002`),
Chromium headless via Playwright (global Python 3.14). All three seeded bikes have `/v1/bike/details` and `/v1/bike/review`
rows in the generic cache, so no case calls the Anthropic API; the search case uses a DB-hit (`Trek` / `Marlin 5`).

## Requirement traceability — TODO-034

| # | Requirement (from task) | Implemented in | Status | Notes |
|---|---|---|---|---|
| R1 | Before the first search the home page shows "Najpopularniejsze rowery" under the search form, 3 result-style cards | `frontend/src/App.tsx:53` (hook), `App.tsx:529-535` (render), `frontend/src/components/PopularBikesSection.tsx` | Implemented | |
| R2 | A card click opens the details view | `PopularBikesSection.tsx:37-56` → `App.tsx handleBikeSelect` | Implemented | same handler as a search result |
| R3 | Section hidden while a search runs and while results show; back after "Nowe wyszukiwanie" / reset / back from details | `App.tsx:530` (`!showResults && popularBikes.length > 0`) | Implemented | |
| R4 | Table `bike_popular` (`bike_id` FK unique, `position`), created by `init_db()` | `backend/app/models.py` `BikePopular` | Implemented | created on the local DB at first start |
| R5 | `GET /v1/bike/popular` → `{ bikes: [{ brand, model, description }] }`, ordered by position, description = first two sentences, pure DB read, empty table → `200 []` | `backend/app/popular_repository.py` (`get_popular_bikes`, `first_sentences`), `backend/app/main.py:198-202`, `backend/app/schemas.py:108-117` | Implemented | DB error → `200 []` + ERROR log |
| R6 | Card shows the expert rating in points from one `POST /v1/bike/review` per bike; "—" pending; "Brak oceny" on error / rating 0 | `frontend/src/hooks/usePopularBikes.ts`, `frontend/src/components/ResultCard.tsx` (`expertRating`) | Implemented | label "Ocena eksperta" / "Ocena eksperta…" / "Brak oceny" |
| R7 | Description (first 1–2 sentences) under the points | `popular_repository.first_sentences` → card explanation slot | Implemented | stored descriptions of the 3 seeded bikes are English (data, not code) |
| R8 | Seed script fills 3 bikes with complete data into the local PostgreSQL | `backend/scripts/seed_popular_bikes.py` | Implemented | rows: Cannondale Topstone Carbon 4 (7.2), Trek Madone SL 6 (8.2), Giant Revolt Advanced Pro (8.4) |
| R9 | Smoke test in `backend/scripts/test_search.py` | `case_popular` | Implemented | |
| X1 | (not requested) details header hides its "Dopasowanie" block when `match_score` is 0 | `frontend/src/components/BikeDetailsView.tsx:77-82,121-134`, `PopularBikesSection.tsx` passes `match_score: 0` | Extra | needed so a popular bike does not show its expert rating as a match score — confirm with the user |

## Test conditions

| ID | Condition | Technique | Requirements |
|---|---|---|---|
| C1 | Initial home page render: section, 3 cards in seed order, ranks, no "best match" badge, no percentage | use case | R1, R7 |
| C2 | Card rating equals the `rating` of that bike's `/v1/bike/review`; exactly 3 review calls and 1 popular call | state / oracle = API | R6 |
| C3 | Review call states: pending → loaded; error (500) and rating 0 → "Brak oceny" | state transition, EP | R6 |
| C4 | Popular list edge cases: empty list, HTTP 500 → no section, page still usable | EP / error handling | R1, R5 |
| C5 | Section visibility across the search lifecycle: idle → loading → results → new search (state machine) | state transition | R3 |
| C6 | Navigation: popular card → details view → back; details header without "Dopasowanie" | use case | R2, X1 |
| C7 | Regression: search result cards keep percentage + match label; a search result's details header keeps "Dopasowanie" | regression | X1 |
| C8 | API contract of `GET /v1/bike/popular` (shape, order, two-sentence blurb, latency, no cache row) | interface | R5 |
| C9 | Responsiveness at phone width (375 px): no horizontal overflow | non-functional | R1 |
| C10 | Backend smoke test `case_popular`; seed dry-run reproduces the 3 rows | change-related | R8, R9 |

## Test cases

Common preconditions: backend on `:8002` with the 3 seeded rows, frontend on `:5176`, cached reviews/details for the 3 bikes.

| ID | Title | Req | Steps | Expected result | Priority |
|---|---|---|---|---|---|
| TC-034-01 | Section with 3 cards on first load | R1, R7 | Open `/`, wait for network idle | `section[aria-label="Najpopularniejsze rowery"]` visible under the form with eyebrow "Najpopularniejsze rowery"; exactly 3 card buttons, in order Cannondale Topstone Carbon 4 → Trek Madone SL 6 → Giant Revolt Advanced Pro with ranks #1 #2 #3; each card's text equals the API `description`; no "Najlepsze dopasowanie", no `NN%` text | High |
| TC-034-02 | Expert rating in points | R6 | Same page; wait until no card shows "Ocena eksperta…" | Cards show 7.2 / 8.2 / 8.4 with "/ 10" (= the `rating` of `POST /v1/bike/review` for each), label "Ocena eksperta", progressbar `aria-valuenow` = rating, aria-label "…ocena eksperta 7.2 na 10"; network: 1× `GET /v1/bike/popular`, 3× `POST /v1/bike/review`, all 200 | High |
| TC-034-03 | Pending state, then loaded | R6 | Hold every `/v1/bike/review` response; open `/`; inspect; release the responses | While held: numeral "—", label "Ocena eksperta…", aria "w trakcie wczytywania"; after release: ratings as in TC-02 | Medium |
| TC-034-04 | Failed review and rating 0 read "Brak oceny" | R6 | Route review: bike 1 → HTTP 500, bike 2 → 200 with `rating: 0`, bike 3 → real | Cards 1 and 2: "—", label "Brak oceny", aria "brak oceny", progressbar 0; card 3: 8.4 "Ocena eksperta"; page has no uncaught error | High |
| TC-034-05 | Empty list / failing endpoint hides the section | R1, R5 | (a) route popular → `{ "bikes": [] }`; (b) route popular → HTTP 500 | Section absent in both, hero and search form rendered, no uncaught page error | Medium |
| TC-034-06 | Hidden while searching and with results | R3 | Open `/`, click "Filtry", brand `Trek`, model `Marlin 5`, submit | Section disappears at once (loading) and stays hidden once results are shown; results section shows ≥ 1 card with a `NN%` percentage and a "…dopasowanie" label (regression C7) | High |
| TC-034-07 | Search result's details keep "Dopasowanie" (regression) | X1 | From TC-06 results click the first card; then "Wróć do wyników" | Details header shows exactly one "Dopasowanie" eyebrow with the score; after back, results still shown and the popular section still hidden | Medium |
| TC-034-08 | Back after "Nowe wyszukiwanie" | R3 | From TC-07 click "Nowe wyszukiwanie" | Popular section visible again with the same 3 cards and ratings already loaded; `GET /v1/bike/popular` was sent only once in the whole flow | High |
| TC-034-09 | Popular card opens details without "Dopasowanie" | R2, X1 | Open `/`, click card 1 (Cannondale), then "Wróć do wyników" | Details view with h1 "Cannondale" and model "Topstone Carbon 4"; no "Dopasowanie" eyebrow; Expert Review section present (cached); back → search view with the popular section visible | High |
| TC-034-10 | No console errors on the home page | R1 | Collect console errors during TC-01/02 | No `error` console messages, no `pageerror` | Medium |
| TC-034-11 | Phone width | R1 | Viewport 375×812, open `/` | Section visible, `scrollWidth <= clientWidth` (no horizontal scroll) | Low |
| TC-034-12 | API contract | R5 | `GET http://127.0.0.1:8002/v1/bike/popular` | 200 JSON `{ bikes: [3] }` in seed order; each `description` non-empty with at most two sentences; < 1 s; no `endpoint_req_to_body_cache` row for `/v1/bike/popular` | High |
| TC-034-13 | Backend smoke `case_popular` | R9 | run `case_popular` against `:8002` | PASS | High |
| TC-034-14 | Seed dry-run | R8 | `python scripts/seed_popular_bikes.py --dry-run` | Prints the same 3 picks in the same order; table unchanged | Low |

## Regression set

TC-034-06 (search result cards), TC-034-07 (details header of a search result), TC-034-08 ("Nowe wyszukiwanie"), TC-034-09 (details navigation) — run after every fix round together with the failed cases.

## Execution log

Evidence: `scratchpad/qa034/tc-034-*.png` (session scratchpad, not committed). Script: Playwright Python, headless Chromium.

| Round | Result | What changed |
|---|---|---|
| 1 | 8 passed · 5 failed | Test-script defect: `inner_text()` returns the CSS-uppercased labels ("OCENA EKSPERTA…"), so the label checks never matched. Switched the oracle to `text_content()`. No app change. |
| 2 | 11 passed · 2 failed | TC-02/TC-08 counted request *initiations*: React `StrictMode` in Vite dev mounts twice, so `/v1/bike/popular` was started 2× and the reviews 6×. App fix: `usePopularBikes` now aborts the discarded first run's fetch with an `AbortController` (the review fan-out no longer runs twice); test now counts served responses. |
| 3 | 12 passed · 1 failed | TC-08 expected 3 review responses in the whole flow, but the details view opened in TC-07 sends its own `/v1/bike/review` for the search result (pre-existing behaviour). Expectation narrowed to the three popular bikes' reviews. |
| 4 | **13 passed · 0 failed** | — |

### Final results — round 4 (2026-09-28)

| Case | Result | Evidence / note |
|---|---|---|
| TC-034-01 | Pass | `tc-034-01.png` — 3 cards in seed order under the form, blurbs shown, no badge, no percentage |
| TC-034-02 | Pass | `tc-034-02.png` — 7.2 / 8.2 / 8.4 = API `rating`; served 1× popular + 3× review, all 200 |
| TC-034-03 | Pass | `tc-034-03-pending.png`, `tc-034-03-loaded.png` — "—" + "Ocena eksperta…" while held, ratings after release |
| TC-034-04 | Pass | `tc-034-04.png` — HTTP 500 and `rating: 0` → "—" + "Brak oceny", progressbar 0; third card 8.4 |
| TC-034-05a/b | Pass | `tc-034-05-empty.png`, `tc-034-05-500.png` — no section, hero + form usable, no page error |
| TC-034-06 | Pass | `tc-034-06.png` — section gone at loading and with results (DB-hit `Trek` / `Marlin 5`, 1 result); result card keeps `%` + match label |
| TC-034-07 | Pass | `tc-034-07-details.png` — search result's details header shows exactly one "Dopasowanie"; back → results, section hidden |
| TC-034-08 | Pass | `tc-034-08.png` — "Nowe wyszukiwanie" brings the section back with loaded ratings; popular served once, no review refetch |
| TC-034-09 | Pass | `tc-034-09-details.png` — Cannondale details without "Dopasowanie", cached details + review, back → section visible |
| TC-034-10 | Pass | no console errors, no page errors on the home page |
| TC-034-11 | Pass | `tc-034-11-mobile.png` — 375 px, no horizontal overflow |
| TC-034-12 | Pass | API: 3 bikes in seed order, blurbs ≤ 2 sentences, 51–84 ms, no generic-cache row |
| TC-034-13 | Pass | `case_popular` against `:8002` → PASS |
| TC-034-14 | Pass | seed `--dry-run` prints the same 3 picks, table unchanged |

**Needs a decision from the user:** X1 (details header hides "Dopasowanie" for a bike opened from the popular list) was not in the request; it prevents the expert rating being shown as a match score.
