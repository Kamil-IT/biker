# Biker — AI Bike Finder

AI-powered bike finder. Describe what you're looking for in plain English and get matched to real bike models instantly.

## How it works

1. You enter a free-text description (e.g. *"comfortable bike for daily 10 km city commute"*)
2. The backend first searches its own bike database: every structured filter it can check (brand, model, frame material, wheel size, frame size, gender, electric, battery, brakes, drivetrain, belt drive) is matched against stored bike specs. All matching bikes are returned (no cap) with no AI call
3. Only when the database has no match, a single Claude Haiku call recommends every real bike that fits (at least 1 — the closest match when nothing meets every filter)
4. Click a result to open the details page — the backend fetches specs, description, manufacturer photos, review score, and current Allegro / Ceneo / Decathlon offers in parallel via Claude web search + Playwright; used OLX listings are read from the database only. Any section (photos, overview, specs, review, Used / New offers) still without data after 5 s — or with an empty/failed response — shows a **Request data** button instead of its spinner; clicking it records the request via `POST /v1/bike/missing`. Data that arrives later replaces the button
5. In the **Used** offers card that same button also starts the on-demand OLX search (`POST /v1/bike/used/search` → the `searcher/` service, which runs the Claude Code CLI on your subscription and stores what it finds in `bike_offer`). The button reads "Szukam na OLX…" while it runs, then the real listings with photos replace it — or "Nie znaleziono ofert" when there are none
6. Click any component name in a bike's spec sheet (e.g. a derailleur, fork, or saddle) to open the **equipment** page for that item — an overview, component-tree spec sheet, photos, and an expert review for gear (helmets, lights, locks, apparel). Equipment is informational only — no shopping/offer links

## Running the project

You need **Docker** for the database and **two terminals** — backend and frontend run separately (a third one for the
optional OLX searcher, see Terminal 3).

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

### Terminal 3 — OLX searcher (optional, TODO-031)

The used-bike search on OLX runs in its own service so it only spends tokens when a user asks for it — and it spends
them from the **Claude Code subscription** (`claude -p`), not from `ANTHROPIC_API_KEY`. Log the CLI in once (`claude`),
then:

```bash
cd searcher
copy .env.example .env          # DATABASE_URL (same Postgres as the backend) + SEARCHER_API_KEY
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8100
```

`backend/.env` needs the matching `SEARCHER_URL=http://localhost:8100` and `SEARCHER_API_KEY`. Without the searcher the
app still works — the Used card's **Poproś o dane** button just gets a 503 and stays clickable. Try it by hand:

```bash
curl -X POST http://localhost:8100/v1/search/olx -H "X-Searcher-Key: dev-local-searcher-key" -H "Content-Type: application/json" -d "{\"company\":\"Trek\",\"model\":\"Marlin 5\"}"
```

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
| `searcher` | `searcher/Dockerfile` | 8100 | Python 3.14 + Node 24 + `@anthropic-ai/claude-code` (pinned) + patchright Chromium; runs `claude -p` with `CLAUDE_CODE_OAUTH_TOKEN`, writes `bike_offer` into the same database (same pgpass mount); the backend reaches it as `SEARCHER_URL=http://searcher:8100` |
| `db` | `postgres:17` | 5433 → 5432 | profile `local-db` only; named volume `pgdata` |

## Deploy to GCP (Cloud Run)

