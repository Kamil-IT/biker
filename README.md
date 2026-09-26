# Biker — AI Bike Finder

AI-powered bike finder. Describe what you're looking for in plain English and get matched to real bike models instantly.

## How it works

1. You enter a free-text description (e.g. *"comfortable bike for daily 10 km city commute"*)
2. The backend first searches its own bike database: every structured filter it can check (brand, model, frame material, wheel size, frame size, gender, electric, battery, brakes, drivetrain, belt drive) is matched against stored bike specs. All matching bikes are returned (no cap) with no AI call
3. Only when the database has no match, a single Claude Haiku call recommends every real bike that fits (at least 1 — the closest match when nothing meets every filter)
4. Click a result to open the details page — the backend fetches specs, description, manufacturer photos and the review score in parallel via Claude web search + Playwright; Allegro offers, Decathlon offers and used OLX listings are read from the database only (they get there through the on-demand searches below — opening a bike never runs a marketplace search). Any section (photos, overview, specs, review, Used / New offers) still without data after 5 s — or with an empty/failed response — shows a **Request data** button instead of its spinner; clicking it records the request via `POST /v1/bike/missing`. Data that arrives later replaces the button
5. In the **Used** offers card that same button also starts the on-demand OLX search (`POST /v1/bike/used/search` → the `searcher/` service, which runs the Claude Code CLI on your subscription and stores what it finds in `bike_offer`). The button reads "Szukam na OLX…" while it runs, then the real listings with photos replace it — or "Nie znaleziono ofert" when there are none. In the **New** card it fires **two** searches at once — Decathlon (`POST /v1/bike/decathlon/search`, no photos) and Allegro (`POST /v1/bike/allegro/search`, with the listing's photos) — through the same searcher; the button reads "Szukam na Allegro i Decathlon…" and rows from either source replace it as they arrive ("Nie znaleziono ofert" only when both came back empty; clickable again when a search failed and neither brought rows). Allegro is searched for every brand, and a used Allegro listing lands in the **Used** card by its `is_new` flag; Decathlon only for its house brands (Rockrider, Btwin, Triban, Van Rysel, Elops, Riverside, Stilus, Tilt; `backend/app/decathlon_brands.py`) — any other brand gets an instant empty Decathlon answer with no search spent (closes `TODO_ISSUE_010`)
6. Click any component name in a bike's spec sheet (e.g. a derailleur, fork, or saddle) to open the **equipment** page for that item — an overview, component-tree spec sheet, photos, and an expert review for gear (helmets, lights, locks, apparel). Equipment is informational only — no shopping/offer links

## Running the project

You need **Docker** for the database and **two terminals** — backend and frontend run separately (a third one for the
optional OLX / Decathlon / Allegro searcher, see Terminal 3).

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
copy .env.example .env          # edit .env and set your ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8000
```

### Terminal 2 — Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

> The frontend proxies `/v1/*` to the backend automatically — no CORS config needed.

### Terminal 3 — OLX / Decathlon / Allegro searcher (optional, TODO-031 / TODO-032 / TODO-033)

The used-bike search on OLX, the new-bike search on decathlon.pl and the Allegro offer search run in their own service so
they only spend tokens when a user asks for them — and they spend them from the **Claude Code subscription**
(`claude -p`), not from `ANTHROPIC_API_KEY`. Log the CLI in once (`claude`), then:

```bash
cd searcher
copy .env.example .env          # DATABASE_URL (same Postgres as the backend) + SEARCHER_API_KEY
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8100
```

`backend/.env` needs the matching `SEARCHER_URL=http://localhost:8100` and `SEARCHER_API_KEY`. Without the searcher the
app still works — the Used and New cards' **Poproś o dane** buttons just get a 503 and stay clickable. Try it by hand:

```bash
curl -X POST http://localhost:8100/v1/search/olx -H "X-Searcher-Key: dev-local-searcher-key" -H "Content-Type: application/json" -d "{\"company\":\"Trek\",\"model\":\"Marlin 5\"}"
curl -X POST http://localhost:8100/v1/search/decathlon -H "X-Searcher-Key: dev-local-searcher-key" -H "Content-Type: application/json" -d "{\"company\":\"Rockrider\",\"model\":\"ST 100\"}"
curl -X POST http://localhost:8100/v1/search/allegro -H "X-Searcher-Key: dev-local-searcher-key" -H "Content-Type: application/json" -d "{\"company\":\"Trek\",\"model\":\"Marlin 5\"}"
```

The three routes share `SEARCHER_MAX_CONCURRENT` busy slots (default 2 — the New card fires Decathlon and Allegro
together); a third concurrent call answers 503 `searcher busy` while the others run, nothing queues. OLX and Allegro
scrape listing photos with Playwright (Allegro: ≤ 8 gallery photos per offer, `[]` while DataDome blocks the page — which
it does today); the Decathlon search stores no photos. Allegro answers 403 to every automated fetch, so its prompt works
from web-search results alone (an offer may come back with an empty price): 3 offers in 67–75 s in the 2026-09-26 probes.

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
| `searcher` | `searcher/Dockerfile` | 8100 | Python 3.14 + Node 24 + `@anthropic-ai/claude-code` (pinned) + patchright Chromium; runs `claude -p` with `CLAUDE_CODE_OAUTH_TOKEN` for the OLX, Decathlon and Allegro searches (two at once by default), writes `bike_offer` into the same database (same pgpass mount); the backend reaches it as `SEARCHER_URL=http://searcher:8100` |
| `db` | `postgres:17` | 5433 → 5432 | profile `local-db` only; named volume `pgdata` |

## Deploy to GCP (Cloud Run)

The same two images run as two Cloud Run services in `europe-central2` (project `biker-engine-prod`): `biker-backend`
(Cloud SQL `biker-pg` over the `/cloudsql/…` unix socket) and `biker-frontend` (nginx with `BACKEND_URL` set to the
backend's `run.app` URL, so the browser only ever talks to the frontend origin — no CORS). Secrets never leave Secret
Manager: `anthropic-api-key` → `ANTHROPIC_API_KEY`, `db-password` → `PGPASSWORD` (libpq reads it; `DATABASE_URL` carries
no password). This is TODO-030 step 1; the per-IP rate limit, budget alerts and `docs/DEPLOYMENT.md` follow in step 2.

TODO-031 adds a third service, `biker-searcher` (the on-demand OLX searcher; TODO-032 adds the Decathlon search and
TODO-033 the Allegro search to the **same** service — same image and secrets, no new service): same Cloud SQL socket,
`--concurrency 1` (one CLI run + one Chromium per instance), 2 vCPU / 2 GiB, timeout 900 s, `max-instances 2` since
TODO-033 — the New card fires the Decathlon and Allegro searches together, so the second search gets its own instance;
a third concurrent search gets Cloud Run's 429, which the backend reports as 503 busy — scale to zero; secrets `searcher-api-key` → `SEARCHER_API_KEY`,
`claude-code-oauth-token` → `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`), `db-password` → `PGPASSWORD`. The backend
service gets `SEARCHER_URL` (the searcher's `run.app` URL) and `SEARCHER_API_KEY` from the same secret. Like the other two,
the searcher needs the one-time `roles/run.invoker` for `allUsers` (it is protected by the shared secret, and the backend
calls it over the public URL).

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
at `BROWSER_MAX_CONCURRENCY=2` (each ≈ 0.5–0.9 GiB; only the bike / equipment photo scrapers remain in the backend — the
offer scrapers live in the searcher), so a burst of uncached details requests queues for a browser
instead of exceeding the 2 GiB and getting the instance killed; raise it only together with `--memory`.

## Other useful commands

| Command | What it does |
|---|---|
| `cd backend && python scripts/test_search.py` | Smoke-test `POST /v1/bike/search` (+ `/v1/bike/missing`, `/v1/bike/used/olx`, `/v1/bike/used/search`, `/v1/bike/decathlon`, `/v1/bike/decathlon/search`, `/v1/bike/allegro`, `/v1/bike/allegro/search`) |
| `cd searcher && python scripts/test_searcher.py` | Smoke-test the searcher (`/health`, 401/422 on all three search routes — free, no CLI run; the single paid live run lives in `backend/scripts/test_search.py` `case_decathlon_search`) |
| `cd backend && python scripts/test_details.py` | Smoke-test `POST /v1/bike/details` |
| `cd backend && python scripts/test_review.py` | Smoke-test `POST /v1/bike/review` |
| `cd backend && python scripts/test_equipment.py` | Smoke-test `POST /v1/equipment/details` + `/v1/equipment/review` |
| `cd backend && pytest` | Review-aggregation unit tests (no API key) |
| `cd frontend && npm run build` | TypeScript check + production bundle → `dist/` |
| `cd frontend && npm run preview` | Serve the production bundle locally |
| http://localhost:8000/docs | Interactive OpenAPI UI for the backend |

## Marketplace integrations

| Marketplace | Status | Notes |
|---|---|---|
| Allegro | **Working (on demand)** | Offers found by the same `searcher/` service — Claude Code CLI web search (`bike_offer_allegro.md`, subscription token) + Playwright photos (≤ 8 per offer, `[]` when DataDome blocks the page) — stored in `bike_offer` / `bike_offer_photos` (`source = 'allegro.pl'`, `is_new` as the listing said); triggered by the New card's **Poproś o dane** button (together with the Decathlon search) or `curl :8100/v1/search/allegro`. `POST /v1/bike/allegro` itself is a DB read (TODO-033). Official API requires a verified app — dev portal: https://apps.developer.allegro.pl/ |
| OLX | **Working (on demand)** | Used listings found by the `searcher/` service — Claude Code CLI web search (`bike_offer_olx.md`, subscription token) + Playwright photos — stored in `bike_offer` / `bike_offer_photos`; triggered by the Used card's **Poproś o dane** button or `curl :8100/v1/search/olx`. Official API still pending account approval (`backlog/blocked/TODO_009`) |
| Decathlon | **Working (on demand)** | New-bike offers found by the same `searcher/` service — Claude Code CLI web search (`bike_offer_decathlon.md`, subscription token), no photos — stored in `bike_offer` (`source = 'decathlon.pl'`); triggered by the New card's **Poproś o dane** button or `curl :8100/v1/search/decathlon`. The backend only forwards Decathlon house brands (`backend/app/decathlon_brands.py`); any other brand gets an instant empty answer (closes `TODO_ISSUE_010`). `POST /v1/bike/decathlon` itself is a DB read (TODO-032) |
| Amazon | Todo | — |

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14, FastAPI, Uvicorn |
| AI | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) — API key for the backend; the searcher (OLX + Decathlon + Allegro) calls the same model through the Claude Code CLI (`claude -p`, subscription OAuth token) |
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
│   │   ├── searcher_client.py         # httpx proxy to the searcher (search_olx / search_decathlon / search_allegro), single-flight + shared in-flight cap (2)
│   │   ├── decathlon_brands.py        # Decathlon house-brand allowlist for /v1/bike/decathlon/search (is_decathlon_brand, not_sold_info; TODO_ISSUE_010)
│   │   ├── bike_finder.py             # Single Claude call → all matching bikes, min 1 (DB-miss fallback)
│   │   ├── bike_details_finder.py     # Fetch full component specs via web search
│   │   ├── bike_description_finder.py # Generate Polish plain-text overview via web search
│   │   ├── bike_review_finder.py      # Aggregate web reviews into score + explanation
│   │   ├── bike_photos_finder.py      # Find manufacturer product photos: Claude URL search + Playwright scrape
│   │   ├── equipment_categories.py    # 4 equipment category registry + inference
│   │   ├── equipment_details_finder.py    # Equipment component specs (per-category prompt)
│   │   ├── equipment_description_finder.py # Equipment overview via web search
│   │   ├── equipment_photos_finder.py      # Equipment manufacturer photos
│   │   ├── equipment_review_finder.py      # Equipment review (review/forum links only)
│   │   └── prompts/
│   │       ├── bike_search.md         # Single-call bike-finding prompt
│   │       ├── bike_details.md        # Component extraction prompt
│   │       ├── bike_review.md         # Review aggregation prompt
│   │       ├── bike_offer.md          # Multi-marketplace offer prompt (unused)
│   │       ├── bike_offer_ceneo.md    # Ceneo offer search prompt (the only offer finder still on the API key)
│   │       ├── bike_photos.md         # Manufacturer product page URL search prompt
│   │       ├── equipment_details_*.md # Per-category equipment spec prompts (helmets/lights/locks/apparel)
│   │       ├── equipment_description.md   # Equipment overview prompt
│   │       ├── equipment_photos.md        # Equipment manufacturer page URL prompt
│   │       └── equipment_review.md        # Equipment review prompt (no offer links)
│   └── scripts/
│       ├── test_search.py             # Smoke tests for /v1/bike/search (+ /v1/bike/missing, /v1/bike/used/olx, /v1/bike/used/search, /v1/bike/decathlon, /v1/bike/decathlon/search, /v1/bike/allegro, /v1/bike/allegro/search)
│       ├── test_details.py            # Smoke test for /v1/bike/details
│       ├── test_review.py             # Smoke test for /v1/bike/review
│       ├── test_equipment.py          # Smoke test for /v1/equipment/details + /review
│       └── test_equipment_review.py   # Focused regression for equipment-review JSON extraction
└── frontend/
    └── src/
        ├── App.tsx                    # App shell, state machine, all API calls
        ├── types.ts                   # Shared TypeScript interfaces
        └── components/
            ├── SearchInput.tsx        # Search form
            ├── ResultCard.tsx         # Per-bike result card
            ├── LoadingCard.tsx        # Shimmer skeleton for search results
            ├── BikeDetailsView.tsx    # Bike details page: Overview, Offers, Review, Specs
            ├── RequestDataButton.tsx  # "Request data" button for empty bike-details sections (POST /v1/bike/missing); in the Used card also runs the OLX search, in the New card the Decathlon + Allegro searches at once
            ├── EquipmentDetailsView.tsx   # Equipment details page: Overview, Review, Specs (no offers)
            └── BikeDetailsShared.tsx  # Shared building blocks for both detail views
└── searcher/                          # On-demand OLX + Decathlon + Allegro searcher (TODO-031 / 032 / 033) — FastAPI on :8100, Claude Code CLI + Playwright
    ├── app/
    │   ├── main.py                    # POST /v1/search/olx + /v1/search/decathlon + /v1/search/allegro (X-Searcher-Key, SEARCHER_MAX_CONCURRENT shared slots, default 2) + GET /health
    │   ├── claude_cli.py              # subprocess wrapper around `claude -p --json-schema …`
    │   ├── olx_finder.py              # the former backend bike_used_finder (CLI call + photo scrape)
    │   ├── decathlon_finder.py        # the former backend bike_offer_decathlon_finder (CLI call only, no photos)
    │   ├── allegro_finder.py          # the former backend bike_offer_finder (CLI call + photo scrape, ≤ 3 offers)
    │   ├── olx_image_fetcher.py       # Playwright: up to 4 OLX CDN photos per listing
    │   ├── allegro_image_fetcher.py   # Playwright: DataDome warm-up, then up to 8 allegroimg.com gallery photos per offer (moved from the backend)
    │   ├── repository.py / models.py  # save_offers: writes bike_offer + bike_offer_photos (replace per bike + source)
    │   └── prompts/                   # bike_offer_olx.md + bike_offer_decathlon.md + bike_offer_allegro.md — the search prompts (moved from the backend)
    ├── scripts/test_searcher.py       # Smoke test (health, auth + validation on all three routes — no paid runs)
    └── Dockerfile                     # Python 3.14 + Node 24 + claude CLI + Chromium (Cloud Run image)
```
