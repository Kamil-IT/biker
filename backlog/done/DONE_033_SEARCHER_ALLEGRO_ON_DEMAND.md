# TODO-033 — On-demand Allegro search in the searcher service (same pattern as TODO-031 / TODO-032)

**Notion:** "8. Allegro search na serverless i na callu na UI" (Praca rozwój / Plany / Plany 2026 Q4 / Zadania Q4 2026,
priority 5, blank page) — tick it when the PR merges. Reference write-ups: `docs/OLX_SEARCHER_MIGRATION.md` (TODO-031)
and `docs/DECATHLON_SEARCHER_MIGRATION.md` (TODO-032); tasks `backlog/done/DONE_031_*.md`, `backlog/done/DONE_032_*.md`.

## Goal
`POST /v1/bike/allegro` still runs one Anthropic SDK `web_search` call (API key, **no credits left → 500**) plus a
Playwright photo scrape on every uncached details view, and stores the answer as a JSON blob in the generic cache
(under the old key `/v1/bike/offer`). Do to it exactly what TODO-031 did to `/v1/bike/used` and TODO-032 to
`/v1/bike/decathlon`: the endpoint becomes a **pure DB read** of `bike_offer` rows with `source = 'allegro.pl'`
(no photos — see decision 4), and the search itself moves into the **existing** `searcher/` service as a third endpoint
(`POST /v1/search/allegro`) that runs the prompt through the Claude Code CLI (`claude -p --json-schema`,
subscription token) and writes the result into the shared database — **no photo scrape** (dropped after the probes,
decision 4). The search is triggered only by the user clicking **Poproś o dane** in the **"Nowe"** offers card — and that
click now runs **Decathlon and Allegro in parallel**.

## Decisions (interview, 2026-09-26)
1. **Same searcher service** (one image, one secret, one `claude` CLI); Allegro is its third route.
2. **Trigger = the "Nowe" card's button, both searches at once.** The click records `offers_new` via `/v1/bike/missing`
   as before and fires `POST /v1/bike/decathlon/search` **and** `POST /v1/bike/allegro/search` **concurrently**
   (`Promise.allSettled`). Rows from either search replace the button as they arrive; both empty → "Nie znaleziono
   ofert"; a search failed and neither brought rows (both failed, or one failed — e.g. 503 busy — while the other was
   empty, which for a non-Decathlon brand is always the Decathlon half) → clickable again (review finding: the first
   cut rejected only when both failed, which turned an Allegro 503 into a false "no offers" for most brands). The
   "Używane" card keeps running only OLX. An Allegro offer whose listing is used (`is_new: false`) lands in the
   "Używane" card through the existing `is_new` split, as it does today; one with no visible price is stored with
   `price: ""` and rendered as "cena w ofercie".
3. **Two searches at once, therefore two slots.** Today both sides allow one run: backend `SEARCHER_MAX_INFLIGHT=1`,
   searcher `SEARCHER_MAX_CONCURRENT=1`, Cloud Run `--concurrency 1 --max-instances 1`. New defaults: backend
   `DEFAULT_MAX_INFLIGHT = 2`, searcher `DEFAULT_MAX_CONCURRENT = 2` (local uvicorn / compose: two CLI runs in one
   process, plus a browser only for OLX), Cloud Run `--max-instances 2` with `--concurrency 1` unchanged (one CLI per
   2 GiB instance, + Chromium only for OLX; the second search gets its own instance). Nothing queues: the third concurrent search is still
   refused (backend 503 busy; the searcher's own 503, and Cloud Run's **429** when both instances are taken, are both
   mapped to `SearcherBusy`).
