# Biker Searcher

The on-demand marketplace search (TODO-031 OLX, TODO-032 Decathlon, TODO-033 Allegro). A small FastAPI service that
runs **only when asked**: `POST /v1/search/olx` searches olx.pl for a bike, scrapes each listing's photos with Playwright
and writes the result into the shared bike database (`bike_offer` + `bike_offer_photos`, `source = 'olx.pl'`);
`POST /v1/search/decathlon` searches decathlon.pl the same way (one CLI run, no Playwright) and writes `bike_offer` rows
with `source = 'decathlon.pl'`; `POST /v1/search/allegro` searches allegro.pl (one CLI run, no Playwright — Allegro offers
are stored without photos by design, see "Why the Claude Code CLI") and writes rows with `source = 'allegro.pl'`. The
backend never searches any of the three shops itself —
`POST /v1/bike/used/olx`, `POST /v1/bike/decathlon` and `POST /v1/bike/allegro` are pure DB reads, and
`POST /v1/bike/used/search` / `POST /v1/bike/decathlon/search` / `POST /v1/bike/allegro/search` proxy here when the user
clicks **Poproś o dane** in the "Używane" (OLX) / "Nowe" (Decathlon **and** Allegro at once) card. The three searches
share `SEARCHER_MAX_CONCURRENT` busy slots (default **2**, so the two searches the "Nowe" button fires both run); a third
concurrent search is refused with 503, never queued.

## Why the Claude Code CLI

The search is the most token-hungry call in the project (web search + fetch per bike), so it is billed to the Claude
**subscription** instead of the API key: every model call goes through `claude -p` — the Claude Code CLI — with
`ANTHROPIC_API_KEY` stripped from the child environment. Locally that is your logged-in `claude`; on a server it is
`CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`. `--output-format json --json-schema` makes the CLI return an
already-validated `structured_output`, so there is no prose parsing.

```
claude -p "Find current used bike offers on OLX for: Trek Marlin 5" \
  --system-prompt "<app/prompts/bike_offer_olx.md>" --output-format json --json-schema '<schema>' \
  --tools WebSearch,WebFetch --allowedTools WebSearch,WebFetch --permission-prompts none \
  --strict-mcp-config --setting-sources "" --no-session-persistence \
  --exclude-dynamic-system-prompt-sections --model claude-haiku-4-5-20251001
```

Probe on 2026-09-25: Trek Marlin 5 → 5 real OLX listings in 34 s.

Allegro is different (probes 2026-09-26): **allegro.pl answers HTTP 403 (DataDome captcha) to every automated request** —
to the CLI's `WebFetch` and to patchright Chromium alike, headless or headed, already on the homepage. The backend's
SDK-era prompt ("open the listing, open the offer page") therefore did not survive the move: Trek Marlin 5 needed
**286 s** of the 300 s `SEARCHER_CLI_TIMEOUT` to fall back to search results (1 offer), Kross Level 3.0 gave up after
49 s with `offers: []` ("Allegro.pl blocks automated page fetching"). `app/prompts/bike_offer_allegro.md` is therefore a
**CLI-tuned rewrite** (same role, rules and output; WebSearch results only, never `WebFetch` on allegro.pl; price and
condition from the result title/snippet): Kross Level 3.0 → 3 real offers in **67 s** (8 turns), Trek Marlin 4 → 3 real
offers in **75 s** (11 turns, no price visible in the snippets → `"price": ""`). The Playwright photo scrape that shipped
with the move got the same 403 on every offer page — 0 photos in every probe, for ~10 s and a browser launch per run —
so it was **dropped** (decision of 2026-09-26): Allegro offers are stored with `photos: []` by design and the route
launches no browser.

## Layout

