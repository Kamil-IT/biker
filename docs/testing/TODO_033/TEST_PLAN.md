# Test plan — TODO-033 On-demand Allegro search in the searcher

Branch `feature/033-searcher-allegro` · task `backlog/TODO_033_SEARCHER_ALLEGRO_ON_DEMAND.md` · executed 2026-09-26.

## Scope

In scope: the on-demand Allegro search path end to end — the searcher's new `POST /v1/search/allegro` (CLI-tuned
prompt, Playwright photo scrape, DB write), the backend's DB-only `POST /v1/bike/allegro`, the proxy
`POST /v1/bike/allegro/search`, the raised concurrency (two searches in flight on both sides, 429 mapped to busy) and the
frontend's **Poproś o dane** button in the **"Nowe"** card, which now fires the Decathlon and Allegro searches **in
parallel**. Regression: the OLX path (TODO-031) and the Decathlon path (TODO-032) — same searcher, same button component,
shared slots — and the other Request-data buttons.

Out of scope (per task): Ceneo, backfill of the old cached Allegro responses, TTL / refresh, listing liveness, the global
`url` uniqueness (TODO-021), the Allegro REST API (TODO-008), rate limiting, GCP deploy (only after the user's go-ahead).

## Environment and constraints

- Local stack from this checkout: searcher `127.0.0.1:8102` (`SEARCHER_MAX_CONCURRENT=2`, `PLAYWRIGHT_HEADLESS=true`),
  backend `127.0.0.1:8002` (`SEARCHER_MAX_INFLIGHT=2`), frontend `localhost:5176` (ports 8000/8001/8100/5174/5175 are
  held by another worktree's compose stack and stale dev servers from the previous session — not touched).
- Database: local PostgreSQL 17 (`biker-pg`, `DATABASE_URL` in `backend/.env` and `searcher/.env`).
- Error/empty paths run on a second stack wired to a **fake searcher** (`127.0.0.1:8199` → backend `8003` → frontend
  `5177`), because the real CLI cannot be made to return "no offers", 502, 503 or an empty price on demand. The fake picks
  its answer from the requested model name; the fixture bikes `Smoke Fixture / Empty Bike | Fail Bike | Busy Bike |
  NoPrice Bike` (ids 703–706) exist in `bike` for the duration of the run and are deleted afterwards.
- **The Anthropic API key has no credits**, so every uncached AI endpoint answers 500. Test bikes are therefore rows that
  already exist in `bike` and are reachable through the DB-first search (brand + model filters): `Trek / Marlin 6` (59),
  `Trek / Marlin 8` (29), `Triban / Van Rysel EDR Easy` (633) — none of them has stored offers of any source, so their
  "Nowe" card is empty until a search runs; `Trek / Marlin 5` (1, 5 stored OLX rows) and `Riverside / Riverside 500` (34,
  1 stored decathlon.pl row) for the regression cases.
- **allegro.pl answers HTTP 403 (DataDome) to every automated request** from this machine — the CLI's WebFetch and
  Chromium alike (probes, see the task file decision 4). Every real Allegro search in this plan is therefore expected to
  store offers **without photos**; that is the documented behaviour, not a defect.
- Expected behaviour change surfaced by the tests: Allegro responses that the *old* endpoint left in the generic cache
  (11 bikes, e.g. Trek Marlin 5 / FX 3 Disc, Indiana Rock Jr 24) are no longer served — `/v1/bike/allegro` reads
  `bike_offer` only (decision 5, no backfill).

## Requirement traceability

| # | Requirement (task file) | Implemented in | Status |
|---|---|---|---|
| R1 | `POST /v1/bike/allegro` is a pure DB read of `bike_offer` (`source='allegro.pl'`) + `bike_offer_photos`: zero AI/CLI calls, no generic cache, `{offers, info}` unchanged, unknown bike → 200 empty | `backend/app/main.py` `bike_allegro`, `backend/app/offers_repository.py` `get_allegro_offers` (over `_get_stored_offers`, `is_new` from the row, photos by `display_order`) | Implemented |
| R2 | New `POST /v1/bike/allegro/search`: 404 unknown bike → proxy to the searcher; 503 not configured / unreachable / busy (fixed strings naming "Allegro searcher"), 502 with the searcher's detail; never cached; HTTP 429 from the searcher URL (Cloud Run overflow) = busy | `backend/app/main.py` `bike_allegro_search`, `backend/app/searcher_client.py` `search_allegro`, `SEARCH_PATHS`, `BUSY_STATUSES = (503, 429)` | Implemented |
| R3 | Searcher `POST /v1/search/allegro`: same auth/status mapping, ≤ 3 offers, only `allegro.pl/oferta/…` or `/produkt/…` URLs, `is_new` from the listing, Playwright photos (≤ 8, gallery order, non-fatal), replace semantics scoped to `(bike, 'allegro.pl')`, empty result keeps rows | `searcher/app/main.py` `search_allegro` → `_run_search`, `searcher/app/allegro_finder.py` (`ALLEGRO_OFFER_URL_RE`, `_to_offers`), `searcher/app/allegro_image_fetcher.py` (moved; `MAX_PHOTOS = 8`, non-200 page skipped), `searcher/app/repository.py` `save_offers` (unchanged) | Implemented |
| R4 | Two searches at once: backend `SEARCHER_MAX_INFLIGHT` default 2, searcher `SEARCHER_MAX_CONCURRENT` default 2, Cloud Run `--max-instances 2` with `--concurrency 1`; a third concurrent search of any source is refused with 503, nothing queues | `backend/app/searcher_client.py` `DEFAULT_MAX_INFLIGHT = 2`, `searcher/app/config.py` `DEFAULT_MAX_CONCURRENT = 2`, `scripts/deploy.ps1` | Implemented |
| R5 | Frontend: the "Nowe" card's button records `offers_new` **and** runs Decathlon + Allegro concurrently (`Promise.allSettled`); label "Szukam na Allegro i Decathlon…"; rows from either source replace the button as they arrive; "Nie znaleziono ofert" only when both came back empty; clickable again when a search failed and neither brought rows; the button is offered only while neither source has a stored row (`hasNewSourceRows`); Allegro rows split into New/Used by `is_new`; the automatic `POST /v1/bike/allegro` on opening stays (now a DB read) | `frontend/src/App.tsx` `searchAllegro`, `searchNew`, `fetchStoredOffers`; `frontend/src/components/BikeDetailsView.tsx` `MergedOffersSection` (`hasNewSourceRows`, `pendingLabel`), `OfferRow`; `RequestDataButton.tsx` unchanged | Implemented (+ X2, X3) |
| R6 | `backend/app/bike_offer_finder.py`, `allegro_image_fetcher.py` and `prompts/bike_offer_allegro.md` leave the backend (the two Python files move to the searcher); the dev scripts that only drove them go; `pytest` passes | deleted / moved (`git status`); `scripts/test_browser_slots.py` no longer imports them (and no longer imports the long-gone `olx_image_fetcher` — see X4); `pytest` 22 passed | Implemented |
| R7 | Smoke tests: `backend/scripts/test_search.py` `case_allegro` (seeded allegro.pl fixture with a photo row, < 5 s, no generic-cache row, unknown bike → 200 empty) + `case_allegro_search` (unknown bike → 404, no paid run); `searcher/scripts/test_searcher.py` TC-7 (401) / TC-8 (422) on `/v1/search/allegro`; the one paid run of the suite stays `case_decathlon_search` | `test_search.py` `case_allegro` / `case_allegro_search`, `test_searcher.py` TC-7/8 | Implemented — results below |
| R8 | Docs: CLAUDE.md, README.md, backend/README.md (both Allegro sections with HTTP example + Flow), frontend/README.md, searcher/README.md, `.env.example` ×2, `scripts/deploy.ps1`, `docker-compose.yml`, `backend/app/DB_MIGRATION.md` | updated | Implemented |
| R9 | No backfill: the generic-cache rows under `/v1/bike/offer` stay as dead rows; `_ALLEGRO_CACHE_KEY` gone | `backend/app/main.py` (no `get_cached`/`set_cached` on the Allegro routes) | Implemented — visible in TC-033-02 (Trek Marlin 5's cached Allegro offer is no longer shown) |
| X1 | (decided during the probes, task decision 4) the prompt is **not** byte-identical: allegro.pl answers 403 to every fetch, so `searcher/app/prompts/bike_offer_allegro.md` is a CLI-tuned rewrite that works from WebSearch results only — price/condition from the result snippet, `price: ""` when none shows it | `searcher/app/prompts/bike_offer_allegro.md`; probes: Kross Level 3.0 → 3 offers / 67 s, Trek Marlin 4 → 3 offers / 75 s, Trek Marlin 6 (through the real module, incl. the fetcher) → 3 offers with prices / 93 s + 403 on both offer pages → `photos: []` | Extra — validated |
| X2 | (review finding, medium) `searchNew` rejects when a search failed and **neither** brought rows — the first cut rejected only when both failed, so an Allegro 503 next to an instantly-empty Decathlon (every non-Decathlon brand) ended as a false "Nie znaleziono ofert" with no way to retry | `frontend/src/App.tsx` `searchNew` (`gotRows`) | Extra — TC-033-04, TC-033-06, TC-033-07 |
| X3 | (not requested) an offer with `price: ""` renders "cena w ofercie" instead of an empty price slot; the pending label is no longer gated on `hasNewSourceRows` (it flipped to the default "Szukam…" when a used Allegro row arrived mid-search) | `BikeDetailsView.tsx` `OfferRow`, New `OfferCategoryCard` | Extra — TC-033-08 |
| X4 | (not requested) `backend/scripts/test_browser_slots.py` imported the backend `olx_image_fetcher` that TODO-031 removed, so `pytest` failed at collection on `main`; fixed while dropping the Allegro fetcher from it | `backend/scripts/test_browser_slots.py` | Extra — `pytest` 22 passed |
| K1 | Known limitation (as in TODO-031/032): `bike_offer.url` is globally unique — a listing URL already stored under another bike identity is not re-parented; fix = TODO-021 item 2 | `searcher/app/repository.py` | Documented |
| K2 | Known limitation: DataDome blocks the photo scrape (403 on the homepage and every offer page, headless and headed) → Allegro offers are stored with `photos: []` today; the fetcher stays as a non-fatal step in case Allegro's blocking changes | `searcher/app/allegro_image_fetcher.py` | Documented — TC-033-01 |
| K3 | Known limitation: a search-result snippet may not show the price → `price: ""` (Trek Marlin 4 probe: 3 offers, 0 prices) | prompt step 4, `OfferRow` | Documented — TC-033-08 |

## Test cases

### TC-033-01 — Empty New card → click runs Allegro (and the instant-empty Decathlon) → the real rows replace the button
- **Requirement:** R2, R3, R5 · **Priority:** High
- **Preconditions:** Trek / Marlin 6 has no stored offers of any source and no cached Allegro response
- **Steps:** open `/`, Filtry → Marka `Trek`, Model `Marlin 6` → Znajdź → click the result card → wait for the "Nowe"
  card; wait for "Poproś o dane" (after the 5 s grace); click; observe the label; wait ≤ 7 min
- **Expected:** skeleton first, then the button; after the click the button reads "Szukam na Allegro i Decathlon…" with a
  spinner; `POST /v1/bike/missing` → 200, `POST /v1/bike/decathlon/search` → 200 at once (Trek is not a Decathlon brand,
  no searcher run), `POST /v1/bike/allegro/search` → 200 after the CLI run; ≥ 1 allegro.pl row in the New **or** Used card
  (by `is_new`), the button gone; `bike_offer` holds the rows (`source='allegro.pl'`, 0 photo rows — K2);
  `bike_missing_request` `offers_new` +1; no console errors from the app

### TC-033-02 — Reopen the bike → stored Allegro rows come from the DB read, no search, no button
- **Requirement:** R1, R5, R9 · **Priority:** High
- **Preconditions:** TC-033-01 stored ≥ 1 allegro.pl row for Trek / Marlin 6
- **Steps:** open its details again; sample the cards after the 5 s grace
- **Expected:** exactly one `POST /v1/bike/allegro` → 200 within ~2 s carrying the stored rows, no `/allegro/search`; the
  rows show `allegro.pl` as source; the card that holds them shows no "Poproś o dane"

### TC-033-03 — Decathlon house brand: both searches run in parallel, none refused
- **Requirement:** R4, R5 · **Priority:** High
- **Preconditions:** Triban / Van Rysel EDR Easy has no stored offers (a previous TODO-032 run found nothing on decathlon.pl)
- **Steps:** open its details; click the New card's button; watch the searcher log; wait ≤ 8 min
- **Expected:** two `claude CLI start` lines within seconds of each other (allegro + decathlon), no 503 on either proxy
  (`/v1/bike/decathlon/search` → 200 and `/v1/bike/allegro/search` → 200); afterwards rows from either source, or
  "Nie znaleziono ofert" only if both really found nothing

### TC-033-04 — A third search while the pair runs is refused and its button stays clickable
- **Requirement:** R4, R5 (X2) · **Priority:** High
- **Steps:** while TC-033-03's pair is running, page B: Trek / Marlin 8 → click the New card's button
- **Expected:** `/v1/bike/decathlon/search` → 200 (instant, foreign brand) and `/v1/bike/allegro/search` → **503** within
  seconds (backend: two searches already in flight); the button reads "Poproś o dane" and is enabled (not
  "Nie znaleziono ofert"); no searcher run for Marlin 8

### TC-033-05 — Search that finds nothing
- **Requirement:** R5 · **Priority:** Medium · fake-searcher stack
- **Steps:** Smoke Fixture / Empty Bike → click
- **Expected:** `/v1/bike/allegro/search` → 200 `offers: []`, `/v1/bike/decathlon/search` → 200 empty (foreign brand);
  button reads "Nie znaleziono ofert", disabled

### TC-033-06 — Searcher failure (502) returns the button to clickable, a second click sends again
- **Requirement:** R2, R5 (X2) · **Priority:** High · fake-searcher stack
- **Steps:** Smoke Fixture / Fail Bike → click (fake answers 502) → click again
- **Expected:** `/v1/bike/allegro/search` → 502 while Decathlon answered 200 empty; button "Poproś o dane", enabled; the
  second click sends another `/allegro/search` (`[502, 502]`)

### TC-033-07 — Searcher busy (503) next to an instantly-empty Decathlon returns the button to clickable
- **Requirement:** R2, R5 (X2) · **Priority:** High · fake-searcher stack
- **Steps:** Smoke Fixture / Busy Bike → click (fake answers 503 "searcher busy")
- **Expected:** backend `/v1/bike/allegro/search` → 503 (`"Allegro searcher is busy — try again in a moment"`); button
  "Poproś o dane", enabled — the mixed outcome must not read as "no offers"

### TC-033-08 — Offer without a visible price renders "cena w ofercie"
- **Requirement:** R5 (X3, K3) · **Priority:** Medium · fake-searcher stack
- **Steps:** Smoke Fixture / NoPrice Bike → click (fake answers one allegro.pl offer, `is_new: true`, `price: ""`)
- **Expected:** the row appears in the New card with the source `allegro.pl`, the "Nowy" badge and the text
  "cena w ofercie" where the price would be; no button

### TC-033-09 — Regression: stored OLX rows in the Used card, stored Decathlon row in the New card (no button)
- **Requirement:** regression (TODO-031 / TODO-032), R5 `hasNewSourceRows` · **Priority:** Medium
- **Steps:** Trek / Marlin 5 → wait for the Used card; Riverside / Riverside 500 → wait for the New card, then past the grace
- **Expected:** ≥ 5 `olx.pl` rows, `/v1/bike/used/olx` → 200; Riverside: the decathlon.pl row in the New card,
  `/v1/bike/decathlon` and `/v1/bike/allegro` → 200 each, no `/…/search`, no "Poproś o dane" in the New card

### API-level cases (covered by the smoke suites, not repeated in the browser)
- `POST /v1/search/allegro` without key → 401, with key but a blank model → 422 (`searcher/scripts/test_searcher.py`
  TC-7/8); OLX / Decathlon auth + validation regression TC-1..6.
- `POST /v1/bike/allegro` seeded fixture read (`is_new` true, `city` null, `photos == [photo]`, no generic-cache row,
  < 5 s), unknown bike → 200 empty; `POST /v1/bike/allegro/search` unknown bike → 404 (`backend/scripts/test_search.py`
  `case_allegro` / `case_allegro_search`); the OLX/Decathlon cases re-run unchanged, incl. the one paid
  `case_decathlon_search`.
- Searcher module end to end without the server (probe, real CLI run): Trek Marlin 6 → 3 offers with prices in 93 s,
  both offer pages 403 → `photos: []`.

## Results

Executed 2026-09-26 with headless patchright Chromium from the backend venv (harness `ui_tests_033.py` in the session
scratchpad — not committed; evidence in `evidence/`). Two rounds: the only round-1 failure (TC-033-03) was a harness
defect, not an application defect — its oracle declared the case finished when the button unmounted on the first source's
rows while the second search was still running — and the case was re-run on another bike with the fixed oracle.
**Final: 9 passed · 0 failed · 0 blocked.**

| Case | Result | Round | Evidence / actual |
|---|---|---|---|
| TC-033-01 | Pass | 1 | Trek Marlin 6: skeleton → "Poproś o dane" → "Szukam na Allegro i Decathlon…" + spinner; `/missing` 200, `/decathlon/search` 200 at once (foreign brand, no run), `/allegro/search` 200 after **99.6 s**; 2 allegro.pl rows stored (new `3,458.19 zł` → New card, used `2,299.00 zł` → Used card; 0 photo rows — both offer pages 403, K2), button gone, `offers_new` 0 → 1, `app_errors=[]` (`tc01_marlin6_new_card_button.png`, `tc01_marlin6_searching.png`, `tc01_marlin6_after_search.png`) |
| TC-033-02 | Pass | 1 | Trek Marlin 6 reopened: both rows rendered from the DB in 2.0 s, exactly one `POST /v1/bike/allegro` → 200, no `/allegro/search`, sources `allegro.pl`, no button after the grace (`tc02_marlin6_from_db.png`) |
| TC-033-03 | Pass | 2 (harness fixed) | Round 1, Triban / Van Rysel EDR Easy: two `claude CLI start` lines at 17:50:09 (decathlon + allegro), Decathlon 1 offer in 49 s, Allegro 3 offers in 61 s, no 503 — every application check green, the harness stopped reading before the Allegro half returned. Round 2, Decathlon / Triban RC 520: two CLI starts at 17:52:19, `/decathlon/search` 200 (1 offer, 4199 zł, 70 s) and `/allegro/search` 200 (2 offers in 76 s, one with `price: ""`), 3 rows in the New card, button gone, `app_errors=[]` (`tc03_edr_easy_searching.png`, `tc03_edr_easy_after_search.png`) |
| TC-033-04 | Pass | 1, 2 | Trek Marlin 8 while the pair ran: `/decathlon/search` 200 (instant, foreign brand), `/allegro/search` **503** in 0.6 s (backend: two searches in flight), button "Poproś o dane" **enabled** — X2 verified; no searcher run for Marlin 8 (`tc04_marlin8_third_search_refused.png`) |
| TC-033-05 | Pass | 1 (fake stack) | Empty Bike: `/allegro/search` 200 `offers: []`, `/decathlon/search` 200 empty → "Nie znaleziono ofert", disabled (`tc05_empty_bike_not_found.png`) |
| TC-033-06 | Pass | 1 (fake stack) | Fail Bike: `/allegro/search` 502 next to an empty Decathlon → "Poproś o dane" enabled; second click → `[502, 502]` (`tc06_fail_bike_clickable_again.png`) |
| TC-033-07 | Pass | 1 (fake stack) | Busy Bike: `/allegro/search` 503 next to an empty Decathlon → "Poproś o dane" enabled (`tc07_busy_bike_clickable_again.png`) |
| TC-033-08 | Pass | 1 (fake stack) | NoPrice Bike: one row in the New card — `allegro.pl · Smoke Fixture NoPrice Bike · Nowy · cena w ofercie →`, no button (`tc08_noprice_bike_row.png`) |
| TC-033-09 | Pass | 1 | Trek Marlin 5: 5 `olx.pl` rows, `/used/olx` 200; Riverside 500: the stored decathlon.pl row in the New card, `/decathlon` 200, `/allegro` 200, no `/…/search`, no button after the grace (`tc09_marlin5_used_regression.png`, `tc09_riverside500_new_from_db.png`) |

Smoke suites (run before the browser cases, same servers):
- `searcher/scripts/test_searcher.py` TC-1..8 **ALL OK** — free (health, 401 ×2 + 422 on OLX, 401 + 422 on Decathlon,
  401 + 422 on Allegro).
- `backend/scripts/test_search.py` (`BIKER_API_URL=http://127.0.0.1:8002`) → **9 passed, 0 failed, 3 skipped** (the three
  `--ai` cases): `allegro` 0.7 s (fixture read with its photo row, no generic-cache row, unknown bike → 200 empty),
  `allegro_search` 0.3 s (404), the one paid `decathlon_search` 189 s (0 offers this time for `Decathlon / Rockrider ST 100`
  — its row is already stored, nothing deleted), OLX / Decathlon cases unchanged.
- `cd backend && pytest` → 22 passed (was failing at collection on `main`, X4).
- Probes through the real searcher module (no server): Trek Marlin 6 → 3 offers with prices in 93 s; the SDK-era prompt:
  Trek Marlin 5 286 s / 1 offer, Kross Level 3.0 49 s / 0 offers; the CLI-tuned prompt: Kross Level 3.0 67 s / 3 offers,
  Trek Marlin 4 75 s / 3 offers without prices.

Harness / environment notes (none of them application bugs): (1) TC-03's round-1 oracle (see above); (2) the "no console
errors" oracle excludes the browser's `Failed to load resource` lines from the uncached AI endpoints (500, no API
credits); (3) ports 8000/8001/8100/5174/5175 were held by another worktree's compose stack and stale dev servers, so this
run used 8102/8002/5176 (+ 8199/8003/5177 for the fake stack); (4) the fake-stack fixture bikes (ids 703–706) were
deleted after the run.

Side effects left in the local database (real, paid searches — kept on purpose): allegro.pl rows for `Trek / Marlin 6`
(59, 2 rows), `Triban / Van Rysel EDR Easy` (633, 3 rows + 1 decathlon.pl row), `Decathlon / Triban RC 520` (33, 2 rows +
1 decathlon.pl row); `bike_missing_request` `offers_new` counters for the bikes clicked above (incl. Trek Marlin 8, whose
Allegro search was refused). No row has photos (K2).