4. **Photos: planned to stay (interview answer P2), DROPPED after the probes.** The interview answer was "same logic,
   different transport" — move `backend/app/allegro_image_fetcher.py` (DataDome warm-up on `https://allegro.pl`, then
   the `a.allegroimg.com/(original|s\d+)/…` regex, `networkidle` + 3 s per offer) to the searcher as a non-fatal step.
   **Probes 2026-09-26** (unchanged `run_structured` + the backend's unchanged fetcher) showed allegro.pl answers
   **HTTP 403 (DataDome captcha) to every automated request** — to the CLI's `WebFetch` and to patchright Chromium
   alike, headless or headed, already on the homepage warm-up. Consequences: (a) the SDK-era prompt ("open the listing,
   open the offer page") does not work in the CLI — Trek Marlin 5 took 286 s (of the 300 s timeout) to fall back to
   search results and returned 1 offer; Kross Level 3.0 gave up after 49 s / 9 turns with `offers: []` and *"Allegro.pl
   blocks automated page fetching (HTTP 403)"*; (b) the photo scrape returned 0 photos (both modes, status 403, DataDome
   markers in the HTML) — in the probes and in every real run of the manual tests. **User's decision (2026-09-26, after
   the probes): "wywal te zdjęcia z implementacji i searcha, nie ma co marnować tokenów"** — there is nothing to gain,
   and each run wasted ~10 s and a browser launch. So the Allegro search stores **no photos by design**:
   `searcher/app/allegro_image_fetcher.py` was deleted, `allegro_finder.py` never launches a browser, `photos` is
   always `[]` (exactly like Decathlon), and Playwright runs in the searcher only for OLX. The prompt is also **not**
   byte-identical: `searcher/app/prompts/bike_offer_allegro.md` is a CLI-tuned rewrite of the same role/rules/output
   that works from **WebSearch results only** (never `WebFetch` on allegro.pl; price and condition from the result
   title/snippet; up to 3 `/oferta/` or `/produkt/` URLs — the finder drops anything else, e.g. a `/listing` search
   page; `is_new` false when the result says used, true when it says new or looks like a shop listing; a price no
   snippet shows stays `""`), validated by probes before the code shipped: Kross Level 3.0 → 3 real offers in 67 s
   (8 turns), Trek Marlin 4 → 3 real offers in 75 s (11 turns, no prices in the snippets) (see
   `docs/ALLEGRO_SEARCHER_MIGRATION.md` § 3). CLI message: `Find current offers on allegro for: {company} {model}`;
   ≤ 3 offers kept, `is_new` from the result (default `false` — an Allegro listing is used unless it says new),
   `source = 'allegro.pl'`, `city = None`, `url` must match `^https://(www\.)?allegro\.pl/(oferta|produkt)/`.
5. **No backfill.** The generic-cache rows under `/v1/bike/offer` (11 in the local Postgres, 6 of them without
   photos) are **not** migrated into `bike_offer` — they are
   weeks-old snapshots of listings that expire, and a re-click costs one subscription run, not an API call. They stay
   in the table as dead rows (nothing reads them); the `_ALLEGRO_CACHE_KEY` constant goes.
6. **Persistence and semantics identical to OLX/Decathlon**: bike found by the Python-normalised brand/model compare
   (created only by the searcher for a direct call; the backend proxy answers **404** for a bike not in `bike`),
   replace semantics scoped to `(bike_id, source='allegro.pl')`, `INSERT … ON CONFLICT (url) DO UPDATE … WHERE
   bike_id = this bike AND source = this source` (a URL already stored under another bike stays there and is not
   reported as saved), an empty result keeps the stored rows, no TTL (no photo rows for Allegro — decision 4).
7. **Order of work**: this file → probe → implement → smoke tests → `/manual-tester` locally (searcher :8102, backend
   :8002, frontend :5175, local Postgres `biker-pg`; 8001/8100/5174 are taken by stale servers) → **ask the user**
   before deploying → Cloud Run (same Cloud SQL `biker-pg`, the existing `biker-searcher` service gets the new image
   and `--max-instances 2`; backend + frontend redeployed) → `docs/ALLEGRO_SEARCHER_MIGRATION.md` → tick Notion.

## Contract

**Searcher** (`searcher/`)
- `POST /v1/search/allegro` `{company, model}` + `X-Searcher-Key` → `{offers, info, bike_id, saved}` — same auth,
  same 401/422/502/503/500 mapping as the other two routes, **same semaphore** (now `SEARCHER_MAX_CONCURRENT`
  default 2, counted across all three routes). Offers returned = the rows now stored under this bike for
  `source='allegro.pl'`.
- `app/allegro_finder.py` (new) — `find_allegro_offers(company, model) -> (offers, info)`: `run_structured` with
  `OLX_SCHEMA` (same `{info, offers[]}` shape), prompt `prompts/bike_offer_allegro.md`, `_to_offers` per decision 4
  (dedupe, column-width truncation, `photos=[]` always, `city=None`). **No photo scrape, no Playwright** — the
  fetcher was dropped by decision 4; the route is CLI-only like Decathlon. Raises `SearcherError` when the CLI fails.
