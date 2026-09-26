# TODO-032 — On-demand Decathlon search in the searcher service (same pattern as TODO-031)

**Notion:** none — this task is not recorded there (confirmed 2026-09-26). Reference: the OLX migration write-up
`docs/OLX_SEARCHER_MIGRATION.md` and `backlog/done/DONE_031_SEARCHER_OLX_ON_DEMAND.md`.
Closes **`TODO_ISSUE_010`** (Decathlon offers always empty for non-Decathlon brands) on the way.

## Goal
`POST /v1/bike/decathlon` still runs one Anthropic SDK `web_search` call (API key, no credits left) on every uncached
details view. Do to it exactly what TODO-031 did to `/v1/bike/used`: the endpoint becomes a **pure DB read** of
`bike_offer` rows with `source = 'decathlon.pl'`, and the search itself moves into the **existing** `searcher/`
service as a second endpoint (`POST /v1/search/decathlon`) that runs the same prompt through the Claude Code CLI
(`claude -p --json-schema`, subscription token) and writes the result into the shared database. The search is
triggered only by the user clicking **Poproś o dane** in the **"Nowe"** offers card.

## Decisions (interview, 2026-09-26)
1. **Same searcher service**, not a second Cloud Run — one image, one secret, one `claude` CLI, one semaphore.
2. **Only Decathlon moves.** Allegro (`/v1/bike/offer`) and Ceneo (`/v1/bike/ceneo`) stay exactly as they are
   (automatic on opening the details view, generic cache, API key).
3. **Trigger = the "Nowe" card's button.** It records the click via `/v1/bike/missing` (`offers_new`) as before
   **and** calls the new backend proxy `POST /v1/bike/decathlon/search`; while running it shows "Szukam na Decathlon…";
   returned offers replace the button; none → "Nie znaleziono ofert"; a failed call → clickable again.