| File | Responsibility |
|------|----------------|
| `app/main.py` | FastAPI app: `GET /health` (open) · `POST /v1/search/olx` · `POST /v1/search/decathlon` · `POST /v1/search/allegro` (all three `X-Searcher-Key`); one `asyncio.Semaphore(SEARCHER_MAX_CONCURRENT)` (default 2) shared by the three routes around the whole search (`_run_search` is the common body; `locked()` is true only when every slot is taken, so the busy check holds for any slot count) |
| `app/config.py` | Env vars (see below), loads `searcher/.env`; `DATABASE_URL` is required — no SQLite fallback |
| `app/claude_cli.py` | `run_structured()` — the `claude -p` subprocess wrapper (argv list, `stdin=DEVNULL`, timeout, sanitised errors); `cli_version()` |
| `app/olx_finder.py` | The moved `find_used_bikes`: prompt → CLI → ≤ 5 offers (`is_new=false`, `source=olx.pl`) → photo scrape. Also home of `SearcherError`, the `{info, offers[]}` CLI schema and the `bike_offer` column widths the Decathlon and Allegro finders reuse |
| `app/decathlon_finder.py` | The moved `find_decathlon_offers` (TODO-032): prompt → CLI → ≤ 3 offers (`url` on `https://www.decathlon.pl/`, `is_new` from the page — default true, `source=decathlon.pl`, `photos=[]`, `city=null`). No Playwright |
| `app/allegro_finder.py` | The moved `find_allegro_offers` (TODO-033, the backend's former `bike_offer_finder`): prompt → CLI → ≤ 3 offers (`url` must be an `allegro.pl/oferta/…` or `allegro.pl/produkt/…` page — a search/category page is dropped, `is_new` from the result title/snippet, `price` may be `""` when no snippet showed one, `source=allegro.pl`, `photos=[]`, `city=null`). No Playwright — the photo scrape was dropped because allegro.pl answers 403 to Chromium too |
| `app/olx_image_fetcher.py` · `app/browser_config.py` | Playwright scrape of ≤ 4 `apollo.olxcdn.com` images per listing (copied from the backend) |
| `app/models.py` · `app/repository.py` | SQLAlchemy over `bike` / `bike_offer` / `bike_offer_photos` (DDL identical to `backend/app/models.py`; `init_db()` only checks they exist); `save_offers(company, model, offers, source)` upserts on `url` within this bike **and** source, takes `is_new` from each offer, never re-parents a listing, deletes the bike's stale rows of that source only when something new was stored |
| `app/prompts/bike_offer_olx.md` · `app/prompts/bike_offer_decathlon.md` · `app/prompts/bike_offer_allegro.md` | The system prompts — OLX and Decathlon byte-for-byte the backend's former prompts; the Allegro one is a CLI-tuned rewrite (WebSearch only, allegro.pl answers 403 to every fetch — see "Why the Claude Code CLI") |
| `scripts/test_searcher.py` | Smoke test, free: health, 401 ×2 + 422 on `/v1/search/olx` (TC-1–4), 401 + 422 on `/v1/search/decathlon` (TC-5–6), 401 + 422 on `/v1/search/allegro` (TC-7–8). No `claude -p` run — the one paid live search of the test set is `backend/scripts/test_search.py` `case_decathlon_search` |

## Run locally

Prerequisites: the `claude` CLI installed and logged in (`claude --version` works), the local PostgreSQL
(`docker start biker-pg`), and Chromium for patchright (`patchright install chromium` — the backend venv already has it).

```bash
cd searcher
copy .env.example .env      # SEARCHER_API_KEY + DATABASE_URL are already filled in for local use

# either reuse the backend venv (it has every dependency) …
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8100
# … or make its own
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && patchright install chromium
uvicorn app.main:app --port 8100
```

Startup logs the database URL (password hidden) and the CLI version; a missing `DATABASE_URL` aborts startup with a
`RuntimeError`. Then, in a second terminal:

```bash
..\backend\.venv\Scripts\python.exe scripts/test_searcher.py
```

The backend picks it up through `SEARCHER_URL=http://localhost:8100` + `SEARCHER_API_KEY` in `backend/.env`.

## Environment variables

| Variable | Required | Meaning |
|----------|----------|---------|
| `SEARCHER_API_KEY` | yes | Shared secret; every `POST /v1/search/*` must send it as `X-Searcher-Key`. Unset = 401 for everyone (fail closed) |
| `DATABASE_URL` | yes | SQLAlchemy URL of the bike DB, e.g. `postgresql+psycopg://biker:biker@localhost:5432/biker`. SQLite URLs work too (tests), but there is no default |
| `CLAUDE_CODE_OAUTH_TOKEN` | server | Subscription token for the CLI (`claude setup-token`). Locally the CLI login is used instead |
| `CLAUDE_BIN` | no | Path to the CLI when it is not on `PATH` |
| `SEARCHER_CLAUDE_MODEL` | no | Default `claude-haiku-4-5-20251001` |
| `SEARCHER_CLI_TIMEOUT` | no | Seconds before a CLI run is killed (default 300) |
| `SEARCHER_MAX_CONCURRENT` | no | CLI runs (the OLX one with its browser) allowed at once, counted across **all three** search routes; further requests get 503 "searcher busy" (default **2** — the "Nowe" button fires the Decathlon and Allegro searches together; locally that is two CLI runs in one process, on Cloud Run each instance still serves one request and the second search gets its own instance) |
| `SEARCHER_CREATE_TABLES` | no | `true` = `create_all()` on startup for a database the backend never touches (scratch tests). Default: refuse to start until `bike` / `bike_offer` / `bike_offer_photos` exist — the backend creates them, and two `create_all()`s on one fresh database race |
| `PLAYWRIGHT_HEADLESS` | no | `true` on servers / in Docker; unset = visible browser for debugging |

Neither the API key, the OAuth token nor the DB password is ever logged.

## Endpoints

### `POST /v1/search/olx`

```http
POST http://localhost:8100/v1/search/olx
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"company": "Trek", "model": "Marlin 5"}
```

```bash
curl -s -X POST http://localhost:8100/v1/search/olx \
  -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key" \
  -d '{"company":"Trek","model":"Marlin 5"}'
```

- `200` → `{"offers": [BikeOffer…], "info": str, "bike_id": int | null, "saved": int}` — `BikeOffer =
  {brand, model, price, is_new: false, url, photos: [str], source: "olx.pl", city: str | null}`. `offers` are exactly
  the rows now stored under this bike (`saved == len(offers)`). A search that finds nothing is a 200 with
  `offers: []` — and the bike's previously stored rows are **kept** (an OLX hiccup must not wipe paid-for data)
- `401` missing/wrong `X-Searcher-Key` (also when `SEARCHER_API_KEY` is unset)
- `422` empty `company`/`model` (after strip) or longer than 255 characters
- `502` `{"detail": "claude CLI failed: exit 1" | "claude CLI timed out after 300 s" | "claude CLI returned no
  structured output" | …}` — a short summary; the CLI's stderr tail is only in the server log
- `503` `{"detail": "searcher busy"}` straight away when `SEARCHER_MAX_CONCURRENT` searches are already running —
  nothing queues, because a queued search would outlive the backend's timeout and end in a second paid run
- `500` `{"detail": "database write failed"}`

**Flow**: (1) `claude -p` once (`--tools WebSearch,WebFetch`, the CLI does the olx.pl searches/fetches) →
(2) Playwright opens each listing URL once (≤ 5, 20 s each; a non-200 page — OLX answers 503 when it rate-limits an
IP — is logged and skipped) and takes ≤ 4 `apollo.olxcdn.com` image URLs →
(3) one DB transaction: bike looked up by normalised brand/model (created with the caller's casing if missing),
`INSERT … ON CONFLICT (url) DO UPDATE` per offer **limited to this bike's rows** (`url` is globally unique and the
prompt's cascade returns model-family listings, so a URL already stored under another bike stays there and is not
reported as saved), its photos rewritten in `display_order`, then — only when at least one offer was stored — every
`olx.pl` row of that bike not in the new set deleted.

### `POST /v1/search/decathlon`

```http
POST http://localhost:8100/v1/search/decathlon
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"company": "Rockrider", "model": "ST 100"}
```

```bash
curl -s -X POST http://localhost:8100/v1/search/decathlon \
  -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key" \
  -d '{"company":"Rockrider","model":"ST 100"}'
```

```json
{
  "offers": [
    {"brand": "Rockrider", "model": "ST 100", "price": "1249 zł", "is_new": true,
     "url": "https://www.decathlon.pl/p/rower-gorski-mtb-27-5-cala-rockrider-st-100/_/R-p-192872",
     "photos": [], "source": "decathlon.pl", "city": null}
  ],
  "info": "",
  "bike_id": 42,
  "saved": 1
}
```

- `200` → the same `{offers, info, bike_id, saved}` shape as `/v1/search/olx`; each `BikeOffer` has `url` on
  `https://www.decathlon.pl/`, `source: "decathlon.pl"`, `is_new` as the shop page says (true unless it is an outlet /
  refurbished item), `photos: []` and `city: null`. At most 3 offers. `offers` are exactly the rows now stored under
  this bike for `source = 'decathlon.pl'` (`saved == len(offers)`); nothing found is a 200 with `offers: []` and the
  bike's previously stored Decathlon rows are **kept**
- `401` / `422` / `502` / `500` exactly as for `/v1/search/olx`
- `503` `{"detail": "searcher busy"}` — the `SEARCHER_MAX_CONCURRENT` slots (default 2) are **shared** with
  `/v1/search/olx` and `/v1/search/allegro` whatever the source, so a Decathlon search is refused while two other
  searches are running (nothing queues)

The backend only calls this for Decathlon house brands (Rockrider, Btwin, Triban, Van Rysel, Elops, Riverside, Stilus,
Tilt, Decathlon) — for any other brand it answers its own `/v1/bike/decathlon/search` without a searcher run.

**Flow**: (1) `claude -p` once with `app/prompts/bike_offer_decathlon.md` (`--tools WebSearch,WebFetch`, the CLI does the
decathlon.pl search/fetch; message `Find current offers on decathlon.pl for: {company} {model}`) — **no Playwright**,
Decathlon offers carry no photos →
(2) one DB transaction: bike looked up by normalised brand/model (created with the caller's casing if missing),
`INSERT … ON CONFLICT (url) DO UPDATE` per offer **limited to this bike's `decathlon.pl` rows** (a URL already stored
under another bike or source stays there and is not reported as saved), then — only when at least one offer was
stored — every `decathlon.pl` row of that bike not in the new set deleted. `bike_offer_photos` is never written.

### `POST /v1/search/allegro`

```http
POST http://localhost:8100/v1/search/allegro
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"company": "Trek", "model": "Marlin 5"}
```

```bash
curl -s -X POST http://localhost:8100/v1/search/allegro \
  -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key" \
  -d '{"company":"Trek","model":"Marlin 5"}'
```

```json
{
  "offers": [
    {"brand": "Trek", "model": "Marlin 5", "price": "2319 zł", "is_new": false,
     "url": "https://allegro.pl/oferta/rower-gorski-mtb-trek-marlin-5-29-l-shimano-hydraulika-poserwisie-noweopony-18571327937",
     "photos": [], "source": "allegro.pl", "city": null}
  ],
  "info": "",
  "bike_id": 12,
  "saved": 1
}
```

- `200` → the same `{offers, info, bike_id, saved}` shape as `/v1/search/olx`; each `BikeOffer` has `url` on an
  `allegro.pl/oferta/…` or `allegro.pl/produkt/…` page (a search or category page is dropped), `source: "allegro.pl"`,
  `is_new` as the search result says (used when the title/snippet says "używany", new when it says new or looks like a
  shop listing — the UI's `is_new` split puts a used listing in the "Używane" card), `price` as shown in the result
  snippet (`""` when none showed it — the UI then says "cena w ofercie"), `photos: []` (always — the Allegro search
  stores no photos, see below) and `city: null`. At most
  3 offers. `offers` are exactly the rows now stored under this bike for `source = 'allegro.pl'`
  (`saved == len(offers)`); nothing found is a 200 with `offers: []` and the bike's previously stored Allegro rows
  are **kept**
- `401` / `422` / `502` / `500` exactly as for `/v1/search/olx`
- `503` `{"detail": "searcher busy"}` — the `SEARCHER_MAX_CONCURRENT` slots (default 2) are **shared** with
  `/v1/search/olx` and `/v1/search/decathlon`: the "Nowe" button's Decathlon + Allegro pair fits, a third concurrent
  search of any source is refused (nothing queues)

Probes 2026-09-26 with the CLI-tuned prompt: Kross Level 3.0 → 3 real offers in **67 s**, Trek Marlin 4 → 3 real offers
in **75 s** (the SDK-era prompt needed 286 s or gave up empty — allegro.pl answers 403 to every fetch, see "Why the
Claude Code CLI"). The Playwright photo pass those probes still ran added ~10 s and a browser launch per run and returned
0 photos every time (403 on the offer pages too), which is why it was removed — this route launches no browser.

**Flow**: (1) `claude -p` once with `app/prompts/bike_offer_allegro.md` (`--tools WebSearch,WebFetch`; the prompt tells the
CLI to use WebSearch only and never fetch allegro.pl; message `Find current offers on allegro for: {company} {model}`) —
**no Playwright**, Allegro offers carry no photos (allegro.pl answers 403 to Chromium as well, so the scrape was dropped) →
(2) one DB transaction: bike looked up by normalised brand/model (created with the caller's casing if missing),
`INSERT … ON CONFLICT (url) DO UPDATE` per offer **limited to this bike's `allegro.pl` rows** (a URL already stored
under another bike or source stays there and is not reported as saved),
then — only when at least one offer was stored — every `allegro.pl` row of that bike not in the new set deleted.
`bike_offer_photos` is never written. OLX
and Decathlon rows of the same bike are untouched, so the Decathlon search running in parallel never collides with it.

### `GET /health`

No auth. `{"status": "ok", "claude_cli": "2.1.282 (Claude Code)" | null, "database": true | false}`.

## Docker

`searcher/Dockerfile`: `python:3.14-slim` + Node 24 (nodesource) + `@anthropic-ai/claude-code` **pinned** to the
version `app/claude_cli.py` was proven on (`ARG CLAUDE_CODE_VERSION=2.1.283`, `DISABLE_AUTOUPDATER=1` — bump it
deliberately and re-run `scripts/test_searcher.py`) + patchright Chromium, non-root user `searcher` with a writable
`HOME` (the CLI keeps state in `~/.claude`), `PLAYWRIGHT_HEADLESS=true`, `PORT=8100`. No secrets in the image — `CLAUDE_CODE_OAUTH_TOKEN`, `SEARCHER_API_KEY` and `DATABASE_URL` come from the
environment.

The root `docker-compose.yml` runs it as the `searcher` service on `8100` against the same **Cloud SQL** database as the
backend (through the `cloudsql-proxy` sidecar and the same mounted pgpass file), started after the backend with
`restart: on-failure` (the backend's `init_db()` creates the shared tables), and gives the backend
`SEARCHER_URL=http://searcher:8100`. Put `CLAUDE_CODE_OAUTH_TOKEN` and `SEARCHER_API_KEY` in `searcher/.env` for the
container — there is no interactive login inside it.

```bash
docker compose up --build -d searcher
curl -s http://localhost:8100/health
```

## Cloud Run

Deployed by the root `scripts/deploy.ps1` (`-Only searcher`, or as part of `all`, which deploys searcher → backend → frontend)
as the Cloud Run service `biker-searcher` in `europe-central2`, project `biker-engine-prod`:

- image `europe-central2-docker.pkg.dev/biker-engine-prod/biker/searcher:<git sha>` built from `searcher/Dockerfile`;
- **scale to zero** (`--min-instances 0`), `--max-instances 2`, `--concurrency 1` (one CLI run per 2 GiB instance, plus
  one Chromium only for an OLX search; two instances so the Decathlon and Allegro searches the "Nowe" button fires together both run — on Cloud Run
  the parallelism comes from the instance count, not from `SEARCHER_MAX_CONCURRENT`, whose default 2 only matters for a
  single local / compose process; a third concurrent search hits Cloud Run's **429**, which the backend maps to
  `SearcherBusy` like the searcher's own 503), `--timeout 900` (a search is minutes; the backend waits at most 600 s),
  `--cpu 2 --memory 2Gi --cpu-boost`;
- the same Cloud SQL socket as the backend: `DATABASE_URL=postgresql+psycopg://biker@/biker?host=/cloudsql/<instance>`
  with `PGPASSWORD` from the `db-password` secret;
- secrets from **Secret Manager** as env vars: `searcher-api-key` → `SEARCHER_API_KEY` (the backend reads the same secret),
  `claude-code-oauth-token` → `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token` on the developer machine);
  the service account `biker-run` needs `roles/secretmanager.secretAccessor` on both;
- the backend service gets `SEARCHER_URL=https://biker-searcher-….run.app` and `SEARCHER_API_KEY` from the same secret;
- who may call it is a one-time IAM decision outside the script: `roles/run.invoker` for `allUsers` (the endpoint is
  protected by the shared secret, and the backend calls it over its public URL).

Cold start ≈ 10–20 s (image ≈ 2.7 GB); the first request then waits on the CLI as usual.
