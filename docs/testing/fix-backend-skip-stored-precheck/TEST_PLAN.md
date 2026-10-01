# Test plan — backend review/details search without the stored-data pre-check

Branch `fix/backend-skip-stored-precheck` (base `origin/main` 9a5a3b7). Request (user, 2026-10-01):
1. `POST /v1/bike/review/search` must not read the stored review before calling the searcher.
2. `POST /v1/bike/details/search` must not read the stored details before calling the searcher.
   Decision: the `bike_exists` 404 guard stays in both.
3. Delete the generic-cache rows of `'/v1/bike/ceneo'` (Ceneo code untouched) in local `biker-pg`,
   `backend/cache.db` and Cloud SQL (Cloud SQL run by the user, not tested here).

## Traceability

| Requirement | Where implemented | Status |
|---|---|---|
| R1 review/search: no stored-review read | `backend/app/main.py` `bike_review_search` — `get_review` short-circuit removed | Implemented |
| R2 details/search: no stored-details read | `backend/app/main.py` `bike_details_search` — `get_bike_details` + `has_complete_details` removed | Implemented |
| R1/R2 `bike_exists` 404 kept | `backend/app/main.py` both routes | Implemented |
| R3 Ceneo rows deleted locally | data only: `biker-pg` (12 rows), `backend/cache.db` (13 rows) | Implemented (Cloud SQL pending, user) |
| R3 Ceneo code untouched | no diff in `main.py` `bike_ceneo` / `bike_offer_ceneo_finder.py` | Implemented |
| Extra: `repository.has_complete_details` + its unit test removed | dead after R2 | Extra (dead code) |
| Extra: smoke `case_review_search` reduced to the 404 check | its stored-review check would now start a run | Extra (follows R1) |

## Test cases

Setup: backend from the worktree on :8004 against local `biker-pg`, `SEARCHER_URL` = a fake searcher on :8105
(logs every call, answers canned `{review|details, bike_id, saved}`; no paid run). Fixtures: `Specialized Allez Sprint`
(stored review + complete details), `Canyon Grizl CF 7` (nothing stored).

| ID | Pri | Steps | Expected |
|---|---|---|---|
| TC-01 | High | review/search unknown bike | 404 "Bike not found", fake searcher gets 0 calls |
| TC-02 | High | review/search Allez Sprint (stored usable review) | fake searcher called once (`/v1/search/review`, `X-Searcher-Key`), body = the fake review, not the stored one |
| TC-03 | High | review/search Grizl CF 7 (no review) | searcher called once, fake review returned |
| TC-04 | High | details/search unknown bike | 404, 0 calls |
| TC-05 | High | details/search Allez Sprint (complete details) | searcher called once (`/v1/search/details`), body = fake details |
| TC-06 | High | details/search Grizl CF 7 (no details) | searcher called once, fake details returned |
| TC-07 | Med | fake searcher answers 503 | review/search and details/search → 503 "… busy" |
| TC-08 | High | count `/v1/bike/ceneo` rows in `biker-pg` and `cache.db` | 0 in both; other endpoints' rows still present |
| TC-09 | Med | `git diff` Ceneo code | no change to `bike_ceneo` / `bike_offer_ceneo_finder.py` / its prompt |
| TC-10 | Med | UI: details view of Allez Sprint | no "Poproś o dane" in Opis / Komponenty / Recenzja (data stored) |
| TC-11 | Med | UI: details view of Grizl CF 7, click review "Poproś o dane" | button shown; click → one review/search → fake review rendered |
| TC-12 | High | regression: `pytest`, `test_search.py` against :8004 (fake searcher's `/health` off → live Decathlon skipped) | all selected pass |

## Results — round 1 (2026-10-01, backend :8004 on local `biker-pg`, fake searcher :8105, Vite :5182)

| ID | Result | Evidence |
|---|---|---|
| TC-01 | Pass | 404 "Bike not found", 0 searcher calls |
| TC-02 | Pass | Allez Sprint has a stored review (sources ≥ 1) → 1 call `/v1/search/review` with `X-Searcher-Key`, body = the fake review |
| TC-03 | Pass | Grizl CF 7 → 1 call, fake review (rating 9.1) |
| TC-04 | Pass | 404, 0 calls |
| TC-05 | Pass | Allez Sprint has complete details → 1 call `/v1/search/details`, body = fake details |
| TC-06 | Pass | Grizl CF 7 → 1 call, fake details |
| TC-07 | Pass | fake 503 → "Review searcher is busy …" / "Details searcher is busy …" (503) |
| TC-08 | Pass | `/v1/bike/ceneo` rows: biker-pg 0 (other 133), cache.db 0 (other 142) |
| TC-09 | Pass | no diff in `bike_offer_ceneo_finder.py`, its prompt or the `bike_ceneo` route |
| TC-10 | Pass | Allez Sprint details view: "Poproś o dane" only in Zdjęcia / Używane / Nowe (no data there); none in Opis / Specyfikacja / Recenzja; 0 searcher calls on open |
| TC-11 | Pass | Grizl CF 7: buttons in Opis, Specyfikacja, Recenzja (+ Zdjęcia, offers); review click → 1 `/v1/bike/review/search` → 1 searcher call → fake review rendered, no page error |
| TC-12 | Pass | `pytest` 80 passed; `test_search.py` 14 passed, 0 failed, 4 skipped (3 `--ai`, live Decathlon with no real searcher); `cache.db` unchanged by the run |

**12 passed · 0 failed · 0 blocked · round 1**
