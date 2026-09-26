# Test plan — TODO-032 On-demand Decathlon search in the searcher

Branch `feature/032-searcher-decathlon` · task `backlog/TODO_032_SEARCHER_DECATHLON_ON_DEMAND.md` · executed 2026-09-26.

## Scope

In scope: the on-demand Decathlon search path end to end — the searcher's new `POST /v1/search/decathlon`, the
backend's DB-only `POST /v1/bike/decathlon`, the proxy `POST /v1/bike/decathlon/search` with the Decathlon house-brand
allowlist (closes `TODO_ISSUE_010`), and the frontend's **Poproś o dane** button in the **"Nowe"** offer card.
Regression: the OLX path shipped in TODO-031 (same searcher, same button component, shared busy slot) and the other
Request-data buttons.

Out of scope (per task): Allegro / Ceneo, Decathlon photos, TTL / refresh, listing liveness, rate limiting, GCP deploy
(only after the user's go-ahead).

## Environment and constraints

- Local stack from this checkout: searcher `127.0.0.1:8100`, backend `127.0.0.1:8001`, frontend `localhost:5174`
  (ports 8000/8080 are held by another worktree's docker-compose stack connected to Cloud SQL — not touched).
- Database: local PostgreSQL 17 (`biker-pg`, `DATABASE_URL` in `backend/.env` and `searcher/.env`).
- Error/empty paths run on a second stack wired to a **fake searcher** (`127.0.0.1:8199` → backend `8002` → frontend
  `5175`), because the real CLI cannot be made to return "no offers" or fail on demand.
- **The Anthropic API key has no credits**, so every uncached AI endpoint answers 500. Test bikes are therefore rows
  that already exist in `bike` and are reachable through the DB-first search (brand + model filters): the Decathlon
  house-brand bikes `Decathlon / Rockrider ST 100` (id 28), `Riverside / Riverside 500` (34), `Decathlon / Triban RC 520`
  (33), `Triban / Van Rysel EDR Easy` (633) — none of them has cached Allegro/Ceneo offers, so their "Nowe" card is
  empty until the Decathlon search runs — and the foreign-brand bike `Trek / Marlin 5` (1), whose cached Allegro offer
  is `is_new=false` and whose stored OLX rows exercise the Used-card regression.
- Expected behaviour change surfaced by the tests: Decathlon responses that the *old* endpoint left in the generic cache
  (e.g. Romet Wagant 3, Cannondale Topstone Carbon 4) are no longer served — the endpoint reads `bike_offer` only.

## Requirement traceability

| # | Requirement (task file) | Implemented in | Status |
|---|---|---|---|
| R1 | `POST /v1/bike/decathlon` is a pure DB read (zero AI/CLI calls, no generic cache), `{offers, info}` unchanged, unknown bike → 200 empty | `backend/app/main.py:310` `bike_decathlon`, `backend/app/offers_repository.py:105` `get_decathlon_offers` (over `_get_stored_offers`, `is_new` from the row) | Implemented |
| R2 | New `POST /v1/bike/decathlon/search`: 404 unknown bike → 200 empty + `info` for a foreign brand (no searcher call) → proxy to the searcher; 503 not configured / unreachable / busy, 502 on failure; never cached | `backend/app/main.py:326` `bike_decathlon_search`, `backend/app/searcher_client.py:212` `search_decathlon` (single-flight key `(path, company, model)`, one semaphore for both sources) | Implemented |
| R3 | Searcher `POST /v1/search/decathlon`: same prompt through `claude -p --json-schema`, ≤ 3 offers, `photos: []`, `source='decathlon.pl'`, replace semantics scoped to `(bike, source)`, no re-parenting, empty result keeps rows, shared busy slot with OLX | `searcher/app/main.py:145` `search_decathlon` → `_run_search` (`:95`, one `_semaphore`), `searcher/app/decathlon_finder.py:70` `find_decathlon_offers` / `:30` `_to_offers`, `searcher/app/repository.py:73` `save_offers` (`:115` upsert scoped to bike + source, `:132` empty result keeps rows) | Implemented |
| R4 | Searcher auth unchanged: `X-Searcher-Key`, 401 otherwise, fail closed | `searcher/app/main.py:66` `require_api_key` (dependency of both routes) | Implemented |
| R5 | Frontend: the "Nowe" card's Poproś o dane records the click **and** runs the Decathlon search; "Szukam na Decathlon…" while running; rows replace the button; "Nie znaleziono ofert" on empty; clickable again on failure; `/v1/bike/decathlon` still called automatically | `frontend/src/App.tsx:280` `searchDecathlon` (via `postOnDemandSearch`, `:258`, `selectedBikeRef` guard), `BikeDetailsView.tsx:341` New card `onRequested={… onSearchNew}` + `pendingLabel`, `RequestDataButton.tsx` unchanged | Implemented (+ X1) |
| R6 | Foreign brands skipped: allowlist Rockrider, Btwin/B'Twin, Triban, Van Rysel, Elops, Riverside, Stilus, Tilt, Decathlon | `backend/app/decathlon_brands.py:19` `DECATHLON_BRANDS`, `:44` `is_decathlon_brand` (lower-case, apostrophes/hyphens/dots/spaces stripped), `:49` `not_sold_info` (Polish `info`) | Implemented — closes `TODO_ISSUE_010` |
| R7 | `bike_offer_decathlon_finder.py` and the prompt moved out of the backend | deleted from `backend/app`, prompt byte-identical under `searcher/app/prompts` (`git mv`) | Implemented |
| R8 | Smoke tests: `backend/scripts/test_search.py` TC-33..35, `searcher/scripts/test_searcher.py` TC-7..9 | `test_search.py:1096/1128/1141`, `test_searcher.py:128/138/159`; `BikeOfferRequest` bounded to 255 chars (`schemas.py:252`) | Implemented — results below |
| R9 | Docs: CLAUDE.md, README.md, backend/README.md, frontend/README.md, searcher/README.md (+ `backend/app/DB_MIGRATION.md`, compose / deploy comments) | updated | Implemented |
| X1 | (not requested) The New card offers the Decathlon search only while **no** decathlon.pl row is stored for the bike; with a stored outlet row (`is_new: false`, shown in the Used card) the button is the plain counter click | `BikeDetailsView.tsx` `hasDecathlonRows` | Extra — review finding: each click would otherwise be a paid run that can never fill the card |
| X2 | (not requested) Backend 502 for a malformed searcher body now relays a fixed sentence, not the pydantic error text | `backend/app/searcher_client.py` `_post_search` | Extra — review finding (pre-existing since TODO-031) |
| K1 | Known limitation (kept by decision 6, "same as OLX"): a decathlon.pl product URL is **globally unique** in `bike_offer`, and the `bike` table holds duplicate identities for the same product (`Decathlon / Rockrider ST 100` vs a would-be `Rockrider / ST 100`, three `Van Rysel … GRVL GRX AF` rows). The first identity to search stores the URL; a sibling identity's search runs the CLI, saves nothing and ends in "Nie znaleziono ofert". The fix is TODO-021 item 2 (drop the global `unique=True` on `url`, keep `(bike_id, url)`) | `searcher/app/repository.py:115` | Documented; smoke tests use the identity the app already has |

## Test cases

### TC-032-01 — Stored Decathlon offer is served from the DB
- **Requirement:** R1, R5 · **Priority:** High
- **Preconditions:** Riverside / Riverside 500 has ≥ 1 `decathlon.pl` row in `bike_offer` (written by TC-032-03). (Rockrider ST 100 is left to the smoke suites, which run first and store its row — the browser cases need a bike whose card is still empty.)
- **Steps:** open `/`, Filtry → Marka `Riverside`, Model `Riverside 500` → Znajdź → click the result card → wait for the "Nowe" card
- **Expected:** within ~2 s the New card lists the decathlon.pl row (price, link to `https://www.decathlon.pl/…`); no Poproś o dane in it; exactly one `POST /v1/bike/decathlon` → 200 and no `/v1/bike/decathlon/search`

### TC-032-02 — Empty New card shows the button only after the 5 s grace
- **Requirement:** R5 · **Priority:** Medium
- **Preconditions:** Riverside / Riverside 500 has no `decathlon.pl` rows and no cached Allegro/Ceneo offers
- **Steps:** open its details as above; sample the New card immediately, then wait
- **Expected:** no rows and no button right after render (skeleton); "Poproś o dane" appears within 15 s; `/v1/bike/decathlon` → 200 (empty)

### TC-032-03 — Click runs the Decathlon search and the row replaces the button
- **Requirement:** R2, R3, R5 · **Priority:** High
- **Steps:** click Poproś o dane in the New card; observe the label; wait ≤ 7 min
- **Expected:** button reads "Szukam na Decathlon…" with a spinner; `POST /v1/bike/missing` → 200 and `POST /v1/bike/decathlon/search` → 200 once each; afterwards ≥ 1 row with source `decathlon.pl` and an `https://www.decathlon.pl/` link in the card, button gone; no console errors; `bike_offer` holds the row (`source='decathlon.pl'`, `is_new=true`, no photos)

### TC-032-04 — Foreign brand: instant "Nie znaleziono ofert", no searcher run
- **Requirement:** R2, R6 · **Priority:** High
- **Preconditions:** Trek / Marlin 5 — New card empty (Allegro cached as used, Ceneo uncached → 500)
- **Steps:** wait for the New card's button; click it; time the response
- **Expected:** `POST /v1/bike/decathlon/search` → 200 `{offers: [], info: "Decathlon nie sprzedaje marki Trek …"}` in < 5 s (no searcher request in the searcher log); button reads "Nie znaleziono ofert", disabled; `/v1/bike/missing` → 200

### TC-032-05 — A second Decathlon search while one runs is refused, button stays clickable
- **Requirement:** R2, R3 (shared busy slot) · **Priority:** Medium
- **Steps:** page A: Triban / Van Rysel EDR Speed → click New-card button; within seconds page B: Triban / Van Rysel EDR Gravel → click
- **Expected:** B's `/v1/bike/decathlon/search` → 503 within ~6 s and its button reads "Poproś o dane" (enabled); A finishes with a decathlon.pl row or "Nie znaleziono ofert"

### TC-032-06 — Search that finds nothing
- **Requirement:** R5 · **Priority:** Medium · fake-searcher stack
- **Steps:** Triban / Van Rysel EDR Easy → click
- **Expected:** `/v1/bike/decathlon/search` → 200 `offers: []`; button reads "Nie znaleziono ofert", disabled; card still without decathlon.pl rows

### TC-032-07 — Searcher failure returns the button to clickable
- **Requirement:** R5 · **Priority:** High · fake-searcher stack
- **Steps:** Decathlon / Triban RC 520 → click (fake answers 502) → click again
- **Expected:** `/v1/bike/decathlon/search` → 502; button reads "Poproś o dane", enabled; a second click sends another request

### TC-032-08 — Regression: the Used card still serves stored OLX rows
- **Requirement:** regression (TODO-031) · **Priority:** Medium
- **Steps:** on Trek / Marlin 5 wait for the Used card
- **Expected:** ≥ 1 `olx.pl` row from the DB; `/v1/bike/used` → 200

### API-level cases (covered by the smoke suites, not repeated in the browser)
- `POST /v1/search/decathlon` without key → 401; real search Rockrider ST 100 → 200 + rows in `bike_offer`
  (`source='decathlon.pl'`, 0 photo rows) (`searcher/scripts/test_searcher.py` TC-7..9).
- `POST /v1/bike/decathlon` seeded fixture read (`is_new` true, `city` null, `photos []`, no cache row, < 5 s), unknown
  bike → 200 empty; `POST /v1/bike/decathlon/search` unknown bike → 404, Trek → 200 empty with `info` in < 5 s, live
  Rockrider ST 100 → 200 and `/v1/bike/decathlon` reads the same row back (`backend/scripts/test_search.py` TC-33..35).
- OLX regression: TC-30..32 and `test_searcher.py` TC-1..6 re-run unchanged.

## Results

Executed 2026-09-26 with headless Playwright (global `python` 3.14 with `playwright`; scripts in the session scratchpad —
not committed; evidence in `evidence/`). Two rounds: the only round-1 failure (TC-032-03) was a harness defect, not an
application defect, and the case was re-run on a different bike after the fix. **Final: 8 passed · 0 failed · 0 blocked.**

| Case | Result | Round | Evidence / actual |
|---|---|---|---|
| TC-032-01 | Pass | 1 | Riverside 500 reopened: New card rendered the stored decathlon.pl row (`Nowy`, 1599 zł) 5.1 s after the search click (DB-first search → details), no Request-data button, exactly one `POST /v1/bike/decathlon` → 200, no `/decathlon/search` (`tc01_riverside_new_from_db.png`) |
| TC-032-02 | Pass | 1, 2 | Riverside 500 / Van Rysel GRVL GRX AF: skeleton first (0 rows, 0 buttons), "Poproś o dane" after the grace; `/v1/bike/decathlon` → 200 empty; Allegro/Ceneo → 500 (no API credits, expected) (`tc02_riverside_new_card_button.png`) |
| TC-032-03 | Pass | 2 (harness fixed) | Round 1, Riverside 500: "Szukam na Decathlon…" + spinner → after 45 s one decathlon.pl row (`…/rower-crossowy-riverside-500-z-hamulcami-tarczowymi/_/R-p-300777`) replaced the button, `/missing` 200, `/decathlon/search` 200 — every application check green; the harness failed it on "no console errors", which were the browser's own `Failed to load resource: 500` lines from the uncached AI endpoints. Round 2 with the filter, Decathlon / Van Rysel GRVL GRX AF: same flow, 133 s (CLI 16 turns), row `…/rower-gravelowy-triban-grvl-grx-af-2x12/_/R-p-343001`, `app_errors=[]`, 4 browser 500 lines (`tc03_grvl_searching.png`, `tc03_grvl_after_search.png`; round 1: `tc03_riverside_*.png`) |
| TC-032-04 | Pass | 1 | Trek Marlin 5: click → `/v1/bike/decathlon/search` → 200 in **0.53 s** (backend log: "not a Decathlon house brand", no searcher request in the searcher log), button "Nie znaleziono ofert" disabled, `/missing` → 200 (`tc04_marlin5_foreign_brand.png`) |
| TC-032-05 | Pass | 1 | Triban / Van Rysel EDR Speed search running; Triban / Van Rysel EDR Gravel clicked seconds later → `/v1/bike/decathlon/search` → **503** within 6 s, its button "Poproś o dane" enabled. The first search ended after 56 s with "Nie znaleziono ofert": the CLI found no "EDR Speed" variant on decathlon.pl (only EDR AF / Easy / EDR-G exist) — a genuine empty result, 0 rows written, nothing deleted (`tc05_edr_gravel_busy_refused.png`, `tc05_edr_speed_first_search_done.png`) |
| TC-032-06 | Pass | 1 (fake stack) | Fake searcher `200 offers: []` for Triban / Van Rysel EDR Easy → button "Nie znaleziono ofert", disabled; no decathlon.pl rows; `/missing` and `/decathlon/search` → 200 (`tc06_edr_easy_not_found.png`) |
| TC-032-07 | Pass | 1 (fake stack) | Fake searcher 502 for Decathlon / Triban RC 520 → button "Poproś o dane", enabled; second click sends a second request (`[502, 502]`) (`tc07_rc520_502_clickable_again.png`) |
| TC-032-08 | Pass | 1 | Trek Marlin 5: Used card lists the 5 stored `olx.pl` rows, `/v1/bike/used` → 200 — the generalised `save_offers` / `_get_stored_offers` did not disturb the OLX path (`tc04_marlin5_foreign_brand.png`, full page) |

Smoke suites (run before the browser cases, same servers):
- `searcher/scripts/test_searcher.py` TC-1..9 **ALL OK** — OLX regression: Trek Marlin 5, 5 listings × 4 photos in 75 s;
  Decathlon: `Decathlon / Rockrider ST 100` → 1 real offer (1199 zł, `…/rockrider-st-100/_/R-p-192872`) in 136 s, 1 `bike_offer`
  row (`source='decathlon.pl'`), 0 photo rows.
- `backend/scripts/test_search.py` TC-30..35 **all OK** through a port-swapped runner (`:8001`; the full file cannot pass —
  its Ceneo/AI cases hit the API without credits): DB reads from fixtures in 0.3–0.4 s with no cache row, unknown bike →
  200 / 404, Trek → `"Decathlon nie sprzedaje marki Trek — …"` in 0.29 s with no searcher call, live OLX 80 s and live
  Decathlon 78 s, each followed by a DB round-trip that returned the same rows.

Harness / environment notes (none of them application bugs): (1) TC-03's "no console errors" oracle had to exclude the
browser's `Failed to load resource` lines caused by the uncached AI endpoints (500, no API credits) — `NetLog.app_errors`;
(2) the backend venv ships `patchright`, not `playwright`, so the browser scripts run on the global interpreter;
(3) midway through, Claude Code stopped every background server for low system memory (Chrome ≈ 9 GB); the stack was
restarted after the user freed memory (an `n8n` container) and the interrupted backend smoke run was repeated from scratch.

Side effects left in the local database (real, paid searches — kept on purpose): decathlon.pl rows for
`Decathlon / Rockrider ST 100` (id 28), `Riverside / Riverside 500` (34), `Decathlon / Van Rysel GRVL GRX AF` (621);
refreshed OLX rows for Trek Marlin 5; `bike_missing_request` `offers_new` counters for the bikes clicked above.

The task is ready to move to `backlog/done/` once its PR merges (merged is the bar); `TODO_ISSUE_010` moves with it.
