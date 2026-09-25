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
User: "Add Decathlon offer endpoint"

1. Invoke /sparc:code
   → Specification → Pseudocode → Implementation → Testing phases
   → Creates app/bike_offer_decathlon_finder.py + POST /v1/bike/decathlon route

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

**New backend endpoint** → add a smoke test for it in `backend/scripts/test_search.py`. This is the single file for all smoke tests. Each test must call the endpoint against a running local server and assert HTTP 200.

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
This mirrors the pattern used by `/v1/bike/used`.

## Documentation Update Policy

After **every code change**, review and update the relevant documentation before considering the task done:

| What changed | Files to review & update |
|---|---|
| Any change | `CLAUDE.md` · `README.md` |
| Backend (`/backend/**`) | `backend/README.md` · `README.md` · `CLAUDE.md` |
| Frontend (`/frontend/**`) | `frontend/README.md` · `README.md` · `CLAUDE.md` |

Update only the sections that are actually affected — do not rewrite docs that remain accurate.

**`backend/README.md` must always contain an `## Endpoints` section** with every endpoint listed, including:
- A raw HTTP request example (`POST http://localhost:8000/...` with `Content-Type` and JSON body)
- A **Flow** list of every outbound HTTP call made (exact URL, service name, and how many times / in what order)

## Project Overview

Monorepo with separate backend and frontend applications:
- `/backend` — Python REST API (FastAPI)
- `/frontend` — React + TypeScript + Tailwind v4 SPA (Vite)

## Backend Setup