- `app/main.py` — third route on `_run_search("allegro", ALLEGRO_SOURCE, find_allegro_offers, req)`; docstrings and
  the module docstring name three routes; `MAX_CONCURRENT` default 2 in `config.py` (docstring + `.env.example`).
- `app/repository.py` / `app/schemas.py` — no code change beyond docstrings (both already generic over `source`).
- `scripts/test_searcher.py` — TC-7 401 on `/v1/search/allegro` without key; TC-8 422 for a blank model (free, no CLI
  run — the suite stays free).
- `README.md` — `## Endpoints` gets `### POST /v1/search/allegro` (request example + Flow: `claude -p` × 1, DB write —
  no Playwright, no photos); `SEARCHER_MAX_CONCURRENT` row says default 2 / three routes; Cloud Run section says
  `--max-instances 2`.
- `Dockerfile` / `docker-compose.yml` — no change (`COPY app ./app`; Chromium stays for OLX only).

**Backend** (`backend/`)
- `app/offers_repository.py` — `ALLEGRO_SOURCE = "allegro.pl"`, `get_allegro_offers(company, model) ->
  BikeOfferResponse` via `_get_stored_offers` (`is_new` from the row; `photos` always `[]` — Allegro rows never get
  photo rows, decision 4).
- `app/searcher_client.py` — `SEARCH_PATHS["allegro"] = "/v1/search/allegro"`, `search_allegro()`;
  `DEFAULT_MAX_INFLIGHT = 2`; HTTP **429** from the searcher/Cloud Run treated like 503 (`SearcherBusy`). Module
  docstring: three sources, two in flight.
- `app/main.py` — `/v1/bike/allegro` → `get_allegro_offers` (no `get_cached`/`set_cached`, no AI; drop
  `_ALLEGRO_CACHE_KEY` and the `find_bike_offers` import); new `POST /v1/bike/allegro/search`: 404 `"Bike not found"`
  when `bike_exists` is false → `search_allegro` with 503 (not configured / unavailable / busy — fixed strings naming
  "Allegro searcher") / 502 (searcher `detail`). Never cached.
- **Delete** `app/bike_offer_finder.py`, `app/allegro_image_fetcher.py`, `app/prompts/bike_offer_allegro.md`
  (the finder is rewritten as `searcher/app/allegro_finder.py`, the fetcher is deleted **without a replacement** —
  decision 4 — and the prompt is rewritten in `searcher/app/prompts/`), and the dev scripts that only drove them:
  `scripts/test_offer.py` (AI smoke of `/allegro` — replaced by `case_allegro` in `test_search.py`),
  `scripts/test_offer_prompt.py` (SDK call with the moved prompt), `scripts/test_offer_images.py` +
  `app/prompts/allegro_image_extractor_prompt.md` (a standalone copy of the fetcher plus an AI dedupe prompt nothing
  else uses).
- `scripts/test_browser_slots.py` — drop the `allegro` case **and the already-dead `olx_image_fetcher` import** (that
  module left the backend in TODO-031, so `pytest` has been failing at collection on `main`); keep the bike / equipment
  photo finders. `pytest` (pytest.ini `addopts`) must pass.
- `scripts/test_search.py` — `case_allegro` (seeded `allegro.pl` fixture **without** a photo row: `is_new` true, `city`
  null, `photos == []`, source, brand/model from the `bike` row, no generic-cache row written, < 5 s; unknown bike
  → fast empty 200) and `case_allegro_search` (unknown bike → 404 only — **no paid run**; the one live searcher run of
  the suite stays `case_decathlon_search`). Header docstring + `URL` constants updated.
  `scripts/test_e2e_ui_db.py`: `OFFER_ENDPOINTS = ()` — no offer endpoint writes the generic cache any more; E6
  docstring updated accordingly.
- `.env.example` — `SEARCHER_URL`/`SEARCHER_API_KEY` comment lists all three proxies; document
  `SEARCHER_MAX_INFLIGHT` (default 2).