The same two images run as two Cloud Run services in `europe-central2` (project `biker-engine-prod`): `biker-backend`
(Cloud SQL `biker-pg` over the `/cloudsql/…` unix socket) and `biker-frontend` (nginx with `BACKEND_URL` set to the
backend's `run.app` URL, so the browser only ever talks to the frontend origin — no CORS). Secrets never leave Secret
Manager: `anthropic-api-key` → `ANTHROPIC_API_KEY`, `db-password` → `PGPASSWORD` (libpq reads it; `DATABASE_URL` carries
no password). This is TODO-030 step 1; the per-IP rate limit, budget alerts and `docs/DEPLOYMENT.md` follow in step 2.

TODO-031 adds a third service, `biker-searcher` (the on-demand OLX searcher): same Cloud SQL socket, `--concurrency 1`,
2 vCPU / 2 GiB, timeout 900 s, `max-instances 1`, scale to zero; secrets `searcher-api-key` → `SEARCHER_API_KEY`,
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
at `BROWSER_MAX_CONCURRENCY=2` (each ≈ 0.5–0.9 GiB), so a burst of uncached details/offer requests queues for a browser
instead of exceeding the 2 GiB and getting the instance killed; raise it only together with `--memory`.

## Other useful commands

| Command | What it does |
|---|---|
| `cd backend && python scripts/test_search.py` | Smoke-test `POST /v1/bike/search` (+ `/v1/bike/missing`, `/v1/bike/used`, `/v1/bike/used/search`) |
| `cd searcher && python scripts/test_searcher.py` | Smoke-test the OLX searcher (`/health`, auth, one real search + DB check) |
| `cd backend && python scripts/test_details.py` | Smoke-test `POST /v1/bike/details` |
| `cd backend && python scripts/test_review.py` | Smoke-test `POST /v1/bike/review` |
| `cd backend && python scripts/test_offer.py` | Smoke-test `POST /v1/bike/offer` |
| `cd backend && python scripts/test_equipment.py` | Smoke-test `POST /v1/equipment/details` + `/v1/equipment/review` |
| `cd backend && pytest` | Review-aggregation unit tests (no API key) |
| `cd frontend && npm run build` | TypeScript check + production bundle → `dist/` |
| `cd frontend && npm run preview` | Serve the production bundle locally |
| http://localhost:8000/docs | Interactive OpenAPI UI for the backend |

## Marketplace integrations

| Marketplace | Status | Notes |
|---|---|---|
| Allegro | **Working** | Offers fetched via Claude web search (`bike_offer_allegro.md`). Official API requires a verified app — dev portal: https://apps.developer.allegro.pl/ |
| OLX | **Working (on demand)** | Used listings found by the `searcher/` service — Claude Code CLI web search (`bike_offer_olx.md`, subscription token) + Playwright photos — stored in `bike_offer` / `bike_offer_photos`; triggered by the Used card's **Poproś o dane** button or `curl :8100/v1/search/olx`. Official API still pending account approval (`backlog/blocked/TODO_009`) |
| Amazon | Todo | — |

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14, FastAPI, Uvicorn |
| AI | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) — API key for the backend; the OLX searcher calls the same model through the Claude Code CLI (`claude -p`, subscription OAuth token) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4 |
| Fonts | Barlow Condensed · Lora · JetBrains Mono |

## Project structure

```
biker/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, routes
│   │   ├── schemas.py                 # Pydantic models
│   │   ├── repository.py              # ORM data access: bike details + DB-first search (find_bikes_by_details) + missing-data request counter + stored OLX offers (get_used_offers)
│   │   ├── searcher_client.py         # httpx proxy to the OLX searcher (POST /v1/bike/used/search), single-flight + in-flight cap
│   │   ├── bike_finder.py             # Single Claude call → all matching bikes, min 1 (DB-miss fallback)
│   │   ├── bike_details_finder.py     # Fetch full component specs via web search
│   │   ├── bike_description_finder.py # Generate Polish plain-text overview via web search
│   │   ├── bike_review_finder.py      # Aggregate web reviews into score + explanation
│   │   ├── bike_offer_finder.py       # Find current Allegro offers via web search
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
│   │       ├── bike_offer_allegro.md  # Allegro offer search prompt
│   │       ├── bike_photos.md         # Manufacturer product page URL search prompt
│   │       ├── equipment_details_*.md # Per-category equipment spec prompts (helmets/lights/locks/apparel)
│   │       ├── equipment_description.md   # Equipment overview prompt
│   │       ├── equipment_photos.md        # Equipment manufacturer page URL prompt
│   │       └── equipment_review.md        # Equipment review prompt (no offer links)
│   └── scripts/
│       ├── test_search.py             # Smoke tests for /v1/bike/search (+ /v1/bike/missing, /v1/bike/used, /v1/bike/used/search)
│       ├── test_details.py            # Smoke test for /v1/bike/details
│       ├── test_review.py             # Smoke test for /v1/bike/review
│       ├── test_offer.py              # Smoke test for /v1/bike/offer
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
            ├── RequestDataButton.tsx  # "Request data" button for empty bike-details sections (POST /v1/bike/missing); in the Used card also runs the OLX search
            ├── EquipmentDetailsView.tsx   # Equipment details page: Overview, Review, Specs (no offers)
            └── BikeDetailsShared.tsx  # Shared building blocks for both detail views
└── searcher/                          # On-demand OLX searcher (TODO-031) — FastAPI on :8100, Claude Code CLI + Playwright
    ├── app/
    │   ├── main.py                    # POST /v1/search/olx (X-Searcher-Key) + GET /health
    │   ├── claude_cli.py              # subprocess wrapper around `claude -p --json-schema …`
    │   ├── olx_finder.py              # the former backend bike_used_finder (CLI call + photo scrape)
    │   ├── olx_image_fetcher.py       # Playwright: up to 4 OLX CDN photos per listing
    │   ├── repository.py / models.py  # writes bike_offer + bike_offer_photos (replace per bike)
    │   └── prompts/bike_offer_olx.md  # the OLX search prompt
    ├── scripts/test_searcher.py       # Smoke test
    └── Dockerfile                     # Python 3.14 + Node 24 + claude CLI + Chromium (Cloud Run image)
```
