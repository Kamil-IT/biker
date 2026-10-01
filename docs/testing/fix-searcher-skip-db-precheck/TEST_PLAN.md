# Test plan — searcher: no DB read before the photos / review / details search

Branch `fix/searcher-skip-db-precheck`. Request (user, 2026-10-01): *"Searcher POST /v1/search/details,
POST /v1/search/photos, POST /v1/search/review robią call do bazy przed searchem, niech przestaną tak samo jak nie
robią tego POST /v1/search/olx czy POST /v1/search/decathlon"*.

## Test basis and traceability

| ID | Requirement | Implemented in | Status |
|----|-------------|----------------|--------|
| R1 | photos / review / details issue no DB query before the finder runs | `searcher/app/main.py` `search_photos` / `_photo_search`, `search_review`, `search_details` (pre-reads and in-slot re-reads removed); `repository.get_stored_photos` / `get_stored_review` removed | Implemented |
| R2 | (decision) no stored-photo check moved to the backend: a photos search for a bike with photos runs, writes nothing, returns the stored photos with `saved: 0` | `main.py` `search_photos`; `repository.save_photos` unchanged | Implemented |
| R3 | (decision) details keeps the read-back **after** the save; response = stored state | `main.py` `search_details` | Implemented |
| X1 | (extra) TC-11 removed from `searcher/scripts/test_searcher.py` (it would now start a paid run) | test script | Extra — consequence of R1 |

## Approach

- Level: system test of the searcher (API) + integration through the backend + UI regression.
- **No paid runs**: the searcher runs under a QA wrapper that replaces `find_bike_photos` / `find_bike_review` /
  `find_bike_details` with stubs and records an ordered event log (`finder:<name>` and every SQL statement sent to the
  engine). Stub output is chosen by the model name: `Empty*` → empty / unusable result, `Slow*` → 6 s delay.
- Throwaway SQLite DB in the session scratchpad (never `biker-pg`); backend 8002, searcher 8102, frontend 5175.
- Oracle for R1: in the event log of one request, the first entry is `finder:*` — no SQL before it.

## Test data

| Bike | Seeded state |
|------|--------------|
| `QA / Bare` | bike row only |
| `QA / HasAll` | 2 photos, usable review (rating 7.0), complete details |
| `QA / Empty` | bike row only; stubs return nothing usable |
| `QA / Slow` | bike row only; stubs sleep 6 s |

## Test cases

| ID | Req | Pri | Preconditions / data | Steps | Expected |
|----|-----|-----|----------------------|-------|----------|
| TC-01 | R1 | High | `QA / Bare` | POST `/v1/search/photos` | 200, `saved: 2`, stub photos; log: `finder:photos` first, SQL only after |
| TC-02 | R1 R2 | High | `QA / HasAll` (2 photos) | POST `/v1/search/photos` | finder **called**; no SQL before it; 200 with the 2 **stored** photos, `saved: 0`; DB still 2 original rows |
| TC-03 | R1 | High | `QA / HasAll` (usable review) | POST `/v1/search/review` | finder called, no SQL before it; 200 `saved: 1`, stub review stored |
| TC-04 | R1 | Med | `QA / Empty` | POST `/v1/search/review` | finder called first; 200 `saved: 0`, empty review; no `bike_review` row |
| TC-05 | R1 R3 | High | `QA / HasAll` (complete details) | POST `/v1/search/details` | finder called, no SQL before it; SQL after it includes the save **and** a read-back SELECT; 200 `saved: 1`, body = stored state |
| TC-06 | R1 R3 | Med | `QA / Empty` | POST `/v1/search/details` | finder called first; 200 `saved: 0`, empty details; nothing written |
| TC-07 | R1 | High | `SEARCHER_MAX_CONCURRENT=1`, `QA / Slow` photos running | POST review + details + photos(`QA / Bare`) while the slot is taken | each 503 `searcher busy`; no SQL and no finder call for them |
| TC-08 | regr | Med | `QA / Slow` | 2 concurrent POST `/v1/search/photos` | one `finder:photos`, both 200 with the same body |
| TC-09 | regr | Med | — | `searcher/scripts/test_searcher.py` against 8102 | ALL OK (health, 401, 422 on six routes) |
| TC-10 | regr | Med | — | `pytest searcher/scripts` | all pass (400 limit / 502 on six routes, aggregation, details finder) |
| TC-11 | regr | High | `QA / HasAll` via backend 8002 | POST `/v1/bike/review/search`, `/v1/bike/details/search` | 200 from the DB, searcher **not** called (no new searcher events) |
| TC-12 | R2 | Med | `QA / HasAll` via backend | POST `/v1/bike/photos/search` | searcher called (R2), 200 with the 2 stored photos |
| TC-13 | regr | Med | unknown bike via backend | POST `/v1/bike/{photos,review,details}/search` | 404, no searcher call |
| TC-14 | regr | High | UI 5175, `QA / Bare` details view | click **Poproś o dane** in gallery, Opis, Recenzja | sections fill with the stub data, no console errors |

Regression set = TC-08 … TC-14. Exit: every case Pass.

## Results — round 1 (2026-10-01)

**14 passed · 0 failed · 0 blocked.** Environment as planned. The frontend ran on 5190, not 5175, because another
session held the 517x ports.

| ID | Result | Evidence |
|----|--------|----------|
| TC-01 | Pass | `finder:photos` first event, `saved: 2`, 2 rows |
| TC-02 | Pass | finder called, `saved: 0`, the 2 original photos returned, rows unchanged (id/url/order) |
| TC-03 | Pass | finder first, `saved: 1`, DB rating 7.0 → 9.1 |
| TC-04 | Pass | finder first, `saved: 0`, no `bike_review` row |
| TC-05 | Pass | finder at index 0; 2 writes, then 4 SELECTs (read-back); response = stub component |
| TC-06 | Pass | finder first, `saved: 0`, no INSERT/UPDATE/DELETE |
| TC-07 | Pass | review/details/photos → 503 `searcher busy`, zero events while the slot was held |
| TC-08 | Pass | 1 finder call for 2 concurrent requests, identical bodies |
| TC-09 | Pass | `test_searcher.py` ALL OK against 8102 |
| TC-10 | Pass | 73 passed (`pytest scripts --ignore=scripts/test_searcher.py`) |
| TC-11 | Pass | backend answered review/details from the DB, no searcher event |
| TC-12 | Pass | searcher called (R2), the 2 stored photos returned |
| TC-13 | Pass | 404 ×3, no searcher event |
| TC-14 | Pass | photos, description, components and review filled from the stubs, 0 console errors |

**Negative control:** the same harness against the `main` searcher logs a `SELECT … FROM bike` as the first event and
never calls the finder (`… already stored — no search`), so the TC-01–06 oracle tells the old code from the new one.

**Notes:**
- `pytest searcher/scripts` without `--ignore` fails to collect `test_searcher.py` because it is a live-server script.
  The same happens on `main`, so this change did not cause it.
- In the first TC-14 attempt the script clicked every **Poproś o dane** button. The offer finders were not stubbed
  yet, so one real OLX `claude -p` run started. It was killed after about 1 minute and wrote only to the throwaway
  SQLite DB. After that, every CLI finder was stubbed and `CLAUDE_BIN` pointed at a missing file.
