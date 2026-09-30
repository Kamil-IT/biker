# TODO-037 — Test plan: bike expert review through the searcher

Test basis: `backlog/done/DONE_037_REVIEW_SEARCHER.md` (decisions 1–11, contract, acceptance criteria AC1–AC10).
Branch `feature/036-review-searcher` (uncommitted diff vs `origin/main`, based on TODO-035).
Two executors: **qa-fake** (this plan's default — isolated stack with a fake searcher) and **qa-real**
(real searcher, one paid `claude -p` run, migration script on Postgres). Cases marked `qa-real` are executed by that agent.

## 1. Scope

In scope: `POST /v1/bike/review` (DB read), `POST /v1/bike/review/search` (proxy), backend searcher client for the
review route, `copy_review_cache_to_table.py`, `seed_popular_bikes.py`, details-view Review section
(`RequestDataButton` with `onRequested`), home-page popular cards (regression), equipment review (regression).
Out of scope: deploy, Cloud SQL run, `/v1/equipment/review` internals, search-result ratings.

## 2. Environment (qa-fake)

| Component | Where |
|---|---|
| DB | SQLite copy of `biker/backend/cache.db` (scratchpad `qa-fake/qa.db`), `migrate_photos_bike_id.py` + `copy_review_cache_to_table.py` run on it, `seed_popular_bikes.py` run on it |
| Fixture bikes | brand `QAFake`, models `Review OK` / `Review OK2` (no photos) / `Review Empty` / `Review Fail` / `Review Busy` / `Review Slow` / `Review Slow2` / `Review NoRating` (also `bike_popular` position 4) — details, components and photos cloned from Trek Madone SL 6 |
| Fake searcher | FastAPI on `127.0.0.1:8112`, `POST /v1/search/review` checks `X-Searcher-Key`; model name picks Empty (200 empty review, saved 0) / Fail (502 `claude CLI failed: fake`) / Busy (503) / Slow (8 s, then success) / else success (Polish review, 3 http refs + `javascript:` + `escapecollective.com`). Does **not** write the DB. Every call logged to `fake_calls.log` |
| Backend | worktree `backend/`, port 8012, `DATABASE_URL=sqlite:///…qa.db`, `SEARCHER_URL=http://127.0.0.1:8112`, invalid `ANTHROPIC_API_KEY` (any SDK call would fail loudly) |
| Frontend | worktree `frontend/`, Vite on `localhost:5178`, `BIKER_API_URL=http://localhost:8012` |
| Browser | Python Playwright (global python), Chromium headless, screenshots in `qa-fake/shots/` |

## 3. Traceability (requirement → implementation)

| Req | Requirement | Where implemented | Static status |
|---|---|---|---|
| D2/AC1 | `/v1/bike/review` = pure DB read, empty review on unknown / none / DB error | `backend/app/main.py` `bike_review`; `backend/app/reviews_repository.py` `get_review` | Implemented |
| D3/AC2 | `/v1/bike/review/search`: 404 before searcher, 503 ×3 fixed strings, 502 detail, single-flight, never cached | `backend/app/main.py` `bike_review_search`; `backend/app/searcher_client.py` `search_review` | Implemented + **Extra**: stored review with sources is returned without a searcher call (not in the task) |
| D6 | `bike_review` / `bike_review_source` tables via `init_db()` | `backend/app/models.py` `BikeReview`, `BikeReviewSource` | Implemented |
| D7/AC6 | Review section button: `onRequested`, "Szukam recenzji…", "Nie znaleziono recenzji", failure → clickable, late result dropped | `frontend/src/App.tsx` `searchReview`; `BikeDetailsView.tsx` Review branch; `RequestDataButton.tsx` `emptyLabel` | Implemented |
| D7/AC7 | Home page ratings from DB, rating 0 → "Brak oceny" | `usePopularBikes.ts` (unchanged) | Implemented (no change) |
| D8/AC5 | copy script SQLite + PG, dry-run, idempotent, eligibility, unknown bikes listed | `backend/scripts/copy_review_cache_to_table.py` | Implemented (SQLite here; PG = qa-real) |
| D9 | seed script reads `bike_review` | `backend/scripts/seed_popular_bikes.py` | Implemented |
| D10/AC8 | finder + prompt gone from backend; equipment review unchanged | deleted files; `main.py` import removed | Implemented |
| — | ReviewSection renders only http(s) refs | `frontend/src/components/BikeDetailsShared.tsx` `isWebUrl` | Extra (security hardening) |
| D4/D5/AC3/AC4 | searcher route, aggregation, persistence rules, DDL copy, REQUIRED_TABLES | `searcher/app/*` | qa-real |

## 4. Test conditions and cases

Priority: P1 = acceptance criterion / money or data risk, P2 = error path, P3 = cosmetic/regression.
Technique: EP = equivalence partitioning, BVA = boundary value, ST = state transition, UC = use case.

### 4.1 API — `POST /v1/bike/review` (AC1)

| ID | Pri | Tech | Precondition / data | Steps | Expected |
|---|---|---|---|---|---|
| API-R01 | P1 | EP | Trek / Madone SL 6 (migrated review) | POST | 200, values equal the `bike_review` row, `ref` in `display_order`, < 5 s, no fake call, no new generic-cache row |
| API-R02 | P1 | EP | `trek` / `  madone sl 6 ` | POST | 200, same review (Python normalisation) |
| API-R03 | P1 | EP | unknown bike | POST | 200 empty review `{0,"",[],0.0,0}` |
| API-R04 | P1 | EP | QAFake / Review OK (bike without review) | POST | 200 empty review |
| API-R05 | P2 | EP/BVA | blank model, missing field, 256-char model; 255-char model | POST | 422 ×3; 255 chars → 200 empty |
| API-R06 | P2 | EP | DB error (not forced here) | — | covered by code review / qa-real |

### 4.2 API — `POST /v1/bike/review/search` (AC2)

| ID | Pri | Tech | Data | Expected |
|---|---|---|---|---|
| API-S01 | P1 | EP | unknown bike | 404 `Bike not found`, fake log has no call |
| API-S02 | P1 | EP | Review OK | 200 with the fake's review (bike_id/saved dropped), fake called once with key |
| API-S03 | P1 | EP | Review Empty | 200 empty review |
| API-S04 | P2 | EP | Review Fail | 502 `claude CLI failed: fake` |
| API-S05 | P2 | EP | Review Busy | 503 `Review searcher is busy — try again in a moment` |
| API-S06 | P2 | EP | backend restarted with searcher down / URL unset | 503 `Review searcher unavailable` / `…is not configured` |
| API-S07 | P1 | ST | two concurrent POSTs for Review Slow | both 200, identical; fake called **once** |
| API-S08 | P1 | EP | Madone SL 6 (stored review) — Extra behaviour | 200 stored review, fake **not** called |
| API-S09 | P2 | EP | 422 validation as API-R05 | 422, no fake call |
| API-S10 | P2 | EP | wrong key | fake 401 → backend 502 (`SearcherFailed`) — observe |
| API-S11 | P1 | — | real searcher run + DB write | **qa-real** |

### 4.3 UI — details view Review section (AC6)

| ID | Pri | Tech | Data | Steps | Expected |
|---|---|---|---|---|---|
| UI-01 | P1 | UC | Madone SL 6 via home card | open details | review + Sources table renders, no button, no `/v1/bike/review/search` request |
| UI-02 | P1 | ST | Review OK | open details (URL/app flow), wait 5 s | skeleton, then `RequestDataButton` "Poproś o dane" in "Recenzja ekspertów" |
| UI-03 | P1 | ST | Review OK | click | `/v1/bike/missing` `review` + `/v1/bike/review/search`; label "Szukam recenzji…"; review replaces the button; `javascript:` ref not rendered as link; `<cite>` stripped |
| UI-04 | P1 | ST | Review Empty | click | button ends disabled "Nie znaleziono recenzji" |
| UI-05 | P2 | ST | Review Fail | click | button clickable again "Poproś o dane" |
| UI-06 | P2 | ST | Review Busy | click | button clickable again |
| UI-07 | P1 | ST | Review Slow → back → Review OK2 | click on Slow, go back, open OK2 before 8 s | OK2 section keeps its own state (button), Slow's review never appears on OK2 |
| UI-08 | P1 | — | home page load | load `/` | no `/v1/bike/review/search` requests in network log |

### 4.4 Regression

| ID | Pri | Area | Expected |
|---|---|---|---|
| REG-01 | P1 | home popular cards | 3 seeded cards show ratings 8.2 / 7.2 / 8.4, QAFake Review NoRating shows "Brak oceny" |
| REG-02 | P2 | offers cards | "Poproś o dane" still present in Używane / Nowe for a bike without offers (not clicked — fake returns 502 for offers) |
| REG-03 | P2 | photos | QAFake Review OK2 (no photos) shows the gallery Request button after grace |
| REG-04 | P2 | equipment review | `POST /v1/equipment/review` still wired to the SDK finder (cached item → 200; uncached → SDK error, unchanged behaviour) |
| REG-05 | P1 | scripts | copy script re-run = 0 copied (idempotent); `--dry-run` writes nothing; seed script picks by stored review |

### 4.5 qa-real (executed by the `qa-real` agent)

Real `POST /v1/search/review` run (one paid run), persistence rules (save only with sources, upsert, nothing deleted on
empty), aggregation parity, searcher REQUIRED_TABLES refusal, copy script on PostgreSQL, real-stack UI flow.

## 5. Entry / exit criteria

Entry: stack up on 8012/8112/5178, DB copy migrated. Exit: all P1 cases pass, no open P1/P2 defect, max 5 rounds.

## 6. Results — qa-fake, round 1 (2026-09-29)

**28 passed · 0 failed · 0 blocked** (qa-real cases reported separately). Evidence: scratchpad `qa-fake/` —
`api_results.json`, `ui_results.json`, `shots/*.png`, `fake_calls.log`, `backend.out`.

| ID | Result | Evidence / note |
|---|---|---|
| API-R01 | Pass | 200 = `bike_review` row, `ref` in display_order, 0.98 s (first request), no fake call |
| API-R01b | Pass | generic-cache row count unchanged (190 → 190) |
| API-R02 | Pass | `trek` / `  madone sl 6 ` → same review |
| API-R03 | Pass | unknown bike → empty review |
| API-R04 | Pass | bike without review → empty review |
| API-R05 | Pass | blank / missing / 256 chars → 422; 255 chars → 200 |
| API-S01 | Pass | 404 `Bike not found`, no fake call |
| API-S02 | Pass | 200, `bike_id`/`saved` dropped, one fake call with the right key |
| API-S03 | Pass | Empty → 200 empty review |
| API-S04 | Pass | 502 `claude CLI failed: fake` |
| API-S05 | Pass | 503 `Review searcher is busy — try again in a moment` |
| API-S06 | Pass | URL/key empty → 503 `Review searcher is not configured`; fake stopped → 503 `Review searcher unavailable` |
| API-S07 | Pass | two concurrent Slow requests → both 200, identical, fake called once |
| API-S08 | Pass | stored review → returned, fake not called (Extra behaviour) |
| API-S09 | Pass | 422, no fake call |
| API-S10 | Pass (observe) | wrong key → fake 401 → backend 502 with the searcher's detail `bad key` — same mapping as the other searcher routes |
| UI-01 | Pass | Madone from home card: review + Sources table, no button, no `/review/search` request |
| UI-02 | Pass (oracle corrected) | button shows immediately, not after 5 s: the DB read answers empty at once and the grace applies only while loading (CLAUDE.md: "after that — or on an empty/failed response"). Plan's "after 5 s" oracle was wrong |
| UI-03 | Pass | `/v1/bike/missing` + `/v1/bike/review/search`, "Szukam recenzji…" seen, review replaced button, `<cite>` stripped, `javascript:` ref not rendered |
| UI-04 | Pass | "Nie znaleziono recenzji", disabled |
| UI-05 | Pass | Fail → "Poproś o dane", enabled |
| UI-06 | Pass | Busy → "Poproś o dane", enabled |
| UI-07 | Pass | Slow2 search in flight → opened OK2 → no leaked review after 12 s, button intact |
| UI-08 | Pass | home page: no `/v1/bike/review/search` requests |
| REG-01 | Pass | cards 8.2 / 7.2 / 8.4, NoRating card "Brak oceny" |
| REG-02 | Pass | Używane / Nowe request buttons present |
| REG-03 | Pass | gallery request button for a bike without photos |
| REG-04 | Pass | `/v1/equipment/review` cached item → 200 from generic cache; uncached → 500 on the invalid SDK key (unchanged pre-existing behaviour) |
| REG-05 | Pass | copy script: dry-run creates/writes nothing; run copies 17 (9 degenerate skipped); re-run 17/57 rows unchanged; seed script picks 3 bikes by stored review |

Observations (not defects):
- O1 — the frontend renders an `escapecollective.com` ref if the backend receives one; the backend passes refs through, so
  the banned-domain guard lives only in the searcher (`BANNED_REVIEW_DOMAINS`) and the copy script. Verify on qa-real.
- O2 — `/v1/bike/review/search` short-circuits on a stored review (not in the task; saves a paid run). Flag for the user.
- O3 — `hasReview` (`BikeDetailsView.tsx:103`) counts any truthy ref, so a review whose only refs are non-http would show an
  empty Sources table; unreachable with the real searcher (it stores only safe URLs).
- O4 — pre-existing: `/v1/bike/details` reads only the generic cache, not the ORM details tables; fixtures needed a cache row.