- `README.md` — `### POST /v1/bike/allegro` rewritten as a DB read (Flow: none) + new `### POST /v1/bike/allegro/search`
  (Flow: searcher call × 1); the `test_offer.py` row removed from the scripts table; the "Allegro — Working" status row
  and the tree listing updated.
- `app/DB_MIGRATION.md` — the sentence saying Allegro/Ceneo still use the generic cache: now only Ceneo does.

**Frontend** (`frontend/`)
- `App.tsx` — `searchAllegro(bike)` via `postOnDemandSearch<BikeOfferResponse>('/v1/bike/allegro/search', bike)` →
  `setOffers` + `setOfferState('loaded')` (no `'loading'`); `searchNew(bike)` = `Promise.allSettled([searchDecathlon,
  searchAllegro])`, rejecting only when **both** rejected (with the first `detail`); passed to `BikeDetailsView` as
  `onSearchNew`. The automatic `fetchOffer` on opening the details view still POSTs `/v1/bike/allegro` (now a fast DB
  read). Keep `App.tsx` from growing: fold the three `fetch*` offer readers into one helper if needed (≤ 500 lines is
  already broken on `main` at 651; do not add net lines beyond the new functions).
- `BikeDetailsView.tsx` — the New card's `onRequested` is offered only while **neither** `decathlonOffers` **nor**
  `offers` (Allegro) has stored rows (`hasNewSourceRows`); `pendingLabel="Szukam na Allegro i Decathlon…"`. Comments
  updated (three sources, two searches from the New card). `RequestDataButton` unchanged.
- `README.md` — API table (`/allegro` is a DB read; `/allegro/search` on-demand) + Request-data notes.

**Docs**: `CLAUDE.md`, `README.md`, `backend/README.md`, `frontend/README.md`, `searcher/README.md`,
`scripts/deploy.ps1` (`--max-instances 2` for `biker-searcher` + comment), `docker-compose.yml` (comment only).

## Out of scope
- Ceneo (stays on the generic cache + API key; the UI does not call it); backfill of the 7 cached Allegro responses;
  the "Używane" card (OLX only); TTL / refresh of stored offers; listing liveness checks; the global `url` uniqueness
  (TODO-021 item 2); the Allegro REST API (TODO-008, blocked); per-IP rate limiting (TODO-030 step 2).

## Acceptance criteria
- [x] `POST /v1/bike/allegro` makes **zero** Anthropic/CLI calls and returns the stored allegro.pl offers, always with
      `photos: []` (empty list when none stored; unknown bike → 200 empty). — `case_allegro`
- [x] Clicking **Poproś o dane** in the "Nowe" card increments `bike_missing_request` (`offers_new`) and runs the
      Decathlon **and** Allegro searches **at the same time** (two overlapping `claude CLI start` lines in the searcher
      log, no 503); the card then shows a real allegro.pl offer (no photos — by design, decision 4), `bike_offer` holds
      it (no `bike_offer_photos` rows), and reopening the bike reads it from the DB without any AI call. — `/manual-tester`
- [x] For a non-Decathlon brand (e.g. Trek) the same click runs only the Allegro search (Decathlon answers empty at
      once) and the Allegro offer lands in "Nowe" or "Używane" by its `is_new`. — `/manual-tester`
- [x] A third concurrent search (any source) is refused with 503 and the button becomes clickable again. — `/manual-tester`
- [x] `curl -H "X-Searcher-Key: …" -d '{"company":"Trek","model":"Marlin 5"}' http://localhost:8102/v1/search/allegro`
      returns the offer(s); without the header → 401. — `test_searcher.py` TC-7/8 (401/422 only) + manual run
- [x] `backend/app/bike_offer_finder.py`, `backend/app/allegro_image_fetcher.py` and
      `backend/app/prompts/bike_offer_allegro.md` no longer exist; `pytest` in `backend/` passes.
- [x] Smoke tests `backend/scripts/test_search.py` (`case_allegro`, `case_allegro_search`) and
      `searcher/scripts/test_searcher.py` pass.
- [x] `/manual-tester` run locally is green (9/9, two rounds) (`docs/testing/TODO_033/TEST_PLAN.md`).
- [x] Docs updated (see Contract). Notion task 8 ticked when the PR merges.
- [ ] Deployed only after the user's explicit go-ahead: `biker-searcher` new image + `--max-instances 2`, backend +
      frontend redeployed, end-to-end verified on the public URLs.