```bash
# Database — local PostgreSQL 17 in Docker (first time: docker run …; later: docker start biker-pg)
docker run -d --name biker-pg -e POSTGRES_USER=biker -e POSTGRES_PASSWORD=biker -e POSTGRES_DB=biker -p 5432:5432 -v biker-pgdata:/var/lib/postgresql/data postgres:17
docker start biker-pg && docker exec biker-pg pg_isready -U biker -d biker

cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then edit .env: ANTHROPIC_API_KEY, and DATABASE_URL to use Postgres
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

`docker compose up --build -d` → http://localhost:8080 (backend on 8000, nginx frontend on 8080). The database is **GCP Cloud SQL**
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
`run.app` URL). The script never touches IAM — public access is a one-time manual binding. Step 2 (not yet done): per-IP rate limit
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

| Worktree | Backend | Frontend |
|----------|---------|----------|
| `biker\` (main) | 8000 | 5173 |
| first worktree | 8001 | 5174 |
| second worktree | 8002 | 5175 |

## Architecture

### Backend (`/backend`)

| Layer | File | Responsibility |
|-------|------|----------------|
| Entry point | `app/main.py` | FastAPI app, routes, request logging |
| Schemas | `app/schemas.py` | Pydantic models: `SearchRequest`, `BikeResult`, `BikeSearchResponse`, `CachedSearchResponse`, `BikeDetailsRequest`, `BikeDetailsResponse`, `BikeCategory`, `BikeSubcategory`, `ComponentElement`, `SpecItem`, `BikeReviewRequest`, `BikeReviewResponse`, `BikeOffer`, `BikeOfferRequest`, `BikeOfferResponse`, `UsedBikeRequest`, `UsedBikeResponse`, `EquipmentDetailsRequest`, `EquipmentDetailsResponse`, `EquipmentReviewRequest`, `EquipmentReviewResponse`, `MissingDataRequest`, `MissingDataResponse` |
| Generic cache | `app/cache.py` | `endpoint_req_to_body_cache` table (a Core `Table` in `models.py`, created by `init_db()`): generic per-endpoint response cache keyed by endpoint + normalised request (`get_cached`/`set_cached`), read/written through the shared engine; `set_cached` is a first-write-wins `ON CONFLICT DO NOTHING` via `models.dialect_insert()` |
| Engine / DB selection | `app/models.py` `get_engine` · `configure_db` · `dialect_insert` | Engine from `DATABASE_URL` (fallback `sqlite:///cache.db` = `DEFAULT_DB_PATH`); SQLite gets `PRAGMA foreign_keys=ON` + WAL per connection, PostgreSQL gets `pool_pre_ping` and session `timezone=UTC`. `configure_db(url_or_path)` repoints it; `dialect_insert(table)` returns the SQLite or PostgreSQL `insert` so upserts work on both. Startup order in `main.py`: `init_db()` → `init_cache()` → `init_store()` |
| Startup hook | `app/store.py` | `init_store()` now **creates nothing** — it owns no tables any more and is kept purely as the app's startup hook (it only logs). **Search and details both moved to `app/repository.py`** (TODO-019) |
| ORM data access | `app/repository.py` · `app/models.py` | SQLAlchemy layer over `bikes`/`bike_details`/`bike_detail_photos` (+ unused `bike_results`/`accessories`/`bike_offers`). **Live for bike details**: `save_bike_details`/`get_bike_details` are the details cache (30 d TTL from `updated_at + ttl_seconds`; the response echoes the **caller's** casing, and photos are rows ordered by `display_order` rather than a JSON array). `bikes` carries normalised lookup columns `brand_norm`/`model_norm` (`models.norm()` = Python `.strip().lower()`, `UNIQUE(brand_norm, model_norm)`, kept in lockstep by a `@validates("brand", "model")` handler — fires on construction **and** later assignment, but **not** on a bulk `query().update()`) that every identity lookup matches exactly, while `brand`/`model` keep their real casing because the row is shared with search results — they are the **single source of display casing**, so a stored value equal to its own normalised form is treated as a placeholder (the old details blob keyed on `strip().lower()`) and upgraded by the first caller supplying real casing; the rule is monotonic, so lowercase never overwrites real casing and it cannot oscillate. **Normalise in Python, never via SQL `func.lower()`** — SQLite's `lower()` is ASCII-only, so uppercase non-ASCII (`RIESE & MÜLLER`, `Škoda`) misses the lookup and mints a duplicate identity; canonical `Riese & Müller` is unaffected, which is what makes it easy to miss. `models.configure_db(path)` repoints the ORM at another SQLite file, falling back to `models.DEFAULT_DB_PATH` (used by the migration script and the parity test). **Also live for search**: `save_search`/`get_search_by_query`/`find_bikes_by_brand` read and write `searches` (`query` = `norm()`'d enriched query, `UNIQUE`, 24 h TTL from `created_at + ttl_seconds`) + `bike_results` (`search_id` FK `ON DELETE CASCADE`, plus **`position`** preserving the score-weighted rank the old JSON blob carried implicitly — reads `ORDER BY position`). `find_bikes_by_brand` matches `brand_norm` **exactly**, not `ilike` substring — this matches the shipped `store.py` behaviour it replaced. See `backend/app/DB_MIGRATION.md` |
| Missing-data requests | `app/repository.py` `record_missing_request` · `app/models.py` `BikeMissingRequest` | Table `bike_missing_request` (`bike_id` FK → `bike.id`, `missing_type` ≤ 64, `counter`, `UNIQUE(bike_id, missing_type)`) counting "Request data" clicks (TODO-026). Looks the bike up in `bike` by Python-normalised brand/model (never creates it), then one atomic `INSERT … ON CONFLICT DO UPDATE counter = counter + 1` (SQLite or PostgreSQL construct via `models.dialect_insert()`). Created by `init_db()` at startup — no migration step |
| Equipment categories | `app/equipment_categories.py` | 4 equipment category registry (helmets, lights, locks, apparel); loads prompt files at startup; keyword-based `resolve_category()` inference |
| Prompts | `app/prompts/*.md` | `bike_search.md` single-call bike-finding prompt + `bike_details_{slug}.md` per-category component search prompts (8 categories) + `bike_details.md` JSON format reference + `equipment_details_{slug}.md` (4) + `equipment_description.md` / `equipment_photos.md` / `equipment_review.md` |
| Bike finder | `app/bike_finder.py` | **One** Claude Haiku call (no tools, `prompts/bike_search.md`) → every matching `BikeResult` (no cap, min 1 — the closest bike with a low `match_score` when nothing meets every filter; `max_tokens=8000`, warns on `stop_reason == "max_tokens"`), parsed with `extract_json()`; bad JSON → `[]`. Only runs on a DB miss (TODO-024) |
| DB-first search | `app/repository.py` `find_bikes_by_details` | Matches the checkable `SearchRequest` fields (brand, model, frame_material, wheel_size, frame_size, gender, is_electric, battery_capacity_wh, brake_type, drivetrain, belt_drive) against `bike` + `bike_detail_component`; every given field must match, a missing spec row does not match, every match returned (no cap, TODO-025). Rules table in `backend/README.md` § Search Cache |
| Details finder | `app/bike_details_finder.py` | Loops through 8 component categories (Frame → Accessories), runs one focused `web_search` call per category, aggregates results via the shared `extract_json()`; logs per-iteration and total token usage |
| JSON extraction | `app/json_extract.py` | Shared `extract_json()` — lifts the first parseable fenced block or balanced `{...}`/`[...]` out of prose. Used by every finder whose prompt demands raw JSON; the model narrates before the object often enough that a strict parser silently loses whole categories/offers |
| Description finder | `app/bike_description_finder.py` | Single `web_search` call with prompt caching to generate a 4–5 sentence plain-text bike overview **in Polish** (the prompt forces Polish output regardless of the English request/sources); runs in parallel with details finder |
| Review finder | `app/bike_review_finder.py` | Single `web_search` call across curated sources (tier list and weights in `backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md`); synthesises score 0–10, explanation, source URLs, plus a per-source score array from which it computes a weighted aggregate `rating` (0–10) and `sources_used` count (pro/numeric 3×, pro/qualitative 2×, community 1×; non-zero rating requires ≥1 pro source). When the highest and lowest per-source score spread by more than `DISAGREEMENT_THRESHOLD` (3.0), `rating` anchors to the pro/numeric mean (falling back to pro/qualitative) instead of the weighted mean, and a disagreement sentence is appended to `explanation`; `sources_used` is unaffected. `ref` is returned sorted Tier 1 → Tier 2 → Tier 3. Tolerates the model narrating before the JSON via a balanced-brace scan over all text blocks, with a no-tool prefilled repair call as a last resort |
| Offer finder | `app/bike_offer_finder.py` | Single `web_search` call to find 1 current offer on allegro.pl |
| Used bikes finder | `app/bike_used_finder.py` | Single `web_search` call to find up to 5 used listings on olx.pl with cascade fallback; then Playwright scrapes photos via `olx_image_fetcher.py` |
| Browser config | `app/browser_config.py` | `playwright_headless()` — reads `PLAYWRIGHT_HEADLESS` (`true` in the Docker image; unset = visible browser for local debugging); used by every Playwright launch. `BROWSER_SLOTS` — a process-wide `BoundedSemaphore` (`BROWSER_MAX_CONCURRENCY`, default 2, min 1) that every scraper holds around `sync_playwright()` + `chromium.launch()`, because each launch costs 0.5–0.9 GiB and nothing else caps how many worker threads scrape at once; without it a burst of uncached details/offer requests OOM-kills the 2 GiB Cloud Run instance |
| OLX image fetcher | `app/olx_image_fetcher.py` | Playwright (`PLAYWRIGHT_HEADLESS`; unset = visible browser) scrapes up to 4 `<img>` URLs from each OLX listing URL using `*.apollo.olxcdn.com` regex |
| Ceneo finder | `app/bike_offer_ceneo_finder.py` | Single `web_search` call to find 1 current offer on ceneo.pl |
| Decathlon finder | `app/bike_offer_decathlon_finder.py` | Single `web_search` call to find 1 current offer on decathlon.pl |
| Photos finder | `app/bike_photos_finder.py` | Two-step: (1) Claude `web_search` to find manufacturer product page URL, (2) Playwright (`PLAYWRIGHT_HEADLESS`; unset = visible browser) scrapes up to 8 product `<img>` URLs from rendered page; runs in parallel with details and description finders |
| Equipment details finder | `app/equipment_details_finder.py` | Resolves the equipment category (given or inferred), runs one focused component-search call with that category's `equipment_details_{slug}.md` prompt, returns the bike-style component tree (web_search behind a `TODO` flag, mirroring the bike details finder) |
| Equipment description finder | `app/equipment_description_finder.py` | Single `web_search` call with prompt caching for a 4–5 sentence equipment overview |
| Equipment photos finder | `app/equipment_photos_finder.py` | Two-step manufacturer-page → Playwright scrape (mirrors `bike_photos_finder.py`) |
| Equipment review finder | `app/equipment_review_finder.py` | Single `web_search` call → score 0–10, explanation, one source URL (review/forum only, never offers) |
| Test scripts | `scripts/test_search.py` · `scripts/test_details.py` · `scripts/test_review.py` · `scripts/test_offer.py` · `scripts/test_equipment.py` · `scripts/test_equipment_review.py` · `scripts/test_details_parity.py` · `scripts/test_browser_slots.py` | Smoke tests for each endpoint (`test_equipment_review.py` is a focused regression for the equipment-review JSON extraction; `test_details_parity.py` is a pytest asserting the ORM details read path returns a field-for-field identical `BikeDetailsResponse` to the old blob path — casing echo, `components` tree, photo order, staleness — run against a scratchpad copy of `cache.db`) |
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

**Endpoint** `POST /v1/bike/offer`
- Request: `{"company": "Canyon", "model": "Grizl CF 7 ESC"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches allegro.pl using `app/prompts/bike_offer_allegro.md` as the system prompt
- Returns `{ offers: [{ brand, model, price, is_new, url, photos, source }], info: str }` (1 offer)
- On JSON parse error: returns `{ offers: [], info: raw_text }` — never returns 502

**Endpoint** `POST /v1/bike/used`
- Request: `{"company": "Trek", "model": "Marlin 5"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches olx.pl using `app/prompts/bike_offer_olx.md` as the system prompt; cascade fallback (exact → model-family → brand/category)
- Then Playwright (`PLAYWRIGHT_HEADLESS`; unset = visible browser) fetches up to 4 photo URLs per listing from OLX CDN
- Returns `{ offers: [{ brand, model, price, is_new, url, photos, source, city }], info: str }` (up to 5 listings, always used)
- On JSON parse error: returns `{ offers: [], info: raw_text }` — never returns 502

**Endpoint** `POST /v1/bike/ceneo`
- Request: `{"company": "Canyon", "model": "Grizl CF 7 ESC"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches ceneo.pl using `app/prompts/bike_offer_ceneo.md` as the system prompt
- Returns `{ offers: [{ brand, model, price, is_new, url, photos: [], source: "ceneo.pl" }], info: str }` (1 offer, no photos)
- On JSON parse error: returns `{ offers: [], info: raw_text }` — never returns 502

**Endpoint** `POST /v1/bike/decathlon`
- Request: `{"company": "Rockrider", "model": "ST 100"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches decathlon.pl using `app/prompts/bike_offer_decathlon.md` as the system prompt
- Returns `{ offers: [{ brand, model, price, is_new, url, photos: [], source: "decathlon.pl" }], info: str }` (1 offer, no photos)
- On JSON parse error: returns `{ offers: [], info: raw_text }` — never returns 502

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
| App shell | `src/App.tsx` | View router (`search` / `details` / `equipment`), search, details, review, allegro offer, ceneo offer, decathlon offer & used-bike state, plus equipment details/review state; all API calls. A free-text-only submit first calls `/v1/bike/parse`: extracted fields populate the Filters panel and the search waits for a second submit, while a **400** renders a "Not found" warning above the search box and stops there. Clicking a component element name in a bike's spec tree opens the equipment view for that item |
| Search form | `src/components/SearchInput.tsx` | Controlled input + submit button + collapsible Filters panel (Basic group: brand, model, bike type, year, wheel size, frame size + electric toggle; Advanced group: gender, frame material, brake type, drivetrain, belt drive + battery capacity shown only when electric); loading state |
| Result card | `src/components/ResultCard.tsx` | Clickable per-bike card: match score, brand + model, accessories chips, explanation, score bar |
| Loading card | `src/components/LoadingCard.tsx` | Shimmer skeleton matching result card dimensions |
| Details view | `src/components/BikeDetailsView.tsx` | Full spec sheet: back nav, bike header, Overview, unified Offers (MergedOffersSection — pools all four sources Allegro/Ceneo/Decathlon/OLX and splits by each offer's `is_new` flag into two stacked cards: Used on top, New below, each sorted cheapest-first via `OfferCategoryCard`/`OfferRow`), Expert Review, component tree whose element names are clickable → equipment view. Reuses shared building blocks from `BikeDetailsShared.tsx` (component-element links are enabled by passing `onElementSelect`). **Request data (TODO-027):** each section (photos, overview, component tree, review, Used card, New card) shows its loading state for `REQUEST_BUTTON_DELAY_MS` (5 s, via the local `useLoadingGrace` hook); after that — or on an empty/failed response — a section without data renders `RequestDataButton` with its `MissingType`, while the request keeps running and late data replaces the button. `MergedOffersSection` no longer returns `null` when both lists are empty |
| Request data button | `src/components/RequestDataButton.tsx` | Shared "We don't have this data yet" + **Request data** button (`card` variant with section eyebrow, dashed border; `inline` variant inside an offer card). Click → `POST /v1/bike/missing` `{company, model, missing_type}` → disabled "Requested ✓"; a failed POST returns it to clickable. Component state only, no `localStorage`. Not used by the equipment view |
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
- `POST /v1/bike/offer` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (allegro.pl)
- `POST /v1/bike/ceneo` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (ceneo.pl)
- `POST /v1/bike/decathlon` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (decathlon.pl)
- `POST /v1/bike/used` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (used bikes from OLX, each with optional `city`)
- `POST /v1/bike/parse` `{ "text": "..." }` -> `ParseResponse` (5 optional fields); **400** `"Bike not available in our database"` when nothing is extracted -> App.tsx shows a warning above the search box and skips the search
- `POST /v1/bike/missing` `{ "company": "...", "model": "...", "missing_type": MissingType }` → `{ bike_id: number | null, missing_type, counter }` — sent by `RequestDataButton` in the bike details view (TODO-027); the counter is never shown in the UI
- `POST /v1/equipment/details` `{ "company"?, "model", "category"? }` → `{ company, model, category, description: BikeDescription, components: BikeCategory[], photos: string[] }` (no offer links)
- `POST /v1/equipment/review` `{ "company"?, "model" }` → `{ score, explanation, ref: string[] }` (review/forum links only)
- All endpoints proxied to backend via Vite — no CORS config needed in development
