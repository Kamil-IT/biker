# Biker — AI Bike Finder

AI-powered bike finder. Describe what you're looking for in plain English and get matched to real bike models instantly.

## How it works

Before the first search the home page shows **Najpopularniejsze rowery** — the curated popular bikes (`GET /v1/bike/popular`) as result-style cards with their expert rating in points ("8.4 / 10", from one `POST /v1/bike/review` per bike; "Brak oceny" without one) and a short description; click one to jump straight to its details page (step 4). The section disappears while a search runs or shows results and returns after "Nowe wyszukiwanie".

1. You enter a free-text description (e.g. *"comfortable bike for daily 10 km city commute"*)
2. The backend first searches its own bike database: every structured filter it can check (brand, model, wheel size, frame size, electric) is matched against stored bike specs. All matching bikes are returned (no cap) with no AI call. Search answers are never served from a response cache, so they always reflect the current database
3. Only when the database has no match, a single Claude Haiku call recommends every real bike that fits (at least 1 — the closest match when nothing meets every filter)
4. Click a result to open the details page — the backend fetches specs and description in parallel via Claude web search, and the expert review is read from the database; the photos, review, Allegro offers, Decathlon offers and used OLX listings are read from the database only (they get there through the on-demand searches below — opening a bike never runs a marketplace or photo search). Any section (photos, overview, specs, review, Used / New offers) still without data after 5 s — or with an empty/failed response — shows a **Request data** button instead of its spinner; clicking it records the request via `POST /v1/bike/missing`. Data that arrives later replaces the button
5. In the **Recenzja eksperta** section the button also starts the on-demand review search (`POST /v1/bike/review/search` → the same `searcher/` service runs the Claude Code CLI once over the curated review sites, computes the weighted rating and stores it in `bike_review` / `bike_review_source` — only when it found at least one professional source; a stored review is never wiped by a bad run); it reads "Szukam recenzji…" while it runs, then the review replaces it — or "Nie znaleziono recenzji".
   In the photo gallery slot the button also starts the on-demand photo search (`POST /v1/bike/photos/search` → the same `searcher/` service finds the manufacturer's product page with the Claude Code CLI, scrapes up to 8 photos from it with Playwright and stores them in `bike_detail_photos` — only for a bike that has none, stored photos are never replaced); it reads "Szukam zdjęć…" while it runs, then the gallery replaces it — or "Nie znaleziono zdjęć". In the **Used** offers card that same button also starts the on-demand OLX search (`POST /v1/bike/used/search` → the `searcher/` service, which runs the Claude Code CLI on your subscription and stores what it finds in `bike_offer`). The button reads "Szukam na OLX…" while it runs, then the real listings with photos replace it — or "Nie znaleziono ofert" when there are none. In the **New** card it fires **two** searches at once — Decathlon (`POST /v1/bike/decathlon/search`) and Allegro (`POST /v1/bike/allegro/search`) — through the same searcher; neither stores photos (Allegro blocks every automated fetch with 403, so its photo scrape was dropped); the button reads "Szukam na Allegro i Decathlon…" and rows from either source replace it as they arrive ("Nie znaleziono ofert" only when both came back empty; clickable again when a search failed and neither brought rows). Allegro is searched for every brand, and a used Allegro listing lands in the **Used** card by its `is_new` flag; Decathlon only for its house brands (Rockrider, Btwin, Triban, Van Rysel, Elops, Riverside, Stilus, Tilt; `backend/app/decathlon_brands.py`) — any other brand gets an instant empty Decathlon answer with no search spent (closes `TODO_ISSUE_010`)
6. Click any component name in a bike's spec sheet (e.g. a derailleur, fork, or saddle) to open the **equipment** page for that item — an overview, component-tree spec sheet, photos, and an expert review for gear (helmets, lights, locks, apparel). Equipment is informational only — no shopping/offer links

## Running the project

You need **Docker** for the database and **three terminals** — backend, frontend and the searcher run separately. The
searcher (Terminal 3) is part of the normal local stack: without it the app still works, but every **Poproś o dane**
search (review, photos, OLX, Decathlon, Allegro) answers 503. The `app-runner` agent starts all four (database, backend,
searcher, frontend) for you.

### Step 0 — Database (PostgreSQL in Docker)

```bash
# first time — creates the container and a persistent volume
docker run -d --name biker-pg -e POSTGRES_USER=biker -e POSTGRES_PASSWORD=biker -e POSTGRES_DB=biker -p 5432:5432 -v biker-pgdata:/var/lib/postgresql/data postgres:17
# every later time
docker start biker-pg
# check it is up
docker exec biker-pg pg_isready -U biker -d biker
```

The backend connects to it when `DATABASE_URL=postgresql+psycopg://biker:biker@localhost:5432/biker` is set
(TODO-028). Without `DATABASE_URL` it falls back to the SQLite file `backend/cache.db`.

### Terminal 1 — Backend

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
pip install -U anthropic        # existing venv: keep the SDK as new as the Docker image's (unpinned on purpose)
copy .env.example .env          # edit .env and set your ANTHROPIC_API_KEY
python scripts/migrate_photos_bike_id.py --dry-run   # once per existing database: report what would change ...
python scripts/migrate_photos_bike_id.py             # ... then re-key bike_detail_photos to bike_id (idempotent)
uvicorn app.main:app --reload --port 8000
```

> **Run `migrate_photos_bike_id.py` once on every existing database** (SQLite `cache.db` or PostgreSQL, `--url` / `--db`
> pick another one). Bike photos now hang off `bike.id` instead of the details row, and `create_all()` never alters an
> existing table. Until it has run, `POST /v1/bike/photos` answers `{"photos": []}` (ERROR in the log) and the searcher
> refuses to start. On production Cloud SQL run it **before** deploying the new backend and searcher. Details:
> `backend/app/DB_MIGRATION.md`.
>
> **Also run `copy_review_cache_to_table.py` once per database** (TODO-037; `--dry-run` first, idempotent): bike reviews are no longer
> a JSON blob in the generic cache but rows in `bike_review` / `bike_review_source` (created by the backend's `init_db()`), and the
> script carries the old cached reviews over. Until it has run, stored reviews are simply missing (the Review section shows its
> "Request data" button). The searcher refuses to start without the two tables. On production Cloud SQL: backend `init_db()` creates the
> tables, run the script, then deploy searcher and backend.

### Terminal 2 — Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

> The frontend proxies `/v1/*` to the backend automatically — no CORS config needed.

### Terminal 3 — OLX / Decathlon / Allegro / photos / review searcher (TODO-031 / TODO-032 / TODO-033 / TODO-035 / TODO-037)

The used-bike search on OLX, the new-bike search on decathlon.pl, the Allegro offer search and the bike photo search run in their own service so
they only spend tokens when a user asks for them — and they spend them from the **Claude Code subscription**
(`claude -p`), not from `ANTHROPIC_API_KEY`. Log the CLI in once (`claude`), then:

```bash
cd searcher
copy .env.example .env          # DATABASE_URL (same Postgres as the backend) + SEARCHER_API_KEY
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8100
```

Check it is up: `curl http://127.0.0.1:8100/health` → `{"status":"ok",...}` (the log prints `searcher ready`). In a git worktree
use the worktree's port (8101, 8102, …) and set the same port in that worktree's `backend/.env` `SEARCHER_URL`.

`backend/.env` needs the matching `SEARCHER_URL=http://localhost:8100` and `SEARCHER_API_KEY`. Without the searcher the
app still works — the Used and New cards' and the photo gallery's **Poproś o dane** buttons just get a 503 and stay clickable. Try it by hand:

```bash
curl -X POST http://localhost:8100/v1/search/olx -H "X-Searcher-Key: dev-local-searcher-key" -H "Content-Type: application/json" -d "{\"company\":\"Trek\",\"model\":\"Marlin 5\"}"
curl -X POST http://localhost:8100/v1/search/decathlon -H "X-Searcher-Key: dev-local-searcher-key" -H "Content-Type: application/json" -d "{\"company\":\"Rockrider\",\"model\":\"ST 100\"}"
curl -X POST http://localhost:8100/v1/search/allegro -H "X-Searcher-Key: dev-local-searcher-key" -H "Content-Type: application/json" -d "{\"company\":\"Trek\",\"model\":\"Marlin 5\"}"
curl -X POST http://localhost:8100/v1/search/review -H "X-Searcher-Key: dev-local-searcher-key" -H "Content-Type: application/json" -d "{\"company\":\"Canyon\",\"model\":\"Grizl CF 7 ESC\"}"
curl -X POST http://localhost:8100/v1/search/photos -H "X-Searcher-Key: dev-local-searcher-key" -H "Content-Type: application/json" -d "{\"company\":\"Trek\",\"model\":\"Marlin 5\"}"
```

In docker compose one searcher container gets all 10 slots (browsers stay capped at 2 per process, so RAM is the limit — lower `SEARCHER_MAX_CONCURRENT` in `searcher/.env` if needed).
The five routes share `SEARCHER_MAX_CONCURRENT` busy slots (default 10, was 2 — the New card fires Decathlon and Allegro
together and a details page can add OLX and photos); an eleventh concurrent call answers 503 `searcher busy` while the
others run, nothing queues. When the Claude subscription limit is used up, every search route answers **400**
`{"detail": "<the CLI's notice, e.g. You've hit your session limit · resets …>"}` and the backend's `/v1/bike/*/search`
relays it as the same 400 — the shape of the Anthropic credit-balance 400 (TODO-038). Browser launches are capped separately (`BROWSER_MAX_CONCURRENCY`, default 2 per process).
Only OLX and the photo search use Playwright (OLX listing photos, the manufacturer page for bike photos); the Decathlon and
Allegro searches store no photos. A photos request for a bike that already has photos is answered from the database
without a CLI run, and stored photos are never replaced. Allegro answers 403 to every
automated fetch (the CLI's WebFetch and Chromium alike), so its prompt works from web-search results alone (an offer may
come back with an empty price) — 3 offers in 67–75 s in the 2026-09-26 probes — and the Allegro gallery scrape that
shipped with the first cut was removed after those probes returned 0 photos from it: nothing to gain, ~10 s and a
browser launch per run wasted.

## Run with Docker (whole stack)

`docker-compose.yml` runs backend + frontend against **Cloud SQL on GCP** (`biker-pg`) through a `cloud-sql-proxy`
sidecar. Needs, all outside git: `backend/.env` with `ANTHROPIC_API_KEY` and `SEARCHER_API_KEY`, `searcher/.env` with the same `SEARCHER_API_KEY` plus `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token` — the container has no interactive login), `backend/gcp-prod-pgpass.conf` (libpq pgpass line
with the Cloud SQL password, gitignored) and gcloud Application Default Credentials (`gcloud auth application-default login`,
once; another file can be given with `GCLOUD_ADC_FILE`).

```bash
docker compose up --build -d          # → http://localhost:8080
docker compose down
docker compose --profile local-db up -d db   # the old local Postgres (5433, volume pgdata) — no longer used by the backend
```

| Service | Image | Port | Notes |
|---|---|---|---|
| `cloudsql-proxy` | `cloud-sql-proxy:2.25.4` | — | connects to `biker-engine-prod:europe-central2:biker-pg` with the ADC file, serves Postgres on `cloudsql-proxy:5432` inside the compose network |
| `backend` | `backend/Dockerfile` | 8000 | Python 3.14 + patchright Chromium, `PLAYWRIGHT_HEADLESS=true`, listens on `$PORT` (Cloud Run), non-root, no secrets baked in; the pgpass file is mounted read-only and copied to a `600` file on start |
| `frontend` | `frontend/Dockerfile` | 8080 | `npm run build` served by nginx; `nginx.conf.template` proxies `/v1/*` to `BACKEND_URL` (default `http://backend:8000`, 660 s timeout — a margin over the backend's 600 s searcher wait) |
| `searcher` | `searcher/Dockerfile` | 8100 | Python 3.14 + Node 24 + `@anthropic-ai/claude-code` (pinned) + patchright Chromium (used by the OLX and bike photo scrapes); runs `claude -p` with `CLAUDE_CODE_OAUTH_TOKEN` for the OLX, Decathlon, Allegro and photo searches (ten at once by default), writes `bike_offer` / `bike_detail_photos` into the same database (same pgpass mount); the backend reaches it as `SEARCHER_URL=http://searcher:8100` |
| `db` | `postgres:17` | 5433 → 5432 | profile `local-db` only; named volume `pgdata` |

## Deploy to GCP (Cloud Run)

The same two images run as two Cloud Run services in `europe-central2` (project `biker-engine-prod`): `biker-backend`
(Cloud SQL `biker-pg` over the `/cloudsql/…` unix socket) and `biker-frontend` (nginx with `BACKEND_URL` set to the
backend's `run.app` URL, so the browser only ever talks to the frontend origin — no CORS). Secrets never leave Secret
Manager: `anthropic-api-key` → `ANTHROPIC_API_KEY`, `db-password` → `PGPASSWORD` (libpq reads it; `DATABASE_URL` carries
no password). This is TODO-030 step 1; the per-IP rate limit, budget alerts and `docs/DEPLOYMENT.md` follow in step 2.

TODO-031 adds a third service, `biker-searcher` (the on-demand OLX searcher; TODO-032 adds the Decathlon search and
TODO-033 the Allegro search to the **same** service — same image and secrets, no new service): same Cloud SQL socket,
`--concurrency 1` (one CLI run per instance, plus Chromium for OLX and photos), 2 vCPU / 2 GiB, timeout 900 s, `max-instances 10` since
TODO-035 (was 2) — the New card fires the Decathlon and Allegro searches together and a details page can add OLX and photos, so
each search gets its own instance; an eleventh concurrent search gets Cloud Run's 429, which the backend reports as 503 busy — scale to zero; secrets `searcher-api-key` → `SEARCHER_API_KEY`,
`claude-code-oauth-token` → `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`), `db-password` → `PGPASSWORD`. The backend
service gets `SEARCHER_URL` (the searcher's `run.app` URL) and `SEARCHER_API_KEY` from the same secret. Like the other two,
the searcher needs the one-time `roles/run.invoker` for `allUsers` (it is protected by the shared secret, and the backend
calls it over the public URL). TODO-035 adds the photo route and TODO-037 the review route to the same service (no new service or secret). **TODO-037 deploy order:** `scripts/deploy.ps1` deploys the searcher first, and the new searcher refuses to start until `bike_review` / `bike_review_source` exist. So **before any deploy** run `backend/scripts/copy_review_cache_to_table.py` against Cloud SQL through the proxy (`--dry-run` first; it creates the tables via `init_db()` and copies the reviews), or deploy `-Only backend` first.

> **Deploy order — data safety.** Run `backend/scripts/migrate_photos_bike_id.py` against Cloud SQL **before** the new backend or searcher runs against it:
> (1) migrate Cloud SQL, (2) deploy backend and searcher together right after (`.\scripts\deploy.ps1`, searcher → backend), (3) deploy the frontend.
> The new searcher refuses to start on an unmigrated database (Cloud Run keeps serving the old revision) and the new backend returns empty photos
> until the migration has run; once it has run, the **old** backend breaks on that database (it still writes `bike_detail_id`), so expect a short window
> between steps 1 and 2 in which the old backend's details save fails (it rolls back and logs a warning; no data is lost). The new `save_bike_details` updates
> the details row in place, so it can never cascade-delete photos through the old foreign key.

Capacity: up to 10 searcher instances and 2 backend instances each hold their own SQLAlchemy pool (default 5 + 10 overflow) against Cloud SQL, whose
`max_connections` has not been checked (the tier is "smallest shared-core instance" per `TODO_030`; the deploy script sets no tier). There is no per-IP rate limit on the
search triggers yet (the planned "Step 2"): with the limit at 10, anyone can start up to 10 parallel subscription runs via `POST /v1/bike/photos/search`.


```powershell
.\scripts\deploy.ps1                 # docker build + push (Artifact Registry repo biker) + gcloud run deploy, both services
.\scripts\deploy.ps1 -Only backend   # or -Only frontend / -Only searcher; -Tag v1 overrides the git-sha image tag
```

One-time setup the script assumes (done by hand, 2026-09-25): APIs `run`, `artifactregistry`, `secretmanager`, `sqladmin`;
Artifact Registry repo `biker` (Docker, `europe-central2`); service account `biker-run` with `roles/cloudsql.client` and
`roles/secretmanager.secretAccessor` on the two secrets; `gcloud auth configure-docker europe-central2-docker.pkg.dev`.
Who may call the services is a separate, one-time IAM decision made after the first deploy (`roles/run.invoker` for
`allUsers` on both services — the app is public by design, TODO-030); the script never touches IAM, so that binding survives
every redeploy and a brand-new service starts closed.

Sizing (cost cap on the Free Trial): backend 2 vCPU / 2 GiB (Chromium), frontend 1 vCPU / 256 MiB, both `min-instances 0`,
`max-instances 2`, request timeout 600 s (`/v1/bike/details` takes minutes). The backend caps simultaneous browser launches
at `BROWSER_MAX_CONCURRENCY=2` (each ≈ 0.5–0.9 GiB; only the equipment photo scraper remains in the backend — the
OLX and bike photo scrapers live in the searcher, and Allegro / Decathlon offers carry no photos), so a burst of uncached details requests queues for a browser
instead of exceeding the 2 GiB and getting the instance killed; raise it only together with `--memory`.

## Bike discovery (local)

TODO-036 (layout split in TODO-039): the catalogue can fill itself from a shop listing instead of from user searches. Everything lives in
`webscraper/centrumrowerowe/` and runs by hand on your machine — **no AI call** (page parsing only), no endpoint, no
searcher route, and `backend/app/**` is not modified (the scripts import it). Nothing runs on GCP by itself: the only
thing there is a one-off **copy** of the queue and the parsed bikes, made with `copy_to_db.py` (see below). Three steps:

1. **Scrape** the centrumrowerowe.pl listing (`https://www.centrumrowerowe.pl/rowery/`, all `?page=N`; each page is
   tried twice, a page that fails both times is skipped with a warning). The ~2044 listing rows are colour/size
   variants; they collapse to one product per `pd…` ID. Only `https://(www.)centrumrowerowe.pl` links with a `pd…` ID
   are queued; anything else is counted as "skipped (bad url)".
2. **Queue** (TODO-039) — each product is upserted as a **listing** (`bike_discovery_listing`, one product in one shop) and
   linked to its **bike** (`bike_discovery`, the bike and its processing state, identified by normalised company +
   model). A new listing goes to the bike with the same normalised name, and a missing bike is inserted as `pending`;
   one bike can therefore have many listings (other colour pages, other shops). Re-scraping refreshes only the
   listing's name, link, price and `last_seen_at`: it never touches a bike that exists (`status`, `attempts`, `bike_id`,
   `company`, `model`, `bike_type`) and a known listing never changes bike.
3. **Process** — `process_queue.py` claims a batch, fetches each product page, parses it (JSON-LD, the "Specyfikacja"
   table, the variant selector, the photo gallery) and stores `bike` + `bike_detail` + components through the backend's
   `repository.save_bike_details`, so the bike shows up in DB-first search without an Anthropic call. Three more
   things are handled by the shared module `bike_store.py`, each because a different backend reader needs it:
   - **Details cache** — the frontend's details view calls `POST /v1/bike/details`, which reads only the generic cache and
     never `bike_detail`, so after a verified save the processor also writes the generic-cache entry `/v1/bike/details`
     `{company, model}` (the bike's stored casing; an existing entry — e.g. AI-made — is kept, first write wins; a cache
     failure only logs a WARNING and does not fail the row).
   - **Photos** — `BikeDetailsResponse` has no photos since PR #115. The parsed shop photos (up to 8, http/https) are stored
     per bike through the backend's `photos_repository.save_bike_photos` (table `bike_detail_photos`, keyed by
     `bike_id`), **only when the bike has none**; a failure is a WARNING and the row stays `done`. The details view reads
     them through `POST /v1/bike/photos`. Photos are also stored for a bike whose details were kept (`skipped`) if it has none.
   - **Never overwrite** — a bike that already has *any* `bike_detail` row is kept as is (upstream has no details TTL any
     more), whoever wrote it.

```powershell
backend\.venv\Scripts\python.exe -m pip install -r webscraper\centrumrowerowe\requirements.txt   # first time: beautifulsoup4 + pytest
$env:PYTHONUTF8 = "1"
cd webscraper\centrumrowerowe
..\..\backend\.venv\Scripts\python.exe scrape_rowery.py --dry-run          # counts only, no DB
..\..\backend\.venv\Scripts\python.exe scrape_rowery.py                    # upsert into bike_discovery
..\..\backend\.venv\Scripts\python.exe process_queue.py --limit 20         # process 20 due rows
```

| Script | Flag | Default | Meaning |
|---|---|---|---|
| `scrape_rowery.py` | `--csv` | off | also write `rowery.csv` (one row per listing entry, `;`-separated) |
| | `--dry-run` | off | fetch the listing and print counts only; nothing is written to the DB |
| | `--max-pages N` | all | stop after N listing pages (testing) |
| | `--allow-remote` | off | permit a non-local database (see **Database**) |
| `process_queue.py` | `--limit N` | 20 | bikes to claim in this run (≥ 1) |
| | `--delay S` | 1.0 | seconds between page fetches (≥ 0) |
| | `--source NAME` | all | only bikes that have a listing from this shop, e.g. `centrumrowerowe.pl` (also under `--retry-failed`, `--sync-cache`, `--dry-run`) |
| | `--retry-failed` | off | put every `failed` row back to `pending` first, exhausted ones too (attempts reset to 0) |
| | `--dry-run` | off | fetch + parse + print the bikes a real run would claim (each listing tried, stopping at the first page that parses); claims and writes nothing (prints the target instead of refusing a remote one). With `--sync-cache` it counts what would be written |
| | `--sync-cache` | off | no fetching, no claiming: for every bike of a `done` row (`--source` respected) copy its stored details into the generic `/v1/bike/details` cache unless an entry exists; prints `cache sync: written=… already present=… missing details=… failed=…` (missing = the bike has no details row). Use it for rows processed before the cache write existed; a second run writes 0 |
| | `--allow-remote` | off | permit a non-local database (see **Database**) |

The scraper prints `listing rows / products seen / skipped (bad url)` and then `target database`, `products seen /
bikes inserted / listings inserted / listings updated`; the processor logs `database: …` and ends with `done=… skipped=… failed=…` (plus `lost=…` when a
lease was taken over).

**Tables** (created on first use by the scripts via `ensure_table()`, which refuses — with a message to run the
migration — a database whose `bike_discovery` still has the old TODO-036 layout; scraper, processor and copy script all
stop the same way):

- `bike_discovery` = the bike and its processing state: `id`, `company`, `model`, `company_norm`, `model_norm`
  (`strip().lower()` in Python, `UNIQUE` together as `uq_bike_discovery_identity`), `bike_type`, `bike_id` (FK →
  `bike.id`, `ON DELETE SET NULL`), `status`, `attempts`, `last_error`, `locked_at`, `next_attempt_at`, `created_at`,
  `updated_at`; index `(status, next_attempt_at)`. `bike_id IS NOT NULL` means the bike exists in `bike`;
  `status = 'done'` means it has full `bike_detail` data.
- `bike_discovery_listing` = one product in one shop: `id`, `discovery_id` (FK → `bike_discovery.id`, `ON DELETE
  CASCADE`, `NOT NULL`), `source` (`centrumrowerowe.pl`), `source_product_id` (`pd27404`; `UNIQUE` with `source`),
  `raw_name`, `details_link` (URL without `?v_Id=`), `price` (lowest seen among the variants), `first_seen_at`,
  `last_seen_at`, `updated_at`, `fetched_at` (last attempt to fetch this page), `fetch_error` (its error, `NULL` after a
  fetch that parsed); indexes `(discovery_id)` and `(source, last_seen_at)`.

**Status lifecycle:**

| Status | Meaning |
|---|---|
| `pending` | queued by the scraper, not tried yet |
| `in_progress` | claimed by a processor (`locked_at` set, `attempts` +1); the lease is refreshed when work on each row starts. Lease of **15 min**: an older `in_progress` row is claimable again; one that already used its 3rd attempt becomes `failed` ("lease expired on the last attempt") |
| `done` | parsed and stored; `bike_id` set, `company`/`model` set to the bike's stored brand/model. A save counts only when the bike's `bike_detail.updated_at` is at or after the save start (`save_bike_details` swallows errors, and an older row would otherwise look like success) |
| `failed` | fetch/parse/save error, `last_error` filled. Retried after a backoff of **1 h, then 6 h** (`next_attempt_at`; the 24 h step is only reached with a higher attempt limit); the **3rd** failure is final until `--retry-failed` |
| `skipped` | HTTP 404/410 (product gone), or the bike already has a `bike_detail` row (any age) — nothing is overwritten, AI-collected or earlier data wins; its photos are still stored if it has none |

**Listings per bike (processor):** the claim, lease and backoff work per bike. For each claimed bike the listings are
tried newest `last_seen_at` first, each with the parser registered for its shop (`PARSERS`; only `centrumrowerowe.pl`
so far, URL allowlist unchanged) — the first page that parses wins and storing (details, photos, cache, stored casing)
is as before. Every attempt is recorded on its listing (`fetched_at`, `fetch_error`). The bike is `failed` only when
every listing failed (`last_error` = `pid: error; …` when there are several), `skipped` when every listing is 404/410, and
`failed` at once for a store error, a listing of a shop without a parser (`UnknownSource`) or a bike with no listings
("bike has no listings — nothing to fetch"). The stored casing is written to `company`/`model` unless another
`bike_discovery` row already has that normalised identity — then the row keeps its name.

Outcome `lost` (not a stored status): another run took the row's lease over, so this run writes nothing for it.
Ctrl+C hands claimed-but-unprocessed rows back as `pending` without counting the attempt. On PostgreSQL rows are claimed
with `FOR UPDATE SKIP LOCKED`, so two processors never take the same row.

**Fetch safety:** the URL allowlist (https, host `centrumrowerowe.pl` / `www.centrumrowerowe.pl`, default port) is
checked when the scraper upserts and again before every page fetch; redirects are followed by hand (max 3) and each hop is
checked too. Photo URLs kept from a page must be http/https.

**Database:** the scripts read `DATABASE_URL` / `PGPASSFILE` from `backend/.env` (variables already set in the
environment win), i.e. the **local `biker-pg`** container when that is what `.env` points at (`docker start biker-pg`).
Both scripts print the target with the password masked and **refuse any non-local database** — local means SQLite, or a
`localhost` / `127.0.0.1` / `::1` host on a port other than 6543; port 6543 (the Cloud SQL proxy) and `/cloudsql` sockets count
as remote — unless `--allow-remote` is passed. Never point them at the production Cloud SQL without an explicit decision.

**Copy to another database — `copy_to_db.py`** (puts the local result on GCP Cloud SQL without re-fetching a single shop
page; done once on 2026-09-30 at the user's explicit request). Two phases: (1) the source — the `DATABASE_URL` from
`backend/.env` unless `--source-url` — is read completely into memory (queue rows + details and photos of each
`done`/`skipped` row's bike) and closed; (2) the target is written: each bike's details through the same verified save as
the processor (`bike_store.store_details`), its photos (only when the target bike has none), the `/v1/bike/details` cache
entry, then every `bike_discovery` row matched by `(company_norm, model_norm)` and its listings by `(source,
source_product_id)`. A listing already in the target stays on its bike there.

- **Never downgrade**: details already in the target are kept and only linked; a queue row that is already `done` /
  `skipped` / `in_progress` in the target stays as it is; only a target `pending`/`failed` row is promoted to the source's
  `done`/`skipped`. `bike_id` is the **target's** bike id (found by normalised brand + model, the stored casing reused),
  never the source's; `locked_at` is dropped; a source `in_progress` row arrives as `pending` (attempts 0), and a
  `done`/`skipped` row whose bike could not be written arrives as `pending` so the processor fetches it.
- **Idempotent**: a second run changes nothing (rows unchanged, details kept, cache and photos present).
- **Refuses** a target that is the same database as the source, and a non-local target without `--allow-remote`
  (a `--dry-run` only prints the target and reports what would change, writing nothing). The password is never in the URL:
  it comes from `PGPASSFILE` / `PGPASSWORD`.

| Flag | Default | Meaning |
|---|---|---|
| `--target-url URL` | required | SQLAlchemy URL of the database to write, e.g. `postgresql+psycopg://user@127.0.0.1:6543/biker` (no password) |
| `--source-url URL` | `DATABASE_URL` of `backend/.env` | database to read |
| `--source NAME` | all | only bikes listed by this shop (and only that shop's listings), e.g. `centrumrowerowe.pl` |
| `--limit N` | all | copy at most N bikes (queue rows) (>= 1) |
| `--dry-run` | off | report what would change; write nothing |
| `--allow-remote` | off | required when the target is not a local database |

It prints `source:` / `target:` (password masked), `read N queue rows, M bikes (… with details, … with photos)` and a
counter line (`rows_inserted`, `rows_updated`, `rows_unchanged`, `rows_failed`, `listings_inserted`,
`listings_unchanged`, `bikes_written`, `bikes_kept`, `bikes_failed`, `cache_*`, `photos_*`).

```powershell
# Terminal 1: the Cloud SQL proxy on the host port the guard treats as remote (gcloud login / ADC needed)
cloud-sql-proxy --gcloud-auth --port 6543 biker-engine-prod:europe-central2:biker-pg
# Terminal 2: PGPASSFILE = the gitignored pgpass file of the Cloud SQL user (never put the password in the URL)
$env:PYTHONUTF8 = "1"; $env:PGPASSFILE = "<path to the pgpass file>"
cd webscraper\centrumrowerowe
..\..\backend\.venv\Scripts\python.exe copy_to_db.py --target-url "postgresql+psycopg://<user>@127.0.0.1:6543/<db>" --allow-remote --dry-run
..\..\backend\.venv\Scripts\python.exe copy_to_db.py --target-url "postgresql+psycopg://<user>@127.0.0.1:6543/<db>" --allow-remote
```

State on GCP after the 2026-09-30 copy: the queue holds 1304 rows (49 `done`, 1 `skipped`, 1254 `pending`) and 49 bikes with
details, photos and cache entries — migrated to the two-table layout (TODO-039) on 2026-09-30 evening by the user, so no further step is needed before
the scripts touch it (the migration is described below). Nothing there
runs by itself — processing the remaining 1254 rows would be a manual `process_queue.py --allow-remote` run against the proxy,
only on an explicit decision.

**Migration to the two-table layout — `migrate_discovery_listings.py`** (TODO-039). Run it **once on every existing
database before any other script** (local `biker-pg` first; GCP only on the user's explicit go). It moves each old row's
shop columns (`source`, `source_product_id`, `raw_name`, `details_link`, `price`, `first_seen_at`, `last_seen_at`) into one
listing linked to that row, fills the norms, and merges rows that share a normalised identity: the survivor has the
highest status (`done` > `skipped` > `failed` > `in_progress` > `pending`, ties → lowest id), gets every listing, and keeps
its `bike_id` or takes the first one a merged row had. It then drops the moved columns and the old `UNIQUE(source,
source_product_id)` and adds the new constraint and indexes. One transaction, verified before commit (listing count = old row
count, every listing linked, no bike lost its `bike_id`); any mismatch rolls back with exit code 1. SQLite rebuilds the
table, PostgreSQL alters it in place under an `ACCESS EXCLUSIVE` lock. Idempotent: a second run prints "already migrated".
Summary: `old_rows`, `bikes`, `listings`, `merged_groups`, `merged_rows`, `bike_id_conflicts` (a WARNING when > 0).

| Flag | Meaning |
|---|---|
| `--url URL` | SQLAlchemy URL to migrate (default `DATABASE_URL` of `backend/.env`) |
| `--dry-run` | migrate, verify and report, then roll back |
| `--allow-remote` | required for a non-local database — **also with `--dry-run`**, because it runs the DDL and takes the table lock before rolling back |

Run on the local PostgreSQL `biker-pg` on 2026-09-30 (rehearsed first on a PostgreSQL copy of the real table): `old_rows=1310 bikes=1278 listings=1310 merged_groups=30 merged_rows=32 bike_id_conflicts=0` - the merged groups are men's/women's variants of the same model name (e.g. "Rower crossowy ROMET Orkan 5 CS" + "... damski ..."); a second run printed "already migrated". Run on GCP Cloud SQL the same evening (through the proxy, `--allow-remote`, started by the user by hand): identical numbers (1310 → 1278 bikes, 1310 listings, 49 done / 1 skipped / 1228 pending, 50 `bike_id` kept), second run "already migrated". After the migration, on `biker-pg` (2026-09-30): a full re-scrape saw 1311 products and inserted 7 bikes + 7 listings (new `pd` ids in the catalogue; 6 old ones were not seen) and updated 1304 listings; `process_queue.py --limit 5` gave `done=5 skipped=0 failed=0`; 194 unit tests pass.

**Tests** (fixtures are saved product pages in `webscraper/centrumrowerowe/tests/fixtures/`; every test uses a throwaway
SQLite file, never the real database; 194 pass on 2026-09-30):

```powershell
$env:PYTHONUTF8 = "1"
cd webscraper\centrumrowerowe
..\..\backend\.venv\Scripts\python.exe -m pytest tests -q
```

Manual test plan and results (13 of 13 cases pass in round 3, after the merge of PR #115; photos asserted through
`POST /v1/bike/photos`): `docs/testing/TODO_036/TEST_PLAN.md`.

## Other useful commands

| Command | What it does |
|---|---|
| `cd backend && python scripts/test_search.py` | Smoke-test `POST /v1/bike/search` (+ `/v1/bike/missing`, `/v1/bike/popular`, `/v1/bike/used/olx`, `/v1/bike/used/search`, `/v1/bike/decathlon`, `/v1/bike/decathlon/search`, `/v1/bike/allegro`, `/v1/bike/allegro/search`, `/v1/bike/photos`, `/v1/bike/photos/search`) |
| `cd backend && python scripts/seed_popular_bikes.py` | Fill `bike_popular` — the home page's "Najpopularniejsze rowery" served by `GET /v1/bike/popular` (TODO-034) — with 3 bikes that have details, photos and a stored review (`bike_review`) with a real rating; `--dry-run`, `--count N`, repeatable `--bike "Brand\|Model"`; replaces the table contents |
| `cd searcher && python scripts/test_searcher.py` | Smoke-test the searcher (`/health`, 401/422 on all five search routes and a stored-photos answer from the DB — free, no CLI run; the single paid live run lives in `backend/scripts/test_search.py` `case_decathlon_search`) |
| `cd backend && python scripts/test_details.py` | Smoke-test `POST /v1/bike/details` |
| `cd backend && python scripts/copy_review_cache_to_table.py` | One-off (TODO-037): copy the old generic-cache bike reviews into `bike_review` / `bike_review_source`; `--dry-run`, `--force`, `--db` / `--url`; idempotent |
| `cd backend && python scripts/test_equipment.py` | Smoke-test `POST /v1/equipment/details` + `/v1/equipment/review` |
| `cd backend && pytest` | Unit tests (no API key): stored reviews + cache copy, browser-launch cap, searcher client photo and review routes (the review aggregation tests live in `searcher/`) |
| `cd frontend && npm run build` | TypeScript check + production bundle → `dist/` |
| `cd frontend && npm run preview` | Serve the production bundle locally |
| http://localhost:8000/docs | Interactive OpenAPI UI for the backend |

## Marketplace integrations

| Marketplace | Status | Notes |
|---|---|---|
| Allegro | **Working (on demand)** | Offers found by the same `searcher/` service — Claude Code CLI web search (`bike_offer_allegro.md`, subscription token), no photos (allegro.pl answers 403 to every automated fetch, so the Playwright gallery scrape was dropped after the probes returned nothing) — stored in `bike_offer` (`source = 'allegro.pl'`, `is_new` as the listing said); triggered by the New card's **Poproś o dane** button (together with the Decathlon search) or `curl :8100/v1/search/allegro`. `POST /v1/bike/allegro` itself is a DB read (TODO-033). Official API requires a verified app — dev portal: https://apps.developer.allegro.pl/ |
| OLX | **Working (on demand)** | Used listings found by the `searcher/` service — Claude Code CLI web search (`bike_offer_olx.md`, subscription token) + Playwright photos — stored in `bike_offer` / `bike_offer_photos`; triggered by the Used card's **Poproś o dane** button or `curl :8100/v1/search/olx`. Official API still pending account approval (`backlog/blocked/TODO_009`) |
| Decathlon | **Working (on demand)** | New-bike offers found by the same `searcher/` service — Claude Code CLI web search (`bike_offer_decathlon.md`, subscription token), no photos — stored in `bike_offer` (`source = 'decathlon.pl'`); triggered by the New card's **Poproś o dane** button or `curl :8100/v1/search/decathlon`. The backend only forwards Decathlon house brands (`backend/app/decathlon_brands.py`); any other brand gets an instant empty answer (closes `TODO_ISSUE_010`). `POST /v1/bike/decathlon` itself is a DB read (TODO-032) |
| Amazon | Todo | — |

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14, FastAPI, Uvicorn |
| AI | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) — API key for the backend; the searcher (OLX + Decathlon + Allegro + photos + review) calls the same model through the Claude Code CLI (`claude -p`, subscription OAuth token) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4 |
| Fonts | Barlow Condensed · Lora · JetBrains Mono |

## Project structure

```
biker/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, routes
│   │   ├── schemas.py                 # Pydantic models
│   │   ├── repository.py              # ORM data access: bike details + DB-first search (find_bikes_by_details) + missing-data request counter
│   │   ├── offers_repository.py       # Stored marketplace offers read side: get_used_offers (olx.pl) + get_decathlon_offers (decathlon.pl) + get_allegro_offers (allegro.pl) + bike_exists
│   │   ├── popular_repository.py      # Popular bikes read side for GET /v1/bike/popular: bike_popular + bike + bike_detail, two-sentence blurb (first_sentences)
│   │   ├── searcher_client.py         # httpx proxy to the searcher (search_olx / search_decathlon / search_allegro / search_photos / search_review), single-flight + shared in-flight cap (10)
│   │   ├── decathlon_brands.py        # Decathlon house-brand allowlist for /v1/bike/decathlon/search (is_decathlon_brand, not_sold_info; TODO_ISSUE_010)
│   │   ├── bike_finder.py             # Single Claude call → all matching bikes, min 1 (DB-miss fallback)
│   │   ├── bike_details_finder.py     # Fetch full component specs via web search
│   │   ├── bike_description_finder.py # Generate Polish plain-text overview via web search
│   │   ├── reviews_repository.py      # Stored bike review (bike_review + bike_review_source) — DB read for /v1/bike/review
│   │   ├── photos_repository.py       # Stored bike photos: get_bike_photos (POST /v1/bike/photos) — bike_detail_photos keyed on bike_id
│   │   ├── equipment_categories.py    # 4 equipment category registry + inference
│   │   ├── equipment_details_finder.py    # Equipment component specs (per-category prompt)
│   │   ├── equipment_description_finder.py # Equipment overview via web search
│   │   ├── equipment_photos_finder.py      # Equipment manufacturer photos
│   │   ├── equipment_review_finder.py      # Equipment review (review/forum links only)
│   │   └── prompts/
│   │       ├── bike_search.md         # Single-call bike-finding prompt
│   │       ├── bike_details.md        # Component extraction prompt
│   │       ├── bike_offer.md          # Multi-marketplace offer prompt (unused)
│   │       ├── bike_offer_ceneo.md    # Ceneo offer search prompt (the only offer finder still on the API key)
│   │       ├── equipment_details_*.md # Per-category equipment spec prompts (helmets/lights/locks/apparel)
│   │       ├── equipment_description.md   # Equipment overview prompt
│   │       ├── equipment_photos.md        # Equipment manufacturer page URL prompt
│   │       └── equipment_review.md        # Equipment review prompt (no offer links)
│   └── scripts/
│       ├── seed_popular_bikes.py      # Fill bike_popular (home page "Najpopularniejsze rowery") with 3 bikes that have details + photos + a stored review; --dry-run, --count, --bike "Brand|Model"
│       ├── test_search.py             # Smoke tests for /v1/bike/search (+ /v1/bike/missing, /v1/bike/popular, /v1/bike/used/olx, /v1/bike/used/search, /v1/bike/decathlon, /v1/bike/decathlon/search, /v1/bike/allegro, /v1/bike/allegro/search)
│       ├── test_details.py            # Smoke test for /v1/bike/details
│       ├── copy_review_cache_to_table.py  # One-off: generic-cache reviews -> bike_review tables (TODO-037)
│       ├── test_equipment.py          # Smoke test for /v1/equipment/details + /review
│       └── test_equipment_review.py   # Focused regression for equipment-review JSON extraction
└── frontend/
    └── src/
        ├── App.tsx                    # App shell, state machine, all API calls
        ├── types.ts                   # Shared TypeScript interfaces
        ├── hooks/
        │   └── usePopularBikes.ts     # Home page: GET /v1/bike/popular once + one POST /v1/bike/review per bike (TODO-034)
        └── components/
            ├── SearchInput.tsx        # Search form
            ├── ResultCard.tsx         # Per-bike result card (with `expertRating` also the home page's popular look: expert rating instead of match score)
            ├── PopularBikesSection.tsx    # "Najpopularniejsze rowery" under the search form, hidden while searching / showing results
            ├── LoadingCard.tsx        # Shimmer skeleton for search results
            ├── BikeDetailsView.tsx    # Bike details page: Overview, Offers, Review, Specs
            ├── RequestDataButton.tsx  # "Request data" button for empty bike-details sections (POST /v1/bike/missing); in the Used card also runs the OLX search, in the New card the Decathlon + Allegro searches at once
            ├── EquipmentDetailsView.tsx   # Equipment details page: Overview, Review, Specs (no offers)
            └── BikeDetailsShared.tsx  # Shared building blocks for both detail views
├── searcher/                          # On-demand OLX + Decathlon + Allegro + photos + review searcher (TODO-031 / 032 / 033 / 035 / 036) — FastAPI on :8100, Claude Code CLI + Playwright (OLX listing photos, bike photos)
│   ├── app/
│   │   ├── main.py                    # POST /v1/search/olx + /decathlon + /allegro + /photos + /review (X-Searcher-Key, SEARCHER_MAX_CONCURRENT shared slots, default 10) + GET /health
│   │   ├── claude_cli.py              # subprocess wrapper around `claude -p --json-schema …`
│   │   ├── olx_finder.py              # the former backend bike_used_finder (CLI call + photo scrape)
│   │   ├── decathlon_finder.py        # the former backend bike_offer_decathlon_finder (CLI call only, no photos)
│   │   ├── allegro_finder.py          # the former backend bike_offer_finder (CLI call only, no photos — allegro.pl 403s every automated fetch; ≤ 3 offers)
│   │   ├── olx_image_fetcher.py       # Playwright: up to 4 OLX CDN photos per listing
│   │   ├── photos_finder.py           # the former backend bike_photos_finder (CLI finds the manufacturer page, Playwright takes ≤ 8 photos)
│   │   ├── repository.py / models.py  # save_offers: writes bike_offer + bike_offer_photos (replace per bike + source); save_photos: bike_detail_photos, insert-only
│   │   └── prompts/                   # bike_offer_olx.md + bike_offer_decathlon.md + bike_offer_allegro.md + bike_photos.md — the search prompts (moved from the backend)
│   ├── scripts/test_searcher.py       # Smoke test (health, auth + validation on all five routes, stored photos — no paid runs)
│   └── Dockerfile                     # Python 3.14 + Node 24 + claude CLI + Chromium for the OLX and bike photos (Cloud Run image)
└── webscraper/centrumrowerowe/        # Local bike discovery (TODO-036), no AI: scrape_rowery.py -> bike_discovery queue -> process_queue.py -> bike + bike_detail
    ├── db.py                          # backend engine/.env + BikeDiscovery model + local-database guard (--allow-remote)
    ├── name_split.py / product_parser.py / spec_mapping.py   # listing name split; product page -> BikeDetailsResponse; Polish label -> English tree
    └── tests/                         # pytest on saved product pages (tests/fixtures/)
```
