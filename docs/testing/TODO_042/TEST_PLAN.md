# TODO-042 — manual test plan and results

Task: `backlog/TODO_042_EQUIPMENT_SEARCHER.md` (equipment details + photos as DB reads, on-demand searches in the searcher).
Change set: uncommitted diff of `feature/042-equipment-searcher` against `origin/main` (b84d967). Tester: manual-tester skill, 2026-10-01.

## Environment

| Item | Value |
|---|---|
| Database | **`biker_qa042`** — an isolated PostgreSQL 17 database in the `biker-pg` container, copied from the worktree's `backend/cache.db` (old layout, 566 stored details) with `copy_sqlite_to_postgres.py` after `migrate_equipment_tables.py --db` on the scratch copy. The shared `biker` database could not be used: another worktree (`refactor-remove-bike-detail`) had already dropped `bike_detail` there and re-keyed `bike_detail_component` to `bike_id`, a layout this branch does not support. |
| Backend | `uvicorn app.main:app --port 8003` (8002 belongs to the feature-043 worktree), `DATABASE_URL` → `biker_qa042`, `SEARCHER_URL=http://localhost:8101` |
| Searcher | round 1: real searcher on 127.0.0.1:8101 (`claude` 2.1.287, Haiku 4.5); round 2: stub `scratchpad/qa042/stub_searcher.py` (modes 503 / 502 / 400 / 429 / empty / slow) |
| Frontend | Vite on 5178, `BIKER_API_URL=http://localhost:8003` (5175–5177 taken) |
| DB note | The lead approved an isolated copy (suggested SQLite). PostgreSQL was used instead, because the searcher has no SQLite fallback. The PostgreSQL lock paths (`SELECT … FOR UPDATE` on `equipment`) therefore run, but only on the real searcher's store path. |
| Tools | Python Playwright (global python), headless Chromium; curl; psql |
| Out of scope | `/v1/equipment/review` answers 500 here (no Anthropic key in this worktree) — the review section simply stays hidden |

## Traceability

| # | Requirement | Implemented in | Status |
|---|---|---|---|
| R1 | `/v1/equipment/details` + `/photos` = DB reads by id, else by normalised name; unknown → empty 200; no generic cache | `backend/app/equipment_routes.py`, `equipment_repository.py` | Implemented |
| R2 | `/…/details/search` + `/…/photos/search`: 404 bike / element before the searcher; 503 not configured / unavailable / busy (429 too); 502 detail; 400 limit; single-flight | `equipment_routes.py`, `searcher_client.py` | Implemented |
| R3 | Searcher stores only usable results, creates `equipment`, links only this bike's rows, photos insert-only | `searcher/app/repository.py`, `equipment_repository.py` | Implemented (details store path verified manually on the Kona; photo insert path only by pytest) |
| R4 | Re-save of bike details (backend + searcher) keeps `equipment_id` | `backend/app/repository.py`, `searcher/app/repository.py` | Implemented |
| R5 | UI: linked element shows stored data at once; unlinked → buttons (Opis + Komponenty one run, gallery separate), only on click | `useEquipment.ts`, `useSharedRun.ts`, `EquipmentDetailsView.tsx` | Implemented |
| R6 | `/v1/bike/*` unchanged; `/v1/equipment/review` still auto-fetched | `App.tsx`, `main.py` | Implemented |

## Test cases and results

