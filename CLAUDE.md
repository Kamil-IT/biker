# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agent Policy

**Before implementing any multi-step task**, always call `mcp__ruflo__hooks_pre-task` with the task ID and description. It returns agent role suggestions — spawn those agents via `mcp__ruflo__agent_spawn` before writing code. Example flow:

1. `mcp__ruflo__hooks_pre-task` — get agent suggestions for this task
2. `mcp__ruflo__agent_spawn` — spawn one agent per suggested role (e.g. `backend-impl`, `tester`)
3. `mcp__ruflo__task_create` — register the task
4. Implement, then `mcp__ruflo__task_complete` when done

## ECC Skill Routing

Structured workflows for common task types. Use these skills in `.claude/skills/` when starting code changes.

**See `.claude/ECC_INTEGRATION_GUIDE.md` for complete documentation and how to download all 449 ECC skills.**

| Task | Skill | Use When |
|------|-------|----------|
| **Implement new endpoint** | `sparc-code` | Adding POST /v1/bike/* or /v1/equipment/* endpoint |
| **Add tests** | `sparc-tester` | After implementation, before PR; writes smoke tests in backend/scripts/test_search.py |
| **Manual QA of a change** | `manual-tester` | After a backlog task is implemented; compares task vs diff, builds an ISTQB test plan (`qa-manual-istqb`), runs it in the browser (`webapp-testing`), loops fix → retest until green |
| **Security audit** | `sparc-security-review` | New endpoint, new finder module, or API integration (validates input, prevents prompt injection, checks error handling) |
| **Capture pattern** | `memory-persist` | After successful feature completion; saves reusable pattern to Obsidian vault for future tasks |

**Example workflow:**
```
User: "Add Ceneo offer endpoint"

1. Invoke /sparc:code
   → Specification → Pseudocode → Implementation → Testing phases
   → Creates app/bike_offer_ceneo_finder.py + POST /v1/bike/ceneo route

2. Invoke /sparc:tester
   → Adds test to backend/scripts/test_search.py
   → Verifies smoke test passes, cache works, error handling

3. Invoke /sparc:security-review
   → Validates input, prevents prompt injection, checks error responses
   → Runs pen-tests with cURL examples

4. Invoke /memory:persist
   → Saves "Offer finder pattern: single web_search + cache + fallback" to Obsidian
   → Next time: search vault → reuse template → save 1.5 hours

5. Create PR for review
```

**Skills in `.claude/skills/`:**
- `sparc-code.md` — Structured implementation phases + templates
- `sparc-tester.md` — TDD workflow + smoke test templates
- `sparc-security-review.md` — Security checklist + pen-test examples
- `memory-persist.md` — Obsidian vault integration for pattern capture
- **All 449 ECC skills** — Run `python fetch_ecc_skills.py` to download (see guide for details)

**ECC Overview:** 449 production-ready skills for backends (FastAPI, Django, etc.), frontends (React, Vue, etc.), testing, security, DevOps, and specialized domains. See `.claude/ECC_INTEGRATION_GUIDE.md` for complete reference.

## Memory & Persistence

Durable, cross-session memory for this project lives in a single human-readable Obsidian vault — **not** ruflo's `memory_*` / AgentDB stores. The vault is at `obsidian/bike-memory/` (gitignored, including its bearer token) with notes under a `memory/` folder. It is served by the `obsidian` MCP server (the "MCP Connector" plugin, `http://127.0.0.1:27200/mcp`) using local Transformers.js embeddings (`Xenova/all-MiniLM-L6-v2`, no API key).

**To recall:** `mcp__obsidian__search_vault_smart` (semantic) or `search_vault_simple` (keyword).
**To store:** `mcp__obsidian__create_vault_file` (path like `memory/<topic>.md`, with YAML frontmatter + tags).
**To read/update:** `get_vault_file`, `append_to_vault_file`, `patch_vault_file`, `list_vault_files`.

Prefer these over `mcp__ruflo__memory_store` / `memory_search` — the vault is the source of truth so everything stays in one syncable, greppable, Obsidian-browsable store. **Requires the Obsidian app running** with the MCP Connector plugin enabled; if the `obsidian` server is unavailable, say so rather than silently falling back to the ruflo DB.

## Backlog

Tasks are tracked in `/backlog/`. Naming convention:

- `TODO_<ID>_<TASK_NAME>.md` — task not yet started
- `DONE_<ID>_<TASK_NAME>.md` — completed task (rename the file, don't delete it)
- `TODO_ISSUE_<ID>_<NAME>.md` — reported bug/issue, not yet fixed
- `DONE_ISSUE_<ID>_<NAME>.md` — fixed issue (rename the file, don't delete it)

Layout:

```
backlog/            active work — TODO_* files live here
backlog/done/       merged tasks (DONE_*)
backlog/blocked/    implemented but unverifiable — still TODO_*
```

`backlog/` itself holds **only what is actionable now**. Scan it for the next task; the two subfolders are archives, not queues.

When picking up a task: read its file, implement, then rename `TODO_` → `DONE_` **and move it to `backlog/done/`**.
When creating a new task: ask clarifying questions first, then write the file.

### Completed tasks — `backlog/done/`

A task moves here when **its PR has merged to `main`**. Merged is the bar: finished code with an open PR is not done and stays in `backlog/`. Keep the files — they are the record of what was built and why. Update `backlog/done/README.md` when adding one.

### Blocked tasks — `backlog/blocked/`

`backlog/blocked/` holds tasks that are **implemented but cannot be verified** because of an external dependency nobody on the project can satisfy right now (a credential, an account approval, a third-party verification). They keep their `TODO_` prefix — blocked is not done.

- **Do not pick these up in the normal backlog rotation.** Skip the folder when scanning for the next task.
- Move a task back to `backlog/` only once its blocker is genuinely resolved — not merely because its code looks finished.
- `backlog/blocked/README.md` lists what is blocked, on what, what evidence exists, and the known defects to fix on first real use. Update it whenever a task moves in or out.

A task belongs here when its feature **cannot be demonstrated**, not when it is merely hard or unfinished. If the work simply has not been done, it stays a normal `TODO_`.

## Development Rules

**New backend endpoint** → add a smoke test for it in `backend/scripts/test_search.py`. This is the single file for all smoke tests. Each test must call the endpoint against a running local server and assert HTTP 200. (A new **searcher** endpoint gets its smoke test in `searcher/scripts/test_searcher.py` the same way.)

**New backend endpoint using the Anthropic API** → must use the SQLite cache in `app/cache.py`. Pattern:
```python
_fields = {"key_field": req.key_field}  # only fields that uniquely identify the response
cached = get_cached("/v1/your/route", _fields, YourResponseModel)
if cached is not None:
    return cached
# ... existing logic ...
set_cached("/v1/your/route", _fields, result)
return result
```
Only call `set_cached` on the happy path — never cache error/fallback responses.
For endpoints returning offers or reviews, only cache when the result is non-empty:
- Offers: `if result.offers: set_cached(...)`
- Reviews: `if result.ref: set_cached(...)`
- Search/details: always cache (empty is a valid result)
This mirrors the pattern used by `/v1/bike/ceneo`. (`/v1/bike/used/olx`, `/v1/bike/decathlon` and `/v1/bike/allegro` no longer call the API at all — they are DB reads of `bike_offer`, TODO-031 / TODO-032 / TODO-033; the searches behind them run in the searcher service via `/v1/bike/used/search`, `/v1/bike/decathlon/search` and `/v1/bike/allegro/search`, which are never cached.)

## Documentation Update Policy

After **every code change**, review and update the relevant documentation before considering the task done:

| What changed | Files to review & update |
|---|---|
| Any change | `CLAUDE.md` · `README.md` |
| Backend (`/backend/**`) | `backend/README.md` · `README.md` · `CLAUDE.md` |
| Searcher (`/searcher/**`) | `searcher/README.md` (its `## Endpoints` section follows the same rules as the backend's) · `README.md` · `CLAUDE.md` |
| Frontend (`/frontend/**`) | `frontend/README.md` · `README.md` · `CLAUDE.md` |

Update only the sections that are actually affected — do not rewrite docs that remain accurate.

**`backend/README.md` must always contain an `## Endpoints` section** with every endpoint listed, including:
- A raw HTTP request example (`POST http://localhost:8000/...` with `Content-Type` and JSON body)
- A **Flow** list of every outbound HTTP call made (exact URL, service name, and how many times / in what order)

## Project Overview

Monorepo with separate backend, frontend and searcher applications:
- `/backend` — Python REST API (FastAPI)
- `/frontend` — React + TypeScript + Tailwind v4 SPA (Vite)
- `/searcher` — on-demand marketplace searcher (TODO-031 OLX, TODO-032 Decathlon, TODO-033 Allegro): a small FastAPI service (port 8100) that runs the **Claude Code CLI** (`claude -p`, billed to the subscription via the OAuth login / `CLAUDE_CODE_OAUTH_TOKEN`, no `ANTHROPIC_API_KEY`). `POST /v1/search/olx` runs the OLX prompt, scrapes listing photos with Playwright and writes used listings (`source = 'olx.pl'`) into the shared `bike_offer` / `bike_offer_photos` tables; `POST /v1/search/decathlon` runs the Decathlon prompt (no Playwright, no photos) and writes new-bike offers (`source = 'decathlon.pl'`) into `bike_offer`; `POST /v1/search/allegro` runs the Allegro prompt (no Playwright, no photos — allegro.pl answers 403 to every automated fetch, so the photo scrape was dropped by decision on 2026-09-26; `photos: []` by design) and writes ≤ 3 offers (`source = 'allegro.pl'`, `is_new` from the listing, default false) into `bike_offer`. Playwright runs only for OLX. `SEARCHER_MAX_CONCURRENT` busy slots (default **2**) are shared by the three routes — the "Nowe" card fires Decathlon + Allegro together — and a third concurrent search is refused with 503, never queued. Called only by the backend's `POST /v1/bike/used/search` / `POST /v1/bike/decathlon/search` / `POST /v1/bike/allegro/search` (shared secret header `X-Searcher-Key`) or by hand with `curl`. Meant for a scale-to-zero Cloud Run service; see `searcher/README.md`

## Backend Setup

```bash
# Database — local PostgreSQL 17 in Docker (first time: docker run …; later: docker start biker-pg)
docker run -d --name biker-pg -e POSTGRES_USER=biker -e POSTGRES_PASSWORD=biker -e POSTGRES_DB=biker -p 5432:5432 -v biker-pgdata:/var/lib/postgresql/data postgres:17
docker start biker-pg && docker exec biker-pg pg_isready -U biker -d biker

cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then edit .env: ANTHROPIC_API_KEY, DATABASE_URL to use Postgres, SEARCHER_URL + SEARCHER_API_KEY for the searcher (unset → /v1/bike/used/search, /v1/bike/decathlon/search and /v1/bike/allegro/search answer 503)
python scripts/copy_sqlite_to_postgres.py   # once: copy cache.db into the empty Postgres (TODO-028)
python scripts/migrate_bike_details.py   # REQUIRED on an existing cache.db (see below)
uvicorn app.main:app --reload --port 8000
```

**The migration is a hard prerequisite on any pre-existing `cache.db`.** `init_db()`'s `create_all()` never `ALTER`s an existing table, so an older `bike_results` lacks `search_id`/`position`; `repository.save_search` then raises `OperationalError` on every write, and the surrounding `except Exception` keeps the request alive. Result: nothing is cached, the DB-first search branch never hits, and every search runs the full AI pipeline. `repository` singles out this failure (`no such column`/`no such table`) and logs it at **ERROR** naming the remedy rather than letting it blend into routine cache warnings — that line means the migration has not been run here, though it detects rather than fixes. A database migrated by an *intermediate* build has its lowercase brand names repaired automatically: the migration's casing self-heal runs on **every** invocation, so a plain re-run is enough (no `--force`), provided `search_cache` has not been dropped. See `backend/app/DB_MIGRATION.md`.

```bash
# In a second terminal — smoke test the endpoint:
python scripts/test_search.py
```

- **API docs**: http://localhost:8000/docs (auto-generated OpenAPI UI)
- **Python version**: 3.14
- **Database**: `DATABASE_URL` selects it (TODO-028) — unset → SQLite `backend/cache.db`; `postgresql+psycopg://biker:biker@localhost:5432/biker` → the local PostgreSQL 17 in the `biker-pg` Docker container (volume `biker-pgdata`, started by the `app-runner` agent before the backend, shared by every worktree). All access goes through the one SQLAlchemy engine in `app/models.py` — no raw `sqlite3` anywhere in `app/`. `scripts/copy_sqlite_to_postgres.py` copies `cache.db` into Postgres once (FK order, one transaction, sequences reset, per-table row count + checksum verify, orphan rows skipped and listed, `--truncate` / `--verify-only`). A worktree frontend points at its own backend with `BIKER_API_URL=http://localhost:8001 npm run dev -- --port 5174`

## Frontend Setup

```bash
cd frontend
npm install
npm run dev       # dev server on http://localhost:5173
```

```bash
npm run build     # production build → dist/
npm run preview   # serve production build locally
```

- **Dev server**: http://localhost:5173 — requires the backend to be running on port 8000 (Vite proxies `/v1/*` → `http://localhost:8000`)
- **Node version**: v24 / npm 11

## Docker (whole stack)

`docker compose up --build -d` → http://localhost:8080 (backend on 8000, nginx frontend on 8080, searcher (OLX + Decathlon + Allegro) on 8100 — the backend reaches it as `SEARCHER_URL=http://searcher:8100`; the searcher container needs `CLAUDE_CODE_OAUTH_TOKEN` + `SEARCHER_API_KEY` in `searcher/.env` and mounts the same pgpass file). The database is **GCP Cloud SQL**
`biker-pg`, reached through the `cloudsql-proxy` sidecar (gcloud ADC); the password comes only from the gitignored
`backend/gcp-prod-pgpass.conf` (libpq `PGPASSFILE`) — never put it in a URL, `.env.example` or git. The old local Postgres is
the `db` service behind profile `local-db` (5433). Local uvicorn: host proxy on 6543 + `DATABASE_URL`/`PGPASSFILE` in `.env`. Backend image = the Cloud Run image
(`$PORT`, `PLAYWRIGHT_HEADLESS=true`, no secrets). Frontend image: nginx renders `frontend/nginx.conf.template` at start (`PORT`, `BACKEND_URL`
via envsubst; default `http://backend:8000`). Details in `README.md` § Run with Docker.

## Deploy to GCP (TODO-030)

`scripts/deploy.ps1` (PowerShell, by hand) builds + pushes both images to Artifact Registry `europe-central2-docker.pkg.dev/biker-engine-prod/biker`
and deploys two Cloud Run services in `europe-central2`: `biker-backend` (Cloud SQL `biker-pg` over the `/cloudsql/…` unix socket,
`DATABASE_URL` without password, `PGPASSWORD` + `ANTHROPIC_API_KEY` as Secret Manager references `db-password` / `anthropic-api-key`,
service account `biker-run`, 2 vCPU / 2 GiB, timeout 600 s, max 2 instances) and `biker-frontend` (nginx, `BACKEND_URL` = the backend's
`run.app` URL). TODO-031 adds `biker-searcher` (`searcher/Dockerfile`: Node + `claude` CLI + Chromium; 2 vCPU / 2 GiB, `--concurrency 1`, timeout 900 s, same Cloud SQL socket, secrets `searcher-api-key` → `SEARCHER_API_KEY`, `claude-code-oauth-token` → `CLAUDE_CODE_OAUTH_TOKEN`, `db-password` → `PGPASSWORD`); the backend then gets `SEARCHER_URL` = the searcher's `run.app` URL and `SEARCHER_API_KEY` from the same secret. TODO-032 adds the Decathlon route and TODO-033 the Allegro route to that **same** service — same image and secrets, no new service or secret; redeploying `biker-searcher` ships them. Since TODO-033 the searcher runs with `--max-instances 2` (still `--concurrency 1`: one CLI run per 2 GiB instance, plus Chromium only for OLX) because the "Nowe" card fires the Decathlon and Allegro searches together (backend `SEARCHER_MAX_INFLIGHT` = 2); a third concurrent search hits Cloud Run's 429, which the backend maps to 503 busy. `-Only searcher` deploys just that service. The script never touches IAM — public access is a one-time manual binding. Step 2 (not yet done): per-IP rate limit
with 429, budget alerts, `docs/DEPLOYMENT.md`. Details in `README.md` § Deploy to GCP.

## Parallel Development (Worktrees)

Work on multiple features simultaneously — each in its own directory, its own branch, without stashing.

```
C:\Users\kamil_wolny\Projects\
├── biker\             ← main branch (always here)
└── biker-wt\
    ├── feature-xyz\   ← feature/xyz branch
    └── fix-abc\       ← fix/abc branch
```

**Create a new worktree:** `/new-worktree feature/my-feature`
**Check what's running:** `/worktree-status`
**Remove when done:** `git worktree remove C:\Users\kamil_wolny\Projects\biker-wt\feature-my-feature`

Each worktree shares `node_modules` and `.venv` via Junction symlinks (created automatically by `/new-worktree`). If your branch adds new packages, break the junction and run install fresh — the command output explains how.

**Port convention** (for running two worktrees simultaneously):

| Worktree | Backend | Frontend | Searcher |
|----------|---------|----------|----------|
| `biker\` (main) | 8000 | 5173 | 8100 |
| first worktree | 8001 | 5174 | 8101 |
| second worktree | 8002 | 5175 | 8102 |

A worktree backend's `SEARCHER_URL` must point at its own searcher port (`backend/.env` is per checkout).

## Architecture

### Backend (`/backend`)

| Layer | File | Responsibility |
|-------|------|----------------|
| Entry point | `app/main.py` | FastAPI app, routes, request logging |
| Schemas | `app/schemas.py` | Pydantic models: `SearchRequest`, `BikeResult`, `BikeSearchResponse`, `CachedSearchResponse`, `BikeDetailsRequest`, `BikeDetailsResponse`, `BikeCategory`, `BikeSubcategory`, `ComponentElement`, `SpecItem`, `BikeReviewRequest`, `BikeReviewResponse`, `BikeOffer`, `BikeOfferRequest`, `BikeOfferResponse`, `UsedBikeRequest`, `UsedBikeResponse`, `EquipmentDetailsRequest`, `EquipmentDetailsResponse`, `EquipmentReviewRequest`, `EquipmentReviewResponse`, `MissingDataRequest`, `MissingDataResponse` |
| Generic cache | `app/cache.py` | `endpoint_req_to_body_cache` table (a Core `Table` in `models.py`, created by `init_db()`): generic per-endpoint response cache keyed by endpoint + normalised request (`get_cached`/`set_cached`), read/written through the shared engine; `set_cached` is a first-write-wins `ON CONFLICT DO NOTHING` via `models.dialect_insert()` |
| Engine / DB selection | `app/models.py` `get_engine` · `configure_db` · `dialect_insert` | Engine from `DATABASE_URL` (fallback `sqlite:///cache.db` = `DEFAULT_DB_PATH`); SQLite gets `PRAGMA foreign_keys=ON` + WAL per connection, PostgreSQL gets `pool_pre_ping` and session `timezone=UTC`. `configure_db(url_or_path)` repoints it; `dialect_insert(table)` returns the SQLite or PostgreSQL `insert` so upserts work on both. Startup order in `main.py`: `init_db()` → `init_cache()` → `init_store()` |
| Startup hook | `app/store.py` | `init_store()` now **creates nothing** — it owns no tables any more and is kept purely as the app's startup hook (it only logs). **Search and details both moved to `app/repository.py`** (TODO-019) |
| ORM data access | `app/repository.py` · `app/models.py` | SQLAlchemy layer over `bike`/`bike_detail`/`bike_detail_photos`/`bike_detail_component` (+ `bike_offer`/`bike_offer_photos`, live since TODO-031: written by the searcher service, read by `app/offers_repository.py`; the searcher carries a verbatim copy of those three tables' DDL in `searcher/app/models.py` — change the backend's first, then the copy). Note: the description below predates TODO-028 in places (table names `bikes`/`searches`/`bike_results`, `brand_norm`/`model_norm` columns) — `app/models.py` is authoritative. **Live for bike details**: `save_bike_details`/`get_bike_details` are the details cache (30 d TTL from `updated_at + ttl_seconds`; the response echoes the **caller's** casing, and photos are rows ordered by `display_order` rather than a JSON array). `bikes` carries normalised lookup columns `brand_norm`/`model_norm` (`models.norm()` = Python `.strip().lower()`, `UNIQUE(brand_norm, model_norm)`, kept in lockstep by a `@validates("brand", "model")` handler — fires on construction **and** later assignment, but **not** on a bulk `query().update()`) that every identity lookup matches exactly, while `brand`/`model` keep their real casing because the row is shared with search results — they are the **single source of display casing**, so a stored value equal to its own normalised form is treated as a placeholder (the old details blob keyed on `strip().lower()`) and upgraded by the first caller supplying real casing; the rule is monotonic, so lowercase never overwrites real casing and it cannot oscillate. **Normalise in Python, never via SQL `func.lower()`** — SQLite's `lower()` is ASCII-only, so uppercase non-ASCII (`RIESE & MÜLLER`, `Škoda`) misses the lookup and mints a duplicate identity; canonical `Riese & Müller` is unaffected, which is what makes it easy to miss. `models.configure_db(path)` repoints the ORM at another SQLite file, falling back to `models.DEFAULT_DB_PATH` (used by the migration script and the parity test). **Also live for search**: `save_search`/`get_search_by_query`/`find_bikes_by_brand` read and write `searches` (`query` = `norm()`'d enriched query, `UNIQUE`, 24 h TTL from `created_at + ttl_seconds`) + `bike_results` (`search_id` FK `ON DELETE CASCADE`, plus **`position`** preserving the score-weighted rank the old JSON blob carried implicitly — reads `ORDER BY position`). `find_bikes_by_brand` matches `brand_norm` **exactly**, not `ilike` substring — this matches the shipped `store.py` behaviour it replaced. See `backend/app/DB_MIGRATION.md` |
| Missing-data requests | `app/repository.py` `record_missing_request` · `app/models.py` `BikeMissingRequest` | Table `bike_missing_request` (`bike_id` FK → `bike.id`, `missing_type` ≤ 64, `counter`, `UNIQUE(bike_id, missing_type)`) counting "Request data" clicks (TODO-026). Looks the bike up in `bike` by Python-normalised brand/model (never creates it), then one atomic `INSERT … ON CONFLICT DO UPDATE counter = counter + 1` (SQLite or PostgreSQL construct via `models.dialect_insert()`). Created by `init_db()` at startup — no migration step |
| Equipment categories | `app/equipment_categories.py` | 4 equipment category registry (helmets, lights, locks, apparel); loads prompt files at startup; keyword-based `resolve_category()` inference |
| Prompts | `app/prompts/*.md` | `bike_search.md` single-call bike-finding prompt + `bike_details_{slug}.md` per-category component search prompts (8 categories) + `bike_details.md` JSON format reference + `equipment_details_{slug}.md` (4) + `equipment_description.md` / `equipment_photos.md` / `equipment_review.md` |
| Bike finder | `app/bike_finder.py` | **One** Claude Haiku call (no tools, `prompts/bike_search.md`) → every matching `BikeResult` (no cap, min 1 — the closest bike with a low `match_score` when nothing meets every filter; `max_tokens=8000`, warns on `stop_reason == "max_tokens"`), parsed with `extract_json()`; bad JSON → `[]`. Only runs on a DB miss (TODO-024) |
| DB-first search | `app/repository.py` `find_bikes_by_details` | Matches the checkable `SearchRequest` fields (brand, model, frame_material, wheel_size, frame_size, gender, is_electric, battery_capacity_wh, brake_type, drivetrain, belt_drive) against `bike` + `bike_detail_component`; every given field must match, a missing spec row does not match, every match returned (no cap, TODO-025). Rules table in `backend/README.md` § Search Cache |
| Details finder | `app/bike_details_finder.py` | Loops through 8 component categories (Frame → Accessories), runs one focused `web_search` call per category, aggregates results via the shared `extract_json()`; logs per-iteration and total token usage |
| JSON extraction | `app/json_extract.py` | Shared `extract_json()` — lifts the first parseable fenced block or balanced `{...}`/`[...]` out of prose. Used by every finder whose prompt demands raw JSON; the model narrates before the object often enough that a strict parser silently loses whole categories/offers |
| Description finder | `app/bike_description_finder.py` | Single `web_search` call with prompt caching to generate a 4–5 sentence plain-text bike overview **in Polish** (the prompt forces Polish output regardless of the English request/sources); runs in parallel with details finder |
| Review finder | `app/bike_review_finder.py` | Single `web_search` call across curated sources (tier list and weights in `backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md`); synthesises score 0–10, explanation, source URLs, plus a per-source score array from which it computes a weighted aggregate `rating` (0–10) and `sources_used` count (pro/numeric 3×, pro/qualitative 2×, community 1×; non-zero rating requires ≥1 pro source). When the highest and lowest per-source score spread by more than `DISAGREEMENT_THRESHOLD` (3.0), `rating` anchors to the pro/numeric mean (falling back to pro/qualitative) instead of the weighted mean, and a disagreement sentence is appended to `explanation`; `sources_used` is unaffected. `ref` is returned sorted Tier 1 → Tier 2 → Tier 3. Tolerates the model narrating before the JSON via a balanced-brace scan over all text blocks, with a no-tool prefilled repair call as a last resort |
| Stored marketplace offers | `app/offers_repository.py` `_get_stored_offers(company, model, source)` · `get_used_offers` · `get_decathlon_offers` · `get_allegro_offers` · `bike_exists` (all on `repository._find_bike_id`) | TODO-031/032/033: reads `bike_offer` rows for the Python-normalised bike **and one `source`** (`ORDER BY id`) + `bike_offer_photos` (`display_order`); `brand`/`model` on each offer come from the `bike` row (the table has no title column), `is_new` is the row's, `info=""`. `get_used_offers` → `UsedBikeResponse` for `source = 'olx.pl'`; `get_decathlon_offers` → `BikeOfferResponse` for `source = 'decathlon.pl'`; `get_allegro_offers` → `BikeOfferResponse` for `source = 'allegro.pl'` (`ALLEGRO_SOURCE`; `photos: []` — the searcher stores no Allegro photos, `is_new` as the listing said — an Allegro listing is used unless the page said new). Unknown bike / no rows / DB error → empty response, never an error. No TTL. Rows are written only by the searcher service |
| Searcher client | `app/searcher_client.py` | `search_olx(company, model)` → `UsedBikeResponse`, `search_decathlon(company, model)` → `BikeOfferResponse` and `search_allegro(company, model)` → `BikeOfferResponse` — httpx `POST {SEARCHER_URL}{path}` (`SEARCH_PATHS`: `/v1/search/olx` / `/v1/search/decathlon` / `/v1/search/allegro`) with header `X-Searcher-Key` (`SEARCHER_API_KEY`), timeout `SEARCHER_TIMEOUT` (600 s, connect 10 s), the body validated into the route's model. Single-flight per `(path, normalised company, normalised model)` (a second click joins the running search; the task is `asyncio.shield`ed so a disconnect does not cancel it) and at most `SEARCHER_MAX_INFLIGHT` (`DEFAULT_MAX_INFLIGHT` = 2 since TODO-033 — the "Nowe" card fires Decathlon + Allegro together; never more than the searcher's `SEARCHER_MAX_CONCURRENT` / Cloud Run `--max-instances`) distinct searches at once **across the three sources** (one process-wide semaphore); a searcher 503 (its slots taken) **and** Cloud Run's 429 (both instances busy) are `SearcherBusy` too (`BUSY_STATUSES = (503, 429)`) — nothing queues. Raises `SearcherNotConfigured` (URL or key unset) / `SearcherUnavailable` / `SearcherBusy` → 503 (fixed detail strings, the exception text only in the log), `SearcherFailed(status, detail)` → 502 with the searcher's detail (≤ 300 chars). The searcher's `bike_id`/`saved` fields are dropped |
| Browser config | `app/browser_config.py` | `playwright_headless()` — reads `PLAYWRIGHT_HEADLESS` (`true` in the Docker image; unset = visible browser for local debugging); used by every Playwright launch. `BROWSER_SLOTS` — a process-wide `BoundedSemaphore` (`BROWSER_MAX_CONCURRENCY`, default 2, min 1) that every scraper (now only the bike / equipment photo finders — the OLX photo scraper lives in the searcher; Allegro and Decathlon offers carry no photos) holds around `sync_playwright()` + `chromium.launch()`, because each launch costs 0.5–0.9 GiB and nothing else caps how many worker threads scrape at once; without it a burst of uncached details requests OOM-kills the 2 GiB Cloud Run instance |
| Ceneo finder | `app/bike_offer_ceneo_finder.py` | Single `web_search` call to find 1 current offer on ceneo.pl |
| Decathlon house brands | `app/decathlon_brands.py` | TODO-032 (closes `TODO_ISSUE_010`): `DECATHLON_BRANDS` allowlist of normalised tokens (`rockrider`, `btwin`, `triban`, `vanrysel`, `elops`, `riverside`, `stilus`, `tilt`, `decathlon`; normalisation = lower-case, apostrophes `'`/`’`, hyphens, dots and whitespace removed, so `B'Twin` / `B-TWIN` / `Van Rysel` all match), `is_decathlon_brand(company)`, and `not_sold_info(company)` — the Polish `info` sentence `"Decathlon nie sprzedaje marki <X> — w sklepie są tylko marki własne (Rockrider, Btwin, Triban, Van Rysel, Elops, Riverside, Stilus, Tilt)."` returned by `/v1/bike/decathlon/search` for a foreign brand instead of a searcher run. The old `bike_offer_decathlon_finder.py` + `prompts/bike_offer_decathlon.md` moved to the searcher (`searcher/app/decathlon_finder.py`, `searcher/app/prompts/bike_offer_decathlon.md`) |
| Photos finder | `app/bike_photos_finder.py` | Two-step: (1) Claude `web_search` to find manufacturer product page URL, (2) Playwright (`PLAYWRIGHT_HEADLESS`; unset = visible browser) scrapes up to 8 product `<img>` URLs from rendered page; runs in parallel with details and description finders |
| Equipment details finder | `app/equipment_details_finder.py` | Resolves the equipment category (given or inferred), runs one focused component-search call with that category's `equipment_details_{slug}.md` prompt, returns the bike-style component tree (web_search behind a `TODO` flag, mirroring the bike details finder) |
| Equipment description finder | `app/equipment_description_finder.py` | Single `web_search` call with prompt caching for a 4–5 sentence equipment overview |
| Equipment photos finder | `app/equipment_photos_finder.py` | Two-step manufacturer-page → Playwright scrape (mirrors `bike_photos_finder.py`) |
| Equipment review finder | `app/equipment_review_finder.py` | Single `web_search` call → score 0–10, explanation, one source URL (review/forum only, never offers) |
| Test scripts | `scripts/test_search.py` · `scripts/test_details.py` · `scripts/test_review.py` · `scripts/test_equipment.py` · `scripts/test_equipment_review.py` · `scripts/test_details_parity.py` · `scripts/test_browser_slots.py` | Smoke tests for each endpoint (`test_search.py` runs exactly one happy path per endpoint, each on its own seeded fixture — without the API by default: search DB hit + search-cache, details-cache, missing, `case_used` (seeded `bike_offer` row for the DB-only `/v1/bike/used/olx`), `case_decathlon` (seeded `decathlon.pl` row for the DB-only `/v1/bike/decathlon` + unknown bike → fast empty 200), `case_allegro` (TODO-033: seeded `allegro.pl` row — no photo row — for the DB-only `/v1/bike/allegro` — `photos == []`, `is_new`, `city: null`, no generic-cache row under `/v1/bike/offer` or `/v1/bike/allegro`, < 5 s; unknown bike → fast empty 200), `case_used_search` (unknown bike → 404 only — no paid run), `case_allegro_search` (unknown bike → 404 only — no paid run), `case_decathlon_search` (unknown bike → 404, a foreign-brand fixture → instant empty 200 with the Decathlon `info` and no searcher call, then — the **only** paid searcher run in the whole test set, SKIP unless `{SEARCHER_URL}/health` answers — `Decathlon / Rockrider ST 100` live with a DB round-trip through `/v1/bike/decathlon`); `--ai` adds free-text search, parse and Ceneo; the old `test_offer.py` (AI smoke of `/allegro`) is gone with the finder; `test_equipment_review.py` is a focused regression for the equipment-review JSON extraction; `test_details_parity.py` is a pytest asserting the ORM details read path returns a field-for-field identical `BikeDetailsResponse` to the old blob path — casing echo, `components` tree, photo order, staleness — run against a scratchpad copy of `cache.db`) |
| DB migration script | `scripts/migrate_bike_details.py` | One-off, **idempotent** backfill of the legacy `bike_details_cache` blob rows into `bikes` + `bike_details` + `bike_detail_photos`, preserving each row's age (`time_stored` → `updated_at`, `ttl` → `ttl_seconds`) and photo order (array index → `display_order`); also adds + backfills `brand_norm`/`model_norm` on every pre-existing `bikes` row, merges rows sharing a normalised identity, creates the `uq_bike_brand_model_norm` index, and clears test-script leftovers. Placeholder (all-lowercase) casing on `bikes` is repaired on **every** invocation via `_repair_placeholder_casing()` — reported as `casing_repaired` / `placeholders_left`, and impossible once `search_cache` is dropped, since that blob is the only surviving source of real casing. `--force` rebuilds existing details rows; `--db <path>` targets another SQLite file; `--drop-legacy` additionally drops the legacy blob tables (`bike_details_cache`, `search_cache`). Also importable as `migrate(db_path=None, drop_blob_table=False, force=False, verbose=True) -> dict` (the dict's `blob_tables_dropped` is a **list of dropped table names**, not a bool). Dropping is **opt-in from both entry points** — `drop_blob_table=True` or `--drop-legacy` — so a default call from either keeps the blob tables, which the parity tests need to read |

**Endpoint** `POST /v1/bike/search`
- Request: all fields optional, at least one required — `search` (free text), `brand`, `model`, `year` (int), `wheel_size` (string), `is_electric` (bool), `bike_type` (string), `frame_size` (string), `gender` (string), `frame_material` (string), `brake_type` (string), `drivetrain` (string), `belt_drive` (bool), `battery_capacity_wh` (int). `price_max`, `rider_height_cm`, `rider_weight_kg`, `has_suspension` and `is_kids` were **removed** (TODO-023) — Pydantic ignores them if sent, so a payload of only those is a 422
- Structured fields are assembled into an enriched query string via `SearchRequest.enriched_query()` (e.g. `"Brand: Trek, Type: Gravel, Year: 2023 — trail riding"`); all fields participate in the SQLite cache key in `main.py`
- **Cascade (TODO-024)**: (1) generic cache → (2) **DB details search** `repository.find_bikes_by_details(req)` — a bike matches when every given *checkable* field matches its `bike` / `bike_detail_component` rows; `bike_type`, `year` and free-text `search` are not checkable and ignored. ≥1 match returns **all** those bikes (no cap, TODO-025) with **zero** AI calls and **no** `set_cached`. A request with only non-checkable fields skips the DB → (3) **one** Claude call via `bike_finder.find_bikes(enriched)` returning every matching bike, min 1 (closest match with a low score and an explanation naming the unmet filter)
- DB-hit `match_score`/`explanation`/`accessories` come from the bike's latest `search_bike_rating_cache` row; otherwise score 10, `accessories=[]`, explanation in Polish, `"Pasuje: rama karbonowa, koła 29\", …"`
- The category pipeline (11 scoring calls + per-category finders, `categories.py`, `anthropic_scorer.py`, `CategoryResult`) was **removed** in TODO-024
- Returns `{ search, bikes: [{ brand, model, accessories, match_score, explanation }] }` — shape unchanged; `search` is the enriched query. `explanation` and `accessories` are Polish (brand/model and named components such as "Shimano GRX" stay untranslated)
- On parse error: returns an empty list — never a 502 for bad JSON (an upstream API error is a 502). The AI result is cached (`set_cached` + `store.save_search`) only when non-empty

**Endpoint** `GET /v1/bike/search-cache` (follow-up, cache-only — no web/Claude call)
- `?query=<enriched query>` → `CachedSearchResponse` from `searches` + `bike_results` for an exact normalised repeat; 404 if missing/stale (24 h TTL); bikes returned in original score-weighted order (`ORDER BY position`)
- `?brand=<brand>` → every de-duplicated bike of that brand across all fresh cached searches (lookup-by-attribute via `find_bikes_by_brand`). **Exact** `brand_norm` match — a partial brand name does not match, which is the behaviour the live `store.py` implementation always had
- 422 if neither `query` nor `brand` is given

**Endpoint** `GET /v1/bike/details-cache` (follow-up, cache-only — no web/Claude call)
- `?company=<company>&model=<model>` → `BikeDetailsResponse` from the ORM details tables via `repository.get_bike_details`; 404 if missing/stale (30 d TTL). Lookup matches the normalised `bikes.brand_norm`/`model_norm` columns, so casing and surrounding whitespace do not matter; the response echoes the caller's casing

**Endpoint** `POST /v1/bike/missing` (TODO-026 — no AI call, no generic cache)
- Request: `{"company": "Trek", "model": "Marlin 5", "missing_type": "photos"}` — `company`/`model` non-empty; `missing_type` a free string (the enum lives in the frontend, TODO-027), stripped, non-empty, max 64 chars, else 422
- Upserts `bike_missing_request` for the existing `bike` row: first request `counter = 1`, each later one +1 (no spam protection — the frontend stops repeat clicks)
- Returns `{ bike_id, missing_type, counter }`. Bike not in `bike` (only after a swallowed `save_search` failure) → ERROR log, **200** `{ bike_id: null, missing_type, counter: 0 }`, nothing written

**Endpoint** `POST /v1/bike/details`
- Request: `{"company": "Canyon", "model": "Grizl CF 7 ESC"}`
- Runs three calls in parallel via `asyncio.gather`:
  1. `claude-haiku-4-5-20251001` with `web_search_20250305` **8 times** sequentially — one focused search per component category (Frame, Drivetrain, Brakes, Wheels, Cockpit, Saddle & Seatpost, Lighting, Accessories), each using a dedicated `app/prompts/bike_details_{slug}.md` system prompt
  2. `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — generates a 4–5 sentence plain-text overview **in Polish** using `app/prompts/bike_description.md` with prompt caching on the system prompt
  3. `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — finds the official manufacturer product page URL, then Playwright (`PLAYWRIGHT_HEADLESS`; unset = visible browser) scrapes up to 8 product `<img>` URLs from the rendered page; uses `app/prompts/bike_photos.md`
- Returns: `{ company, model, description: str, components: [...], photos: [url, ...] }` — `description` and every component element `description` are Polish; `category`, `subcategory`, spec `key`, element `name` and spec `value` stay English (the frontend translates labels via `specLabels.ts`; DB-first search matches values — its brake patterns also carry Polish stems)
- Each category response is parsed with the shared `app/json_extract.py` `extract_json()`, which lifts the JSON out of any surrounding narration/code fence — the model routinely prefaces the object with prose
- If a response genuinely contains no JSON: logs the error and skips that category — never returns 502
- Happy path also writes the result to the ORM tables `bikes` + `bike_details` + `bike_detail_photos` via `repository.save_bike_details(company, model, response)` (30 d TTL from `updated_at + ttl_seconds`; reads match the normalised `bikes.brand_norm`/`model_norm` columns, photos stored as rows ordered by `display_order`). Payload shape is unchanged — see `backend/app/DB_MIGRATION.md`

**Endpoint** `POST /v1/bike/review`
- Request: `{"company": "Canyon", "model": "Grizl CF 7 ESC"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches the curated review sources (tier list and weights in `backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md`), using `app/prompts/bike_review.md` as the system prompt; returns per-source scores tagged by type
- Backend computes a weighted aggregate `rating` (0–10) from the per-source scores: pro/numeric 3×, pro/qualitative 2×, community 1×, normalised; a non-zero rating requires ≥1 professional source
- Source disagreement: if the spread between the highest and lowest per-source score exceeds `DISAGREEMENT_THRESHOLD` (3.0, module-level constant), `rating` anchors to the mean of the pro/numeric scores instead (falling back to pro/qualitative if none), and the backend appends a (Polish) sentence to `explanation` stating the spread and which camp the rating follows; `sources_used` still counts every consulted source regardless
- Returns `{ score: int (0–10), explanation: str (5–10 sentences), ref: [url, ...] (sorted Tier 1 → Tier 2 → Tier 3), rating: float (0–10), sources_used: int }`
- The parser scans **every** text block for the first balanced `{...}` (the model often narrates before emitting the JSON, sometimes inside a ```json fence) and strips `<cite>` markup from the explanation
- If no JSON object is found at all, a **repair pass** re-sends the gathered findings with no tools and an assistant prefill of `{`, forcing a JSON-only reply rather than wasting the completed web search
- Cache: keyed on `{company, model}`; stored only when `ref` is non-empty **and** `sources_used >= 1`, so a degenerate `rating: 0.0` row cannot be pinned for that bike
- `explanation` is written in Polish (`app/prompts/bike_review.md` § Language)
- On JSON parse error: returns `{ score: 0, explanation: "Recenzja niedostępna.", ref: [], rating: 0.0, sources_used: 0 }` — never returns 502

**Endpoint** `POST /v1/bike/allegro` (TODO-033 — pure DB read, no AI, no generic cache)
- Request: `{"company": "Trek", "model": "Marlin 5"}` — both non-empty, ≤ 255 chars (422 otherwise)
- Returns the allegro.pl offers stored for that bike in `bike_offer` (`source = 'allegro.pl'`, `ORDER BY id`) via `offers_repository.get_allegro_offers`: `{ offers: [{ brand, model, price, is_new (the row's — false unless the listing said new), url, photos: [] (the searcher stores no Allegro photos), source: "allegro.pl", city: null }], info: "" }`; `brand`/`model` are the `bike` row's. Unknown bike or nothing stored → **200** `{ offers: [], info: "" }` (the frontend then shows the "Poproś o dane" button in the "Nowe" card). No TTL — rows stay until the next search replaces them
- The rows are written only by the searcher service, i.e. through the endpoint below. The former `web_search` finder is gone (`app/bike_offer_finder.py` and `app/prompts/bike_offer_allegro.md` moved to the searcher; `app/allegro_image_fetcher.py` was deleted without a replacement — the Allegro photo scrape was dropped, see the search endpoint below; `test_offer.py`, `test_offer_prompt.py`, `test_offer_images.py` and `prompts/allegro_image_extractor_prompt.md` deleted); the generic-cache rows it wrote under the old key `/v1/bike/offer` are dead — nothing reads them and there is no backfill (`_ALLEGRO_CACHE_KEY` is gone)

**Endpoint** `POST /v1/bike/allegro/search` (TODO-033 — on-demand Allegro search, never cached)
- Request: `{"company": "Trek", "model": "Marlin 5"}` (same validation as above)
- Order of checks: (1) **404** `"Bike not found"` when the bike is not in `bike` (`offers_repository.bike_exists`, **before** any searcher call — anonymous traffic must not mint bike rows or spend subscription runs); (2) proxies to the searcher: `POST {SEARCHER_URL}/v1/search/allegro` with `X-Searcher-Key: {SEARCHER_API_KEY}` and waits up to `SEARCHER_TIMEOUT` (600 s). The searcher runs `claude -p` once (subscription token, prompt `searcher/app/prompts/bike_offer_allegro.md`, message `Find current offers on allegro for: {company} {model}`, ≤ 3 offers with `url` on `https://allegro.pl/` or `https://www.allegro.pl/`, `is_new` from the listing — default false, `photos: []`, `city: null`, **no Playwright**), **replaces** that bike's `allegro.pl` rows in `bike_offer` (bike row created if missing; OLX and Decathlon rows untouched) and returns them. **No photos by design**: allegro.pl answers HTTP 403 to every automated fetch — the CLI's WebFetch and Chromium alike — so the prompt works from WebSearch results only (and is therefore not byte-identical to the SDK-era one), and the Playwright gallery scrape that shipped with the first cut (`searcher/app/allegro_image_fetcher.py`, DataDome warm-up) was removed on the user's decision after the 2026-09-26 probes returned 0 photos from it: nothing to gain, ~10 s and a browser launch per run wasted. Probe 2026-09-26 (`Trek Marlin 5`): with the CLI-tuned prompt 3 real offers in 67–75 s (Kross Level 3.0, Trek Marlin 4; the SDK-era prompt needed 286 s or gave up empty)
- Returns `{ offers: [...], info: str }` — the same shape as `/v1/bike/allegro`; a search that found nothing is a 200 with `offers: []`
- **503** when `SEARCHER_URL`/`SEARCHER_API_KEY` are unset, the searcher is unreachable/times out, or the searches in flight are already at the cap (fixed details `"Allegro searcher is not configured"` / `"Allegro searcher unavailable"` / `"Allegro searcher is busy — try again in a moment"`; the backend's `SEARCHER_MAX_INFLIGHT` = 2 and the searcher's slots are **shared across OLX, Decathlon and Allegro** — the "Nowe" card's pair fits, a third concurrent search is refused, and Cloud Run's 429 counts as busy too — nothing queues); **502** with the searcher's detail when it fails (CLI error, DB error). Identical concurrent requests share one search (single-flight, keyed on path + bike)
- Same persistence rules as OLX: `bike_offer.url` is globally unique, the upsert is scoped to `(bike_id, source = 'allegro.pl')`, so a URL already stored under another bike or source stays there and is not returned; a search that finds **nothing keeps** the rows already stored
- Triggered only by the frontend's **Poproś o dane** button in the "Nowe" offers card, **together with** `/v1/bike/decathlon/search` (`Promise.allSettled`; the click also records `offers_new` via `/v1/bike/missing`) — never automatically. A used listing (`is_new: false`) then lands in the "Używane" card through the UI's `is_new` split

**Endpoint** `POST /v1/bike/used/olx` (TODO-031 — pure DB read, no AI, no generic cache)
- Request: `{"company": "Trek", "model": "Marlin 5"}` — both non-empty, ≤ 255 chars (422 otherwise)
- Returns the OLX listings stored for that bike in `bike_offer` (`source = 'olx.pl'`, `ORDER BY id`) + `bike_offer_photos` (`display_order`) via `offers_repository.get_used_offers`: `{ offers: [{ brand, model, price, is_new: false, url, photos, source: "olx.pl", city }], info: "" }`; `brand`/`model` are the `bike` row's. Unknown bike or nothing stored → **200** `{ offers: [], info: "" }` (the frontend then shows the "Poproś o dane" button). No TTL — rows stay until the next search replaces them
- The rows are written only by the searcher service, i.e. through the endpoint below

**Endpoint** `POST /v1/bike/used/search` (TODO-031 — on-demand OLX search, never cached)
- Request: `{"company": "Trek", "model": "Marlin 5"}` (same validation as above)
- Proxies to the searcher service: `POST {SEARCHER_URL}/v1/search/olx` with `X-Searcher-Key: {SEARCHER_API_KEY}` and waits up to `SEARCHER_TIMEOUT` (600 s). The searcher runs `claude -p` once (subscription token, prompt `searcher/app/prompts/bike_offer_olx.md`, cascade fallback exact → model-family → brand/category, ≤ 5 listings) and Playwright once per listing (≤ 4 `*.apollo.olxcdn.com` photos), **replaces** that bike's OLX rows in `bike_offer` / `bike_offer_photos` (bike row created if missing) and returns them
- Returns `{ offers: [...], info: str }` — the same shape as `/v1/bike/used/olx`; a search that found nothing is a 200 with `offers: []`
- **404** `"Bike not found"` when the bike is not in `bike` (checked with `offers_repository.bike_exists` **before** any searcher call — anonymous traffic must not mint bike rows or spend subscription runs); **503** when `SEARCHER_URL`/`SEARCHER_API_KEY` are unset, the searcher is unreachable/times out, or the searches in flight are already at the cap (backend `SEARCHER_MAX_INFLIGHT` = 2, shared with `/v1/bike/decathlon/search` and `/v1/bike/allegro/search`, and the searcher's own 503 "busy" / Cloud Run's 429 — nothing queues); **502** with the searcher's detail when it fails (CLI error, DB error). Identical concurrent requests share one search (single-flight)
- The searcher never re-parents a listing: `bike_offer.url` is globally unique and the prompt's cascade returns model-family listings, so a URL already stored under another bike stays there and is not returned; a search that finds **nothing keeps** the rows already stored (an OLX hiccup must not wipe paid-for data)
- Triggered only by the frontend's **Poproś o dane** button in the "Używane" offers card (which also records the click via `/v1/bike/missing`) — never automatically

**Endpoint** `POST /v1/bike/ceneo`
- Request: `{"company": "Canyon", "model": "Grizl CF 7 ESC"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches ceneo.pl using `app/prompts/bike_offer_ceneo.md` as the system prompt
- Returns `{ offers: [{ brand, model, price, is_new, url, photos: [], source: "ceneo.pl" }], info: str }` (1 offer, no photos)
- On JSON parse error: returns `{ offers: [], info: raw_text }` — never returns 502

**Endpoint** `POST /v1/bike/decathlon` (TODO-032 — pure DB read, no AI, no generic cache)
- Request: `{"company": "Rockrider", "model": "ST 100"}` — both non-empty, ≤ 255 chars (422 otherwise; `BikeOfferRequest` now carries `max_length=255` because the values reach the searcher's prompt)
- Returns the decathlon.pl offers stored for that bike in `bike_offer` (`source = 'decathlon.pl'`, `ORDER BY id`) via `offers_repository.get_decathlon_offers`: `{ offers: [{ brand, model, price, is_new (the row's — default true), url, photos: [], source: "decathlon.pl", city: null }], info: "" }`; `brand`/`model` are the `bike` row's. Unknown bike or nothing stored → **200** `{ offers: [], info: "" }` (the frontend then shows the "Poproś o dane" button in the "Nowe" card). No TTL — rows stay until the next search replaces them
- The rows are written only by the searcher service, i.e. through the endpoint below. The former `web_search` finder and its generic-cache rows are gone (`app/bike_offer_decathlon_finder.py` and `app/prompts/bike_offer_decathlon.md` were deleted; the prompt moved byte-identical to `searcher/app/prompts/`)

**Endpoint** `POST /v1/bike/decathlon/search` (TODO-032 — on-demand Decathlon search, never cached)
- Request: `{"company": "Rockrider", "model": "ST 100"}` (same validation as above)
- Order of checks: (1) **404** `"Bike not found"` when the bike is not in `bike` (`offers_repository.bike_exists`, **before** anything else); (2) **200** `{ offers: [], info: not_sold_info(company) }` **immediately, without any searcher call**, when `company` is not a Decathlon house brand per `app/decathlon_brands.py` (closes `TODO_ISSUE_010` — Decathlon sells only Rockrider, Btwin, Triban, Van Rysel, Elops, Riverside, Stilus, Tilt; the Polish `info` names them); (3) otherwise proxies to the searcher: `POST {SEARCHER_URL}/v1/search/decathlon` with `X-Searcher-Key: {SEARCHER_API_KEY}` and waits up to `SEARCHER_TIMEOUT` (600 s). The searcher runs `claude -p` once (subscription token, prompt `searcher/app/prompts/bike_offer_decathlon.md`, message `Find current offers on decathlon.pl for: {company} {model}`, ≤ 3 offers with `url` on `https://www.decathlon.pl/`, `is_new` from the page — default true, `photos: []`, `city: null`, **no Playwright**), **replaces** that bike's `decathlon.pl` rows in `bike_offer` (bike row created if missing; OLX rows untouched) and returns them
- Returns `{ offers: [...], info: str }` — the same shape as `/v1/bike/decathlon`; a search that found nothing is a 200 with `offers: []`
- **503** when `SEARCHER_URL`/`SEARCHER_API_KEY` are unset, the searcher is unreachable/times out, or a search is already running (fixed details `"Decathlon searcher is not configured"` / `"Decathlon searcher unavailable"` / `"Decathlon searcher is busy — try again in a moment"`; the backend's `SEARCHER_MAX_INFLIGHT` = 2 and the searcher's busy slots are both **shared with the OLX and Allegro searches** — the "Nowe" card's Decathlon + Allegro pair fits, a third concurrent search is refused, nothing queues); **502** with the searcher's detail when it fails (CLI error, DB error). Identical concurrent requests share one search (single-flight, keyed on path + bike)
- Same persistence rules as OLX: `bike_offer.url` is globally unique, the upsert is scoped to `(bike_id, source = 'decathlon.pl')`, so a URL already stored under another bike or source stays there and is not returned; a search that finds **nothing keeps** the rows already stored
- Triggered only by the frontend's **Poproś o dane** button in the "Nowe" offers card, **together with** `/v1/bike/allegro/search` since TODO-033 (the click also records `offers_new` via `/v1/bike/missing`) — never automatically

**Endpoint** `POST /v1/bike/parse`
- Request: `{"text": "Looking for Trek Marlin 7 2022, 29 inch wheels"}` — `text` required, non-empty (422 otherwise)
- Calls `claude-haiku-4-5-20251001` **once**, no tools, with `app/prompts/bike_parse.md`; extracts 5 of the 14 `SearchRequest` fields (`brand`, `model`, `year`, `wheel_size`, `is_electric`). Rider height/weight, suspension and kids are **not** extracted (TODO-023), so text mentioning only those is an empty parse → 400
- Returns `ParseResponse` — every field `Optional`, unextracted ones `null`
- **400 `"Bike not available in our database"` when `ParseResponse.is_empty()`** (all fields `null`). The frontend renders this as a warning above the search box and skips the search entirely. The guard runs on the cache-hit path too, so an all-`null` row cached by an older build is still rejected; empty parses are never cached
- Called only by `frontend/src/App.tsx` `handleSearch`, and only when free text is present with no structured filter set — `/v1/bike/search` never parses

**Endpoint** `POST /v1/equipment/details`
- Request: `{"company": "POC", "model": "Octal MIPS", "category": "helmets"}` — `company` optional (default `""`), `model` required, `category` optional (`helmets` / `lights` / `locks` / `apparel`; inferred from the item name when omitted, defaulting to `apparel`)
- Runs three calls in parallel via `asyncio.gather` (mirrors `/v1/bike/details`):
  1. `claude-haiku-4-5-20251001` **once** — one focused component search using the resolved category's `app/prompts/equipment_details_{slug}.md` prompt (web_search behind a `TODO` flag, like the bike details finder)
  2. `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — 4–5 sentence overview using `app/prompts/equipment_description.md` with prompt caching
  3. `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — finds the manufacturer product page URL, then Playwright (`PLAYWRIGHT_HEADLESS`; unset = visible browser) scrapes up to 8 product `<img>` URLs; uses `app/prompts/equipment_photos.md`
- Returns `{ company, model, category, description, components: [...], photos: [...] }` — **never** any offer/buy links
- Cache: keyed on `{company, model, category}`; always cached (empty is valid)
- On JSON parse error for the category: logs and skips — never returns 502

**Endpoint** `POST /v1/equipment/review`
- Request: `{"company": "POC", "model": "Octal MIPS"}` — `company` optional, `model` required
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches 3–5 reviews using `app/prompts/equipment_review.md`; review/forum source links only, never offer links
- Returns `{ score: int (0–10), explanation: str, ref: [url, ...] }`
- Cache: keyed on `{company, model}`; cached only when `ref` is non-empty
- On JSON parse error: returns `{ score: 0, explanation: "Review unavailable.", ref: [] }` — never returns 502

**Equipment categories** (defined in `app/equipment_categories.py`):
Helmets, Lights & electronics, Locks & security, Apparel/bags & accessories. **No** equipment offer endpoints exist — equipment has details + review only, never buy/offer links.


### Frontend (`/frontend`)

| Layer | File | Responsibility |
|-------|------|----------------|
| Entry point | `src/main.tsx` | React root, mounts `<App>` |
| App shell | `src/App.tsx` | View router (`search` / `details` / `equipment`), search, details, review, allegro offer, decathlon offer & used-bike state, plus equipment details/review state; all API calls. `searchUsedBikes` (TODO-031) POSTs `/v1/bike/used/search`, throws on non-OK, and writes the offers into `usedBikes` **without** flipping `usedBikeState` to `loading` (the button shows its own spinner); `searchDecathlon` (TODO-032) mirrors it for `/v1/bike/decathlon/search` → `decathlonOffers` + `'loaded'`, again without `'loading'`; `searchAllegro` (TODO-033) mirrors it for `/v1/bike/allegro/search` → `offers` + `'loaded'`; `searchNew` = `Promise.allSettled([searchDecathlon, searchAllegro])` — each search sets its own state as it returns, so rows from either source replace the button as they arrive, and it rejects (button clickable again) only when **both** rejected, rethrowing the first failure (one failure next to an empty result reads as "no offers"); a `selectedBikeRef` guard drops a result of any search that lands after the user opened another bike. On opening the details view one generic `fetchStoredOffers<T>(path, bike, setData, setState)` POSTs the three DB reads `/v1/bike/allegro`, `/v1/bike/used/olx` and `/v1/bike/decathlon` — all fast, no AI. A free-text-only submit first calls `/v1/bike/parse`: extracted fields populate the Filters panel and the search waits for a second submit, while a **400** renders a "Not found" warning above the search box and stops there. Clicking a component element name in a bike's spec tree opens the equipment view for that item |
| Search form | `src/components/SearchInput.tsx` | Controlled input + submit button + collapsible Filters panel (Basic group: brand, model, bike type, year, wheel size, frame size + electric toggle; Advanced group: gender, frame material, brake type, drivetrain, belt drive + battery capacity shown only when electric); loading state |
| Result card | `src/components/ResultCard.tsx` | Clickable per-bike card: match score, brand + model, accessories chips, explanation, score bar |
| Loading card | `src/components/LoadingCard.tsx` | Shimmer skeleton matching result card dimensions |
| Details view | `src/components/BikeDetailsView.tsx` | Full spec sheet: back nav, bike header, Overview, unified Offers (MergedOffersSection — pools all three sources Allegro/Decathlon/OLX — Ceneo is no longer called by the UI and splits by each offer's `is_new` flag into two stacked cards: Used on top, New below, each sorted cheapest-first via `OfferCategoryCard`/`OfferRow`), Expert Review, component tree whose element names are clickable → equipment view. Reuses shared building blocks from `BikeDetailsShared.tsx` (component-element links are enabled by passing `onElementSelect`). **Request data (TODO-027):** each section (photos, overview, component tree, review, Used card, New card) shows its loading state for `REQUEST_BUTTON_DELAY_MS` (5 s, via the local `useLoadingGrace` hook); after that — or on an empty/failed response — a section without data renders `RequestDataButton` with its `MissingType`, while the request keeps running and late data replaces the button. `MergedOffersSection` no longer returns `null` when both lists are empty. The **Used** card's button additionally receives `onRequested={onSearchUsed}` + `pendingLabel="Szukam na OLX…"` (TODO-031) and the **New** card's `onRequested={onSearchNew}` + `pendingLabel="Szukam na Allegro i Decathlon…"` (TODO-032/033): the click runs the on-demand OLX search, or the Decathlon **and** Allegro searches in parallel, and the returned rows replace the button (`onSearchUsed` / `onSearchNew` props are threaded `BikeDetailsView` → `MergedOffersSection` → `OfferCategoryCard`). The New card offers `onRequested` only while **neither** Decathlon nor Allegro rows are stored (`hasNewSourceRows` — an `allegro.pl` row sitting in the Used card counts too), otherwise the button is a plain counter click, so a stored result never triggers a second paid run |
| Request data button | `src/components/RequestDataButton.tsx` | Shared "We don't have this data yet" + **Request data** button (`card` variant with section eyebrow, dashed border; `inline` variant inside an offer card). Click → `POST /v1/bike/missing` `{company, model, missing_type}` → disabled "Requested ✓"; a failed POST returns it to clickable. With the optional `onRequested` / `pendingLabel` props (TODO-031 Used card, TODO-032/033 New card) the click also awaits that action: spinner + "Szukam na OLX…" / "Szukam na Allegro i Decathlon…" while it runs, "Nie znaleziono ofert" (disabled) if it resolves with the button still mounted (in the New card that means both searches came back empty — for a non-Decathlon brand only Allegro actually runs), clickable again if it throws (New card: when a search failed and neither brought rows — both failed, or one failed while the other came back empty); a failed `/missing` POST does not stop the search. Component state only, no `localStorage`. Not used by the equipment view |
| Equipment details view | `src/components/EquipmentDetailsView.tsx` | Equipment spec page: back nav, category eyebrow + item header, Overview, Expert Review, component tree, shimmer skeleton, error + retry, graceful empty state. **No** offers/used sections. Reuses `BikeDetailsShared.tsx` |
| Shared details building blocks | `src/components/BikeDetailsShared.tsx` | `PhotoGallery`, `DescriptionCard`, `ReviewSection`, `LoadingSkeleton`, `CategorySection` — shared by both the bike and equipment detail views. `DescriptionCard` renders its sources via `CitationChips`; `ReviewSection` renders its `ref[]` as a full-width source table below the explanation — one row per source, `stars | domain | "Read review →"`, stars mapped 0–10 → 1–5 from the aggregate `rating` (falling back to `score` for equipment reviews, which have none). The `rating` / `sources_used` values are never rendered on their own — the section is header + explanation + Sources table only |
| Citation chips | `src/components/CitationChips.tsx` | Google-AI-Overview-style "Sources" row: terracotta pill links showing each source's domain (`target="_blank"`, full URL as hover tooltip). Accepts structured `citations: DescriptionCitation[]` (overview) or a bare `urls: string[]` (review `ref[]`) |
| Spec labels | `src/specLabels.ts` | `translateLabel()` — Polish display labels for the component tree's category, subcategory and spec-key names (dictionary + `Front`/`Rear`/`Max` prefix and `(…)` qualifier handling, English fallback). Used by `CategorySection` |
| Shared types | `src/types.ts` | `Bike`, `BikeCategory`, `BikeSubcategory`, `ComponentElement`, `SpecItem`, `BikeDetailsResponse`, `BikeDescription`, `TextSegment`, `DescriptionCitation`, `BikeReviewResponse`, `BikeOffer`, `BikeOfferResponse`, `UsedBikeResponse`, `EquipmentDetailsResponse`, `EquipmentReviewResponse`, `EquipmentDetailsPayload`, `EquipmentReviewPayload`, `SearchPayload`, `SearchFilters` (+ `EMPTY_FILTERS`), `ParseResponse`, `MissingType` (const + type: `photos` / `description` / `components` / `review` / `offers_new` / `offers_used`), `MissingDataRequest`, `MissingDataResponse` |
| Styles | `src/index.css` | Tailwind v4 `@theme` tokens, Google Fonts import, keyframe animations |
| Vite config | `vite.config.ts` | Tailwind v4 plugin, `/v1` proxy to backend |

**UI language: Polish.** All user-visible frontend strings are Polish, hard-coded (no i18n library); `index.html` has `lang="pl"`. Filter `<select>` options in `SearchInput.tsx` are `{ value, label }` — `value` stays English (the backend matches it), only `label` is Polish. A `/v1/bike/parse` 400 shows a fixed Polish message rather than the backend's English `detail`. Spec-tree labels (category / subcategory / spec key) are translated at render time by `src/specLabels.ts` `translateLabel()` — a dictionary with English fallback; spec values and component names stay as the backend returned them. See `frontend/README.md` for the English→Polish label map of the "Request data" UI.

**Design system — Direction 5 "Café Rider":**
- Background `#EDE7DC` · Cards `#F5F1EA` · Accent `#C45C38` (terracotta)
- Display font: Barlow Condensed Bold · Body: Lora · Data labels: JetBrains Mono
- All theme tokens live in `src/index.css` under `@theme { --color-*, --font-* }`

**API integration:**
- `POST /v1/bike/search` `SearchPayload` (free text `search` plus any structured filters — see backend endpoint) → `{ search, bikes: [{ brand, model, accessories, match_score, explanation }] }` (all found, min 1; `bikes: []` only on a parse failure → the results section shows "Not found")
- `POST /v1/bike/details` `{ "company": "...", "model": "..." }` → `{ company, model, description: BikeDescription, components: BikeCategory[] }`
- `POST /v1/bike/review` `{ "company": "...", "model": "..." }` → `{ score, explanation, ref: string[], rating: number (0–10 aggregate), sources_used: number }`
- `POST /v1/bike/allegro` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (allegro.pl offers **stored in the DB** — no AI call, TODO-033; empty until a search has run; always `photos: []` — the searcher stores no Allegro photos — and `is_new` as the listing said — false unless it said new, so an Allegro offer can land in either card)
- `POST /v1/bike/decathlon` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (decathlon.pl offers **stored in the DB** — no AI call, TODO-032; empty until a search has run; `is_new` as the shop page reported it, true unless outlet/refurbished, so they normally land in the New card)
- `POST /v1/bike/used/olx` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (OLX listings **stored in the DB** — no AI call; empty until a search has run; each with optional `city`)
- `POST /v1/bike/used/search` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` — the on-demand OLX search through the searcher service (TODO-031), sent only by the Used card's **Poproś o dane** button alongside `/v1/bike/missing`; 503 = searcher not configured / unreachable / busy, 502 = searcher failed (the button becomes clickable again)
- `POST /v1/bike/decathlon/search` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` — the on-demand Decathlon search through the same searcher service (TODO-032), sent only by the New card's **Poproś o dane** button alongside `/v1/bike/missing` (`offers_new`) and `/v1/bike/allegro/search`; a non-Decathlon brand gets an instant 200 `offers: []` with a Polish `info` and no searcher run; 404 = unknown bike, 503 = searcher not configured / unreachable / busy, 502 = searcher failed
- `POST /v1/bike/allegro/search` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` — the on-demand Allegro search through the same searcher service (TODO-033), fired by the New card's **Poproś o dane** button **concurrently** with `/v1/bike/decathlon/search` (`searchNew`, `Promise.allSettled`); returned offers carry no photos (`photos: []` by design) and land in the New or Used card by `is_new`. 404 = unknown bike, 503 = searcher not configured / unreachable / busy (a third concurrent search of any source), 502 = searcher failed. The button shows "Nie znaleziono ofert" only when both searches came back empty and becomes clickable again when a search failed and neither brought rows (both failed, or one failed — e.g. 503 busy — while the other was empty); an Allegro offer whose price no search snippet showed is stored with `price: ""` and rendered as "cena w ofercie"
- `POST /v1/bike/parse` `{ "text": "..." }` -> `ParseResponse` (5 optional fields); **400** `"Bike not available in our database"` when nothing is extracted -> App.tsx shows a warning above the search box and skips the search
- `POST /v1/bike/missing` `{ "company": "...", "model": "...", "missing_type": MissingType }` → `{ bike_id: number | null, missing_type, counter }` — sent by `RequestDataButton` in the bike details view (TODO-027); the counter is never shown in the UI
- `POST /v1/equipment/details` `{ "company"?, "model", "category"? }` → `{ company, model, category, description: BikeDescription, components: BikeCategory[], photos: string[] }` (no offer links)
- `POST /v1/equipment/review` `{ "company"?, "model" }` → `{ score, explanation, ref: string[] }` (review/forum links only)
- All endpoints proxied to backend via Vite — no CORS config needed in development
