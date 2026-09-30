# TODO-041 — Test plan (manual QA, ISTQB-style, risk based)

Stack: local PostgreSQL `biker-pg`; branch backend :8011 (SEARCHER_URL -> real searcher :8111), real searcher :8111,
frontend :5190; second backend :8012 -> fake searcher :8112 (models: Empty / Fail / Busy / Limit).
Techniques: equivalence partitions (details state: complete / none / partial / unknown bike), state transition
(button: idle -> pending -> filled | empty | error), error guessing (late result, double click).

| ID | Area | Precondition | Steps | Expected | Prio |
|----|------|--------------|-------|----------|------|
| TC-01 | DB migration/purge | local DB | migrate --dry-run, real, again; purge --dry-run, real, again | dry-run writes nothing; 2nd run "already migrated"/0 rows; cache rows for /v1/bike/details = 0 | H |
| TC-02 | /v1/bike/details complete | Pedego Boomerang | POST | 200 <1s, description+components, short_description key present, no AI | H |
| TC-03 | /details no data / unknown | Trek Marlin 4; unknown | POST | 200 empty response | H |
| TC-04 | /details/search unknown | unknown bike | POST | 404 "Bike not found" | H |
| TC-05 | /details/search complete | Pedego | POST | 200 stored, searcher log has no new request | H |
| TC-06 | UI complete details | Pedego | open details | Opis + Komponenty shown, no buttons, no short description text, no /details/search call | H |
| TC-07 | UI no details search (real, paid) | bike without details | open, click Opis button | spinner "Szukam danych roweru…", both sections filled, exactly 1 POST /details/search, stored in DB | H |
| TC-08 | UI partial details | seeded description-only bike (real, paid) | click | button present; search runs; existing half not lost | H |
| TC-09 | empty result (fake) | model Empty | click | "Nie znaleziono danych" disabled | H |
| TC-10 | failure / busy / limit (fake) | model Fail / Busy / Limit | click | backend 502 / 503 fixed text / 400 detail; button clickable again | H |
| TC-11 | search card | Pedego; bike with short_description; bike w/o details | search via filters | chips from DB; explanation when present; hidden when empty; TODO-040 rating unaffected | H |
| TC-12 | search-cache follow-up | after search | GET /search-cache?query= | same explanation/accessories rule | M |
| TC-13 | generic cache | after all | count rows '/v1/bike/details' | 0 | M |
| TC-14 | webscraper | - | process_queue.py --help | no --sync-cache | M |
| TC-15 | smoke suites | - | test_search.py (no --ai), test_searcher.py | all pass | H |

## Results (round 1, 2026-09-30)
TC-01 PASS (migrated 617 rows; 2nd run already-migrated; purge 86 rows, 2nd run 0) · TC-02 PASS · TC-03 PASS · TC-04 PASS ·
TC-05 PASS (no new searcher request) · TC-06 PASS (Trek FX 3; see F2 for Pedego) · TC-07 PASS (Trek Marlin 4, 144 s, 33 rows, 7 categories;
Turbo Tero 2.0, 35 s, description only, see F1) · TC-08 PASS (partial bike: button searches, detail id stable, result without components ->
"Nie znaleziono danych") · TC-09 PASS · TC-10 PASS (502 / 503 fixed text / 400 detail / 503 unavailable; button clickable again) ·
TC-11 PASS · TC-12 PARTIAL (only via smoke suite; local search_cache rows older than 24 h) · TC-13 PASS (0 rows) · TC-14 PASS · TC-15 PASS (16 passed, 4 skipped).
Findings: F1 model "not found" apology stored as description; F2 pipeline descriptions with segments [] render an empty Opis card (pre-existing);
F3 Specyfikacja button shows no spinner while the shared search runs from Opis (and vice versa).
Screenshots: tc*_*.png in this folder.

## Round 2 (2026-09-30) — re-test of F1, F2, F3 + regression
Stack: branch backend :8011 -> real searcher :8111; backend :8012 -> fake searcher :8112 (6 s delay; models QaEmpty / QaFail / QaBusy);
frontends :5190 / :5191; local `biker-pg`. Fixtures `QaBrand/*` inserted and deleted afterwards. Screenshots: `f3_*.png`, `f2_pedego.png`, `tc11_r2*.png` (scratchpad).

| ID | Check | Result |
|----|-------|--------|
| R2-F1 | ONE real paid `/v1/bike/details/search`, Specialized Turbo Tero 2.0 (bike 56, no details) | PASS — HTTP 200 in 26.4 s (searcher 24.7 s), model answered found=false: searcher log "no usable details found ... nothing written", response = empty description/components; DB after: 0 `bike_detail` rows for bike 56, bike row kept, no apology text stored |
| R2-F2 | Pedego Boomerang (legacy, segments []) | PASS — Opis card shows the `description.text`, no Opis button, no `/details/search` call. Source chips: not verifiable on data — no local legacy row has segments [] AND citations (Pedego has citations []); code path reviewed (BikeDetailsShared.tsx aggregates `description.citations`) |
| R2-F2b | Equipment details view from cache | SKIPPED — would need the Anthropic API on a miss (no credits) |
| R2-F3a | QaEmpty: click Opis (and, second run, Specyfikacja first) | PASS — both buttons "Szukam danych roweru…" during the run; the other click sent no request (1 `/details/search`, 1 `/missing`); after: both "Nie znaleziono danych", disabled |
| R2-F3b | QaFail (click Specyfikacja, try Opis) | PASS — both pending, 1 search request, after 502 both "Poproś o dane" and enabled |
| R2-F3c | QaBusy (click Opis, try Specyfikacja) | PASS — same as QaFail after 503 |
| R2-TC02 | `/v1/bike/details` Pedego Boomerang | PASS — 200, 0.23 s |
| R2-TC06 | Complete details view | PASS — Opis + Komponenty rendered, no details buttons, no details/search call |
| R2-TC11 | Search cards | PASS — Pedego: chips present, no expert rating ("BRAK OCENY"); Trek: chips + TODO-040 rating (8.2 / 8.0 / 6.5 "OCENA EKSPERTA") intact |
| R2-TC13 | generic cache rows for `/v1/bike/details` | PASS — 0 |
| R2-TC15 | `backend/scripts/test_search.py` (SEARCHER_URL blank) | PASS — 16 passed, 0 failed, 4 skipped (decathlon_search paid case + 3 [API]) |
| R2-TC15b | `searcher/scripts/test_searcher.py` vs :8111 | PASS — ALL OK (incl. details 401 / 422) |

New findings: none. Round 2: 11 passed, 0 failed, 1 skipped, 1 partial (chips on legacy data unverifiable).
