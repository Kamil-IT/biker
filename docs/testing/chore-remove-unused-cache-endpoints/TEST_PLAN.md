# Test plan — remove unused cache endpoints

Branch `chore/remove-unused-cache-endpoints`. Request (user, 2026-10-01): remove `GET /v1/bike/search-cache`,
`GET /v1/bike/details-cache` and `POST /v1/bike/review/cached` completely; replace `review/cached` in the frontend
with one `POST /v1/bike/review` per bike, keeping the expert ratings on the search-result cards and the sort by rating.

## Traceability

| Requirement | Where implemented | Status |
|---|---|---|
| R1 `GET /v1/bike/search-cache` removed | `backend/app/main.py` (route gone), `store.py` readers `get_search_by_query` / `find_bikes_by_brand` removed, `CachedSearchResponse` removed | Implemented |
| R2 `GET /v1/bike/details-cache` removed | `backend/app/main.py` (route gone) | Implemented |
| R3 `POST /v1/bike/review/cached` removed | `backend/app/main.py`, `app/review_ratings.py` deleted, `CachedRating*` schemas removed | Implemented |
| R4 Result cards still show the expert rating | `frontend/src/hooks/useCachedRatings.ts` — one `POST /v1/bike/review` per bike, `Promise.all` | Implemented |
| R5 Sort by rating unchanged (backend order until settled, then rating desc, unrated last) | `App.tsx` `sortedBikes` unchanged; hook still returns `{ ratings, settled }` | Implemented |
| R6 Tests and frontend types follow | `test_search.py`, `test_details_repository.py`, `types.ts` | Implemented |
| Extra: `repository.search_fill_for` removed | used only by the removed readers | Extra (dead code) |

## Test cases

Techniques: equivalence partitions (rated / unrated / failing review call), state transitions (pending → settled,
list A → list B), regression of adjacent features.

| ID | Pri | Preconditions | Steps | Expected |
|---|---|---|---|---|
| TC-01 | High | backend up | `GET /v1/bike/search-cache?query=x` and `?brand=Trek` | 404 |
| TC-02 | High | backend up | `GET /v1/bike/details-cache?company=Trek&model=X` | 404 |
| TC-03 | High | backend up | `POST /v1/bike/review/cached` with a valid batch | 404 (405 acceptable only if another method exists — none does) |
| TC-04 | Med | backend up | read `/openapi.json` | none of the three paths listed |
| TC-05 | High | brand with ≥1 rated and ≥1 unrated bike | Filtry → Marka "Trek" → search | each result card shows a number (rated) or "?" (unrated); one `POST /v1/bike/review` per result bike; no request to `/review/cached`; no console errors |
| TC-06 | High | as TC-05 | read card order + ratings after settle | rated cards first in descending rating, unrated after them |
| TC-07 | Med | `/v1/bike/review` delayed 2 s (route) | search Trek | while pending every card shows "—" and backend order; after settle values appear and order is sorted |
| TC-08 | Med | `/v1/bike/review` answers 500 (route) | search Trek | list renders, every card "?" ("brak oceny"), no crash |
| TC-09 | Med | — | search Trek, then search Giant | second list gets its own review calls, cards show Giant ratings, no Trek rating leaks |
| TC-10 | Med | regression | open home page | "Najpopularniejsze rowery" cards show ratings |
| TC-11 | Med | regression | click a rated result card | details view opens, "Recenzja ekspertów" section shows the review |
| TC-12 | High | regression | `python scripts/test_search.py` against the branch backend (searcher off) + `pytest` | all selected cases pass |

## Results — round 1 (2026-10-01, backend :8003 on local `biker-pg`, Vite :5180)

| ID | Result | Evidence |
|---|---|---|
| TC-01 | Pass | `?query=x` → 404, `?brand=Trek` → 404 |
| TC-02 | Pass | 404 |
| TC-03 | Pass | 404 |
| TC-04 | Pass | `/openapi.json` lists 19 paths, none of the three |
| TC-05 | Pass | Trek: 34 cards = 34 bikes, 3 rated (values equal `/v1/bike/review`), 31 "?"; 34 distinct `POST /v1/bike/review` for the list (+1 from the home page popular list), 0 calls to `/review/cached`, no console errors |
| TC-06 | Pass | order 8.2, 8.0, 6.5, then 31 unrated |
| TC-07 | Pass | with a 2 s delay every card read "ocena eksperta w trakcie wczytywania" in backend order; afterwards sorted (Madone SL 6 8.2 first) |
| TC-08 | Pass | review 500 → 34 cards, all "brak oceny", no page error |
| TC-09 | Pass | Trek → Giant: 8 Giant cards, Revolt Advanced Pro 8.4, rest "?", no Trek leak |
| TC-10 | Pass | popular: Topstone Carbon 4 7.2, Madone SL 6 8.2, Revolt Advanced Pro 8.4 |
| TC-11 | Pass | Madone SL 6 card → details view, "Recenzja ekspertów" 8/10 with text (first run failed on a wrong test string "Recenzja eksperta" — the script was fixed, not the expectation) |
| TC-12 | Pass | `test_search.py` 14 passed, 0 failed, 4 skipped (3 `--ai`, live Decathlon with the searcher off); `pytest` 81 passed |

**12 passed · 0 failed · 0 blocked · round 1**