| ID | Req | Case | Round | Result | Evidence |
|---|---|---|---|---|---|
| TC-01 | R5 | Open an unlinked element (Trek Marlin 5 / Shimano Altus RD-M315): only reads `equipment/details`, `equipment/photos`, `equipment/review`; after 5 s three "Poproś o dane" buttons (Zdjęcia, Opis, Specyfikacja) | 1 | Pass | `r1/02_equipment_open.png` |
| TC-02 | R5 | Click Opis → Opis and Specyfikacja both "Szukam danych wyposażenia…", one `details/search` request | 1 (real) | Pass | `r1/03_details_pending.png` |
| TC-03 | R3/R5 | Real details run finishes; result shown; a bike part gets a fitting category. Actual on the first code: 40.1 s, category `apparel`, model `found:false` → "Nie znaleziono danych" in both sections, nothing written. After the `parts` fix the name resolves to `parts`. `found:false` is acceptable because "RD-M315" is not a real Shimano part number | 1 (real) | Pass with note (Fail on the first code) | `r1/04_details_filled.png`, searcher log |
| TC-04 | R3/R5 | Click gallery → "Szukam zdjęć…" → result. Actual: 46.0 s, no product URL → "Nie znaleziono zdjęć", nothing written | 1 (real) | Pass (empty path) | `r1/05_photos.png` |
| TC-05 | R5 | Back + re-open the same element after an empty search: reads only, no `/search`, buttons again (nothing stored) | 1 | Pass | `r1/06_reentry.png` |
| TC-06 | R1/R5 | Element linked by `equipment_id` (seeded, Trek FX 3 Disc / Trek Standard Grip Tape): read body carries `equipment_id`, data + spec + 2 photos (display order) shown within 2.5 s, no buttons, no `/search` | 1 | Pass | `r1/11_by_id_equipment.png` |
| TC-07 | R1/R5 | Same name on another bike without a link (Trek Marlin 5): read by name shows the stored data, no run | 1 | Pass | `r1/11_by_name_equipment.png` |
| TC-08 | R1 | API reads: by id, by name with other casing/whitespace, unknown id → empty 200 (~0.2 s), empty model → 422; no new generic-cache rows (11 old `/v1/equipment/details` rows unchanged) | 1 | Pass | curl |
| TC-09 | R1/R6 | `/v1/bike/details` returns `equipment_id` on the linked element only (FX 3 Disc = 1, Marlin 5 = null) | 1 | Pass | curl |
| TC-10 | R6 | Bike details view regression (Trek FX 3 Disc, Marlin 5): photos, review, Używane / Nowe offers render; bike reads unchanged | 1 | Pass | `r1/10_*_bike.png` |
| TC-11 | R4 | Backend `save_bike_details` and searcher `save_details` re-save of FX 3 Disc without links in the input keep `equipment_id = 1` | 1 | Pass | psql |
| TC-12 | R2 | 404 "Bike not found" / "Component not found" on both search routes, 0 searcher calls | 1 | Pass | curl, searcher log |
| TC-13 | R2 | 422: empty / missing / 256-char `element_name`, empty `bike_company`, 33-char `category` | 1 | Pass | curl |
| TC-14 | R2 | Searcher down → 503 "Equipment details/photos searcher unavailable" | 2 | Pass | curl |
| TC-15 | R2 | Stub 503 and 429 → 503 "… is busy — try again in a moment"; 502 → 502 "boom"; 400 → 400 "Claude usage limit reached"; stored element name forwarded (caller's casing ignored) | 2 | Pass | curl, `hits.log` |
| TC-16 | R2/R5 | UI after 503 / 502 / 400: both details buttons and the gallery button clickable again ("Poproś o dane"), no error text | 2 | Pass | `r2/mode_*.png` |
| TC-17 | R5 | UI empty 200: run started from the Specyfikacja button, Opis click meanwhile ignored, exactly 1 request, both "Nie znaleziono danych"; gallery "Nie znaleziono zdjęć" | 2 | Pass | `r2/slow_shared_empty.png`, `r2/photos_empty.png` |
| TC-18 | R2 | Single-flight: 3 concurrent details searches (mixed casing) → 1 stub hit; photos separate | 2 | Pass | `hits.log` |
| TC-19 | R2 | `SEARCHER_MAX_INFLIGHT=1`: 2nd and 3rd concurrent searches → 503 busy immediately, 1 stub hit | 2 | Pass | `cap_test.py` |
| TC-20 | R2 | `SEARCHER_URL` unset → 503 "Equipment details/photos searcher is not configured", 0 stub hits | 2 | Pass | curl |
| TC-21 | all | `scripts/test_search.py` against :8003 (paid Decathlon case skipped) | 2 | Pass — 18 passed, 0 failed, 4 skipped | `smoke.log` |
| TC-22 | R3/R5 | After the `parts` / `locks` fixes, real details run on Kona El Kahuna / "Abus T82 Battery Lock": category `locks`; 54.4 s ($0.17); both sections fill (Polish 5-sentence description, 3 elements, 8 spec rows); DB: `equipment` id 4 (`locks`, company "", model = stored name), `equipment_detail` + 8 component rows, Polish `short_description`; only the Kona's element linked (2 links in the whole table: Kona → 4, the FX 3 Disc seed → 1) | 1b (real) | Pass | `r1b/04_details_filled.png`, psql |
| TC-23 | R5/R1 | Back + re-open the Kona element: reads carry `equipment_id: 4`, data shown, no `/search`; `/v1/bike/details` returns `equipment_id: 4` on that element; `/v1/equipment/details` by id 0.21 s | 1b | Pass | `r1b/06_reentry.png` |
| TC-24 | R3 | Real photo run on the Kona: 106.5 s ($0.36); the model returned `veloconnect-ch.abus.com/…`, a host that does not exist in DNS; the URL guard rejected it, nothing written, "Nie znaleziono zdjęć" | 1b (real) | Pass with note (guard correct; photo insert path not exercised manually) | searcher log |
| TC-25 | R5 | No offer/buy links on an equipment page (CLAUDE.md: equipment has details + review only). Actual: all 3 description sources are shops (ebike24.com, melbournepowered.com.au, elanusparts.com) although `equipment_details.md` forbids shops. Retest after the code-side filter (`searcher/app/shop_filter.py` in `build_equipment_details`), no paid run: the filter flags all 3 shop URLs and keeps abus.com and road.cc; the stored item, rebuilt and re-saved through `build_equipment_details` + `save_equipment_details`, keeps its 777-char description, 8 component rows, details row id and both links, with 0 sources; the page shows the description without shop chips and no `/search` call | 1b + retest | Pass on retest (Fail on the first code) | `r1b/06_reentry.png` |
| TC-26 | R3 | A lock with a light keyword ("Abus T82 Battery Lock") gets `locks`. First code: `lights` (Fail, Medium). Retest after the inference fix (locks before lights, head noun wins): `locks` (free one-liner); the derailleur gets `parts`, labelled "Części rowerowe" in the UI | 1b | Pass on retest (Fail on the first code) | `resolve_category` one-liner |

Evidence paths are relative to the session scratchpad `qa042/`.

## Findings

1. **Spec-tree parts landed in the apparel catch-all** (Medium) — **fixed**. A fifth category `parts` is now the default. The derailleur, a saddle and grip tape all resolve to `parts`.
2. **No message after a failed search** (Low, by design). After 503 / 502 / 400 the button just becomes clickable again; the 400 subscription-limit text is never shown. Same behaviour as the bike view's buttons.
3. **"Abus T82 Battery Lock" resolved to `lights`** (Medium) — **fixed** (locks now precede lights, "battery lock" is a locks keyword; the item resolves to `locks`). The `lights` keyword "battery" is checked before `locks` in `searcher/app/equipment_categories.py` (`_PATTERNS`). An e-bike battery lock therefore got the lights prompt.
4. **Shop pages as description sources** (Medium, TC-25) — **fixed** by a code-side filter, retested. The model ignored the prompt's "never a shop" rule; the sources chips link to three shops. Suggested: drop shop domains from `sources` in code (the prompt alone does not hold), or accept with the lead's agreement.
5. **Untranslated spec key "Key type"** (Low, cosmetic) — **fixed**, it now renders "Rodzaj klucza". `frontend/src/specLabels.ts` has no entry; it renders in English next to Polish labels.
6. **The model can return a non-existent product host** (Low). The photo run cost $0.36 and 105 s for `veloconnect-ch.abus.com`, which has no DNS record; the guard handled it correctly.

## Paid runs

| Run | Item | Category | Wall time | Cost | Result |
|---|---|---|---|---|---|
| Details | Trek Marlin 5 / Shimano Altus RD-M315 | apparel (first code) | 40.1 s | $0.10 | found:false, nothing stored |
| Photos | same | apparel (first code) | 46.0 s | n/a | no product URL |
| Details | Kona El Kahuna / Abus T82 Battery Lock | locks | 54.4 s | $0.17 | stored, equipment_id 4, linked |
| Photos | same | locks | 106.5 s | $0.36 | URL on a non-existent host, rejected |

## Final results — 2026-10-01

| Round | Searcher | Cases | Pass | Fail | Blocked |
|---|---|---|---|---|---|
| 1 | real (first code) + seeded DB | TC-01–TC-13 | 13 (TC-03 and TC-04 with notes) | 0 | 0 |
| 1b | real (after the `parts` and locks fixes) | TC-22–TC-26 | 5 (TC-24 with a note; TC-25 and TC-26 on retest) | 0 | 0 |
| 2 | stub | TC-14–TC-21 | 8 | 0 | 0 |
| Final regression | real searcher, then down | TC-01/05 (open, re-entry), TC-06/07/10 (seeded by id / by name, bike view), TC-08 (reads), TC-12/13 (404 / 422, 0 searcher runs), TC-14 (503 unavailable), TC-21 (smoke 18 passed, 0 failed, 4 skipped) | all | 0 | 0 |
| **Total** | | **26** | **26** | **0** | **0** |

Notes: the photo insert path ran only in pytest; both real photo runs found nothing usable. Open Low items: no message after a failed search (by design), and a model-supplied product URL can be on a dead host (the guard handles it). The isolated database `biker_qa042` was dropped after the run.