4. **Skip foreign brands.** Decathlon sells (almost) only its house brands, so the backend answers
   `200 {offers: [], info: "Decathlon nie sprzedaje marki <X> — ..."}` **immediately, without any searcher call**
   when `company` is not a Decathlon house brand. Allowlist (normalised: lower-case, apostrophes/hyphens/spaces
   removed): `rockrider`, `btwin` (B'Twin / Btwin / B-Twin), `triban`, `vanrysel`, `elops`, `riverside`, `stilus`,
   `tilt`, `decathlon`. Verified 2026-09-26 (Decathlon: Van Rysel road/gravel, Rockrider MTB, Triban recreational
   road, Elops + Riverside city/hybrid, Btwin kids/folding, Stilus e-bikes, Tilt folding).
5. **Same logic, different transport.** Prompt `bike_offer_decathlon.md` **moves** (byte-identical) to
   `searcher/app/prompts/`; the CLI message is the old one (`Find current offers on decathlon.pl for: {company}
   {model}`); ≤ 3 offers kept (the old finder's `data[:3]`), `photos: []` (no Playwright for Decathlon — the old
   endpoint had none), `is_new` from the model (default `true`), `source = 'decathlon.pl'`, `city = None`.
   Probe 2026-09-26: Rockrider ST 100 → 1 real offer (`https://www.decathlon.pl/p/rower-gorski-mtb-27-5-cala-rockrider-st-100/_/R-p-192872`, 1249 zł) in 64 s.
6. **Persistence and semantics identical to OLX**: bike found by the Python-normalised brand/model compare (created
   only by the searcher for a direct call; the backend proxy answers **404** for a bike not in `bike`), replace
   semantics scoped to `(bike_id, source='decathlon.pl')`, `INSERT … ON CONFLICT (url) DO UPDATE … WHERE bike_id =
   this bike` (a URL already stored under another bike stays there and is not reported as saved), an empty result
   keeps the stored rows, no TTL.
7. **Order of work**: implement → smoke tests → `/manual-tester` locally (searcher :8100, backend :8001, frontend
   :5174, local Postgres `biker-pg`) → **ask the user** before deploying → Cloud Run (same Cloud SQL `biker-pg`, the
   existing `biker-searcher` service gets the new image; backend/frontend redeployed).

## Contract

**Searcher** (`searcher/`)
- `POST /v1/search/decathlon` `{company, model}` + `X-Searcher-Key` → `{offers, info, bike_id, saved}` — same auth,
  same 401/422/502/503 ("searcher busy" — the semaphore is **shared** with `/v1/search/olx`: one CLI run at a time
  per instance)/500 mapping as `/v1/search/olx`. Offers returned = the rows now stored under this bike for
  `source='decathlon.pl'`.
- `app/decathlon_finder.py` — `find_decathlon_offers(company, model) -> (offers, info)`; `run_structured` with the
  OLX schema shape (`{info, offers[]}`, `city` may be null); URL must start with `https://www.decathlon.pl/`,
  dedupe, column-width truncation, `photos=[]`, `city=None`. Raises `SearcherError` when the CLI fails.
- `app/repository.py` — generalise `save_used_offers` into `save_offers(company, model, offers, source)`
  (`is_new` taken from each offer; upsert and stale-row deletion scoped to this bike **and** that `source`); both
  routes call it, the OLX-only name goes. Nothing else in the file changes.
- `app/schemas.py` — `BikeOffer` docstring (both sources); no new fields.
- `scripts/test_searcher.py` — TC-7 401 on `/v1/search/decathlon` without key; TC-8 one real search (Rockrider
  ST 100: `url` on decathlon.pl, `source == 'decathlon.pl'`, `photos == []`, `saved == len(offers)`); TC-9 the rows
  are in `bike_offer` with `source='decathlon.pl'` (count equals the response, no photo rows).
- `README.md` — `## Endpoints` gets `### POST /v1/search/decathlon` (request example + Flow: `claude -p` × 1, no
  Playwright, DB write).

**Backend** (`backend/`)
- `app/offers_repository.py` — generalise the read into `get_stored_offers(company, model, source)` (`is_new` from
  the row) and expose `get_used_offers` (olx.pl, `UsedBikeResponse`) + `get_decathlon_offers` (decathlon.pl,
  `BikeOfferResponse`); `bike_exists` unchanged.
- `app/decathlon_brands.py` (new) — `DECATHLON_BRANDS` + `is_decathlon_brand(company) -> bool` (normalisation per
  decision 4) + `not_sold_info(company) -> str` (Polish `info` text).
- `app/searcher_client.py` — generic `_post_search(path, company, model)`; `search_olx` and new `search_decathlon`
  (`/v1/search/decathlon`) share the semaphore (`SEARCHER_MAX_INFLIGHT`, still 1) and the single-flight map, whose
  key now includes the path. Same exception classes.
- `app/main.py` — `/v1/bike/decathlon` → `get_decathlon_offers` (no `get_cached`/`set_cached`, no AI); new
  `POST /v1/bike/decathlon/search`: 404 `"Bike not found"` when `bike_exists` is false → 200 empty + `info` when the
  brand is not a Decathlon house brand (no searcher call) → `search_decathlon` with 503 (not configured /
  unavailable / busy, fixed strings naming "Decathlon searcher") / 502 (searcher `detail`). Never cached. Drop the
  `find_decathlon_offers` import.
- `app/schemas.py` — `BikeOfferRequest` fields get `Field(max_length=255)` (they now reach the searcher's prompt).
- **Delete** `app/bike_offer_decathlon_finder.py` and `app/prompts/bike_offer_decathlon.md`.
- `.env.example` — comment: `SEARCHER_URL`/`SEARCHER_API_KEY` also back `/v1/bike/decathlon/search`.
- `scripts/test_search.py` — replace the Decathlon AI + cache-hit tests with TC-33 (after the merge of PR #100 the
  suite is one `case_*` function per endpoint: these became `case_decathlon` and `case_decathlon_search`) (seeded `decathlon.pl` fixture:
  `is_new` true, `city` null, `photos []`, source, no generic-cache row, < 5 s), TC-34 (unknown bike → fast 200
  empty), TC-35 (`/v1/bike/decathlon/search`: unknown bike → 404; `Trek Marlin 5` → 200 `offers: []` with `info`
  naming Decathlon in < 5 s and no searcher call; live `Rockrider ST 100` when `{SEARCHER_URL}/health` answers —
  seed the `bike` row if missing and keep it — with a DB round-trip through `/v1/bike/decathlon`, else 503).
  `test_e2e_ui_db.py`: drop `/v1/bike/decathlon` from `OFFER_ENDPOINTS` if it is listed there.
- `README.md` — `### POST /v1/bike/decathlon` rewritten as a DB read (Flow: none) + new
  `### POST /v1/bike/decathlon/search` (Flow: searcher call ×1, or none for a foreign brand).

**Frontend** (`frontend/`)
- `App.tsx` — `searchDecathlon(bike)` mirroring `searchUsedBikes` (POST `/v1/bike/decathlon/search`, throws on
  non-OK with the backend `detail`, `selectedBikeRef` guard, `setDecathlonOffers` + `'loaded'`, **no** `'loading'`);
  passed to `BikeDetailsView` as `onSearchNew`.
- `BikeDetailsView.tsx` — `onSearchNew` prop → `MergedOffersSection` → the **New** `OfferCategoryCard` gets
  `onRequested={onSearchNew}` and `pendingLabel="Szukam na Decathlon…"`. `RequestDataButton` unchanged.
- `README.md` — API table + Request-data notes.

**Docs**: `CLAUDE.md`, `README.md`, `backend/README.md`, `frontend/README.md`, `searcher/README.md`;
`docker-compose.yml` / `scripts/deploy.ps1` / `Dockerfile` need **no** change (same service, `COPY app ./app`).

## Out of scope
- Allegro / Ceneo in the searcher; Decathlon photos (Playwright); TTL / refresh of stored offers; listing liveness
  checks; per-IP rate limiting (TODO-030 step 2); Notion bookkeeping (no task exists).
- A second Cloud Run service or a separate secret for Decathlon.

## Acceptance criteria
- [x] `POST /v1/bike/decathlon` makes **zero** Anthropic/CLI calls and returns the stored decathlon.pl offers (empty
      list when none; unknown bike → 200 empty). — `case_decathlon` (ex TC-33/34), TC-032-01
- [x] Clicking **Poproś o dane** in the "Nowe" card increments `bike_missing_request` (`offers_new`) **and** runs the
      Decathlon search; the card then shows a real decathlon.pl offer, `bike_offer` holds it, and reopening the bike reads
      it from the DB without any AI call. — TC-032-02/03/01 (Riverside 500, Van Rysel GRVL GRX AF); Rockrider ST 100 via
      the smoke suites (its row is stored by `test_searcher.py` TC-8 before the browser cases run)
- [x] For a non-Decathlon brand (e.g. Trek) the click ends in "Nie znaleziono ofert" in < 1 s with **no** searcher run.
      — `case_decathlon_search` foreign-brand step (ex TC-35b) 0.29 s, TC-032-04 0.53 s
- [x] `curl -H "X-Searcher-Key: …" -d '{"company":"Decathlon","model":"Rockrider ST 100"}' http://localhost:8100/v1/search/decathlon`
      returns the offer; without the header → 401. — `test_searcher.py` TC-7/8/9 (the identity the app already carries;
      a fresh `Rockrider / ST 100` row would capture the product URL, see the test plan K1)
- [x] `backend/app/bike_offer_decathlon_finder.py` and `backend/app/prompts/bike_offer_decathlon.md` no longer exist.
- [x] Smoke tests in `backend/scripts/test_search.py` (`case_decathlon`, `case_decathlon_search` — ex TC-33–35) and
      `searcher/scripts/test_searcher.py` (TC-7–9) pass.
- [x] `/manual-tester` run locally is green (`docs/testing/TODO_032/TEST_PLAN.md`, 8/8).
- [x] Docs updated (see Contract). `TODO_ISSUE_010` → `DONE_ISSUE_010` in `backlog/done/` when the PR merges.
- [x] Deployed only after the user's explicit go-ahead: `biker-searcher` new image, backend + frontend redeployed
      (`scripts/deploy.ps1 -Tag 3334dc2`, 2026-09-26), end-to-end verified on the public URLs
      (`docs/testing/TODO_032/TEST_PLAN.md` § Cloud Run: Riverside 500 empty → real decathlon.pl offer → read back from
      Cloud SQL; Trek skipped without a run). PR: https://github.com/Kamil-IT/biker/pull/99
