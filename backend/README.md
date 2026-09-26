# Biker Backend

## Setup & Run

Start the local PostgreSQL first (Docker):

```bash
# first time — creates the container and a persistent volume
docker run -d --name biker-pg -e POSTGRES_USER=biker -e POSTGRES_PASSWORD=biker -e POSTGRES_DB=biker -p 5432:5432 -v biker-pgdata:/var/lib/postgresql/data postgres:17
# every later time
docker start biker-pg
docker exec biker-pg pg_isready -U biker -d biker        # → "accepting connections"
docker exec -it biker-pg psql -U biker -d biker -c "\dt" # list tables (no local psql needed)
```

The backend uses it when `DATABASE_URL=postgresql+psycopg://biker:biker@localhost:5432/biker` is set (TODO-028),
e.g. in `backend/.env`; without `DATABASE_URL` it falls back to `cache.db`. Reset the database completely with
`docker rm -f biker-pg && docker volume rm biker-pgdata`.

### Database selection (`DATABASE_URL`)

Every table — the generic response cache included — goes through the one SQLAlchemy engine in `app/models.py`
(`get_engine()`); there is no raw `sqlite3` connection. `DATABASE_URL` picks the database:

| `DATABASE_URL` | Database |
|---|---|
| unset | SQLite file `backend/cache.db` (FK enforcement + WAL switched on per connection) |
| `postgresql+psycopg://…` | PostgreSQL (`pool_pre_ping`, session `timezone=UTC`) |

**GCP Cloud SQL (`biker-pg`, the database the app now uses).** Run the Cloud SQL Auth Proxy on the host
(`cloud-sql-proxy --gcloud-auth --port 6543 biker-engine-prod:europe-central2:biker-pg`) and set in `backend/.env`:

```
DATABASE_URL=postgresql+psycopg://biker@127.0.0.1:6543/biker
PGPASSFILE=C:/…/backend/gcp-prod-pgpass.conf
```

The URL carries no password: libpq reads it from `backend/gcp-prod-pgpass.conf` (gitignored, one line
`127.0.0.1:6543:biker:biker:<password>`). Never commit it or put the password in `DATABASE_URL`.

The schema is created at startup by `init_db()` (`create_all()`) on either database. Upserts
(`set_cached`, `record_missing_request`) use `models.dialect_insert()`, which picks the SQLite or PostgreSQL
`INSERT … ON CONFLICT` construct for the active engine.

### Copy `cache.db` into PostgreSQL

```bash
python scripts/copy_sqlite_to_postgres.py              # target = $DATABASE_URL
python scripts/copy_sqlite_to_postgres.py --truncate   # replace a non-empty target
python scripts/copy_sqlite_to_postgres.py --verify-only
```

Creates the schema, copies every table in FK order in **one transaction**, resets the id sequences, then prints
per table the SQLite rows, orphans skipped, PostgreSQL rows and a content-checksum verdict (exit 0 only when all
match). It refuses a non-empty target without `--truncate` and opens `cache.db` read-only. Rows whose parent
no longer exists (SQLite ran without FK enforcement for a while) are skipped and listed — PostgreSQL would reject
them and nothing could reach them anyway. Timestamps written with a `+00:00` suffix land as naive UTC, which is how
every other row is stored and how the app reads them.

To run a worktree next to `main`, point its frontend at its backend:
`BIKER_API_URL=http://localhost:8001 npm run dev -- --port 5174` (the Vite proxy defaults to `:8000`).

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then edit .env with your real ANTHROPIC_API_KEY
python scripts/migrate_bike_details.py   # REQUIRED on an existing cache.db — see note below
uvicorn app.main:app --reload --port 8000
```

> **Run the migration before starting the app on a pre-existing `cache.db`.** `init_db()` uses
> SQLAlchemy's `create_all()`, which creates missing tables but never `ALTER`s an existing one — so an
> older `bike_results` table keeps its old columns and gains neither `search_id` nor `position`.
> `repository.save_search` then raises `OperationalError` on every write. Nothing is cached, the
> DB-first search branch never hits, and **every search falls through to the AI call**. `repository`
> detects this specific failure and logs it at **ERROR** naming the remedy, so it no longer blends
> into routine non-fatal cache warnings — but that is a detector, not a fix. See
> [`app/DB_MIGRATION.md`](app/DB_MIGRATION.md) for how to verify.
>
> The same script also repairs placeholder (all-lowercase) brand casing left by earlier builds, on
> **every** run — no `--force` needed — as long as `search_cache` still exists.

`SEARCHER_URL` / `SEARCHER_API_KEY` (TODO-031) point `POST /v1/bike/used/search` at the on-demand OLX searcher
(top-level `searcher/`, `http://localhost:8100` locally; the key is sent as `X-Searcher-Key` and must equal the
searcher's own `SEARCHER_API_KEY`). `SEARCHER_TIMEOUT` (seconds, default 600) bounds one search. Leave `SEARCHER_URL`
unset to run without the searcher — that route then answers 503, while `POST /v1/bike/used` keeps serving whatever is
stored in `bike_offer`.

```bash
# In a second terminal:
python scripts/test_search.py   # smoke-test POST /v1/bike/search (+ the DB-only routes: search-cache, missing, used — TC-20 – TC-32)
python scripts/test_details.py  # smoke-test POST /v1/bike/details
python scripts/test_review.py   # smoke-test POST /v1/bike/review
python scripts/test_offer.py    # smoke-test POST /v1/bike/offer
```

```bash
# One-off: backfill legacy blob bike details into the ORM tables (idempotent)
python scripts/migrate_bike_details.py
pytest scripts/test_details_parity.py -v   # blob vs ORM read parity
```

### Docker image

`backend/Dockerfile` is the image docker compose and Cloud Run both use: Python 3.14 slim, `patchright install --with-deps chromium`,
non-root user, `uvicorn` on `$PORT` (default 8000). `.env`/`cache.db` are excluded by `.dockerignore` — `ANTHROPIC_API_KEY`
and `DATABASE_URL` come from the environment; under compose the Cloud SQL password arrives as the mounted pgpass file (`PGPASSFILE`). `PLAYWRIGHT_HEADLESS=true` (read by `app/browser_config.py`) runs the photo /
Allegro scrapers without a display; unset keeps the visible browser for local debugging (the OLX scraper moved to
`searcher/` in TODO-031). See the root `README.md`
§ Run with Docker.

On Cloud Run (`scripts/deploy.ps1`, service `biker-backend`) the same image gets
`DATABASE_URL=postgresql+psycopg://biker@/biker?host=/cloudsql/biker-engine-prod:europe-central2:biker-pg` — the unix socket
mounted by `--add-cloudsql-instances`, still no password — plus `PGPASSWORD` and `ANTHROPIC_API_KEY` as Secret Manager
references (`db-password`, `anthropic-api-key`). libpq picks `PGPASSWORD` up exactly like the pgpass file, so nothing in
`app/` changes between compose and Cloud Run. See the root `README.md` § Deploy to GCP.

Browser launches are capped per process by `BROWSER_MAX_CONCURRENCY` (default 2, `app/browser_config.py` `BROWSER_SLOTS`):
every scraper (bike/equipment photos, OLX and Allegro images) holds one slot around `sync_playwright()` + `chromium.launch()`.
One launch costs 0.5–0.9 GiB (node driver + Chromium tree, and Cloud Run's `/tmp` is memory-backed), so two fit in the
2 GiB instance next to the app; a third request waits for a slot instead of getting the instance OOM-killed. Raise it only
together with `--memory` in `scripts/deploy.ps1`.

## Unit tests

```bash
cd backend
pytest -m "not llm"
```

`pytest.ini` scopes default collection to `scripts/test_review_aggregation.py` and
`scripts/test_browser_slots.py`, so a bare `pytest` run covers the review-aggregation unit tests
and the browser-launch cap (a fake Playwright proves no scraper exceeds `BROWSER_MAX_CONCURRENCY`
launches and always returns its slot). The rest of `scripts/`
stays excluded — those are standalone smoke scripts that hit a live server at import
time and must not be auto-run. (The category-scoring eval `scripts/test_scoring.py`
was removed with the category pipeline in TODO-024.)

### Evaluate any prompt (ad-hoc)

`scripts/eval_prompt.py` runs **any** prompt file (as the system prompt) against
arbitrary inputs via the same no-API-key `claude` CLI mechanism, printing each
reply and its extracted score (if any):

```bash
cd backend
.venv\Scripts\python.exe scripts/eval_prompt.py app/prompts/bike_search.md "fast carbon road racer" "29er trail bike"
.venv\Scripts\python.exe scripts/eval_prompt.py app/prompts/bike_search.md --dataset inputs.txt --model sonnet
```

The `/eval-prompt <prompt-file> "<input>" ...` slash command (`.claude/commands/`)
wraps this for quick reuse. Use it for ad-hoc prompt iteration.

## Follow-up cache tables

Two queryable layers (in the same `cache.db`) sit **on top of** the generic response cache (`app/cache.py`). Both are now normalised SQLAlchemy tables written by `app/repository.py`. They let follow-up requests be served without any web/Claude call:

| Layer | Tables | Key | TTL |
|-------|--------|-----|-----|
| Search | `searches` + `bike_results` + `accessories` | `searches.query` — the `norm()`'d enriched query | 24 h |
| Details | `bikes` + `bike_details` + `bike_detail_photos` | `bikes.(brand_norm, model_norm)` — `.strip().lower()` of brand+model | 30 days |

Both reference the shared `bikes` identity row, so a bike found by search and a bike with cached details are the same row.

- Both are indexed on their key columns and upsert on conflict (a re-run refreshes the entry).
- Freshness: searches check `searches.created_at + ttl_seconds`; details check `bike_details.updated_at + ttl_seconds`. A stale row is treated as a miss (never served).
- Search results carry an explicit **`position`** — the bikes are returned best match first, so their order is meaningful, and a row set (unlike the old JSON blob) does not preserve it for free. Reads order by `position`.
- Searches are also queryable **by attribute** — `find_bikes_by_brand(brand)` returns de-duplicated bikes of that brand across fresh cached searches, powering `GET /v1/bike/search-cache?brand=`.
- Writes are best-effort: a cache-table failure is logged but never breaks the underlying request.
- This layer is **additive** — the generic per-endpoint cache is unchanged.

The follow-up read endpoints are [`GET /v1/bike/search-cache`](#get-v1bikesearch-cache) and [`GET /v1/bike/details-cache`](#get-v1bikedetails-cache).

### Details storage — normalised ORM tables

Bike details used to live in a `bike_details_cache` JSON-blob table in `app/store.py`. That half now goes through `app/repository.py` and the normalised ORM tables (TODO-019); the response payload is byte-identical, so the frontend is unaffected.

- `bikes` is the shared identity row — the same row backs search results and offers, so `brand`/`model` are stored with their **real casing**, never normalised. They are the single source of display casing for search results: a stored value equal to its own normalised form is treated as a **placeholder** (the old details blob keyed on `strip().lower()`, so every row it seeded looks like that) and is upgraded by the first caller supplying real casing. The rule is monotonic — an all-lowercase value never overwrites real casing — so it cannot oscillate. Without it, every brand that had been through the details cache would render as `cannondale` rather than `Cannondale`.
- Lookup goes through the normalised companion columns **`brand_norm` / `model_norm`**, populated by `models.norm()` (Python `.strip().lower()`) via a `@validates("brand", "model")` handler on `Bike` — which fires on construction *and* on later assignment, though not on a bulk `query().update()` — and constrained by `UNIQUE(brand_norm, model_norm)`. Lookups match those columns exactly, so `"Trek"`/`"Marlin 5"` and `"trek"`/`"marlin 5"` resolve to the same row — matching what the blob cache's `strip().lower()` key achieved. A save reuses an existing identity rather than creating a second one.
- **Do not replace this with SQL `lower()`.** SQLite's built-in `lower()` is ASCII-only and Python's is not; they diverge only when an **uppercase non-ASCII** character is involved — `RIESE & MÜLLER` lowercases to `riese & mÜller` in SQLite but `riese & müller` in Python, and `Škoda` stays `Škoda` in SQLite against Python's `škoda`. The canonical spelling `Riese & Müller` is unaffected, which is what makes this easy to miss. When it does hit, the lookup misses and `save_bike_details` mints a duplicate `bikes` identity — precisely the case-split problem this migration exists to fix.
- The response echoes the **caller's** casing, not the stored row's — same as the blob path did.
- `photos` are rows in `bike_detail_photos` ordered by `display_order`, not a JSON array. Zero rows deserialise back to `photos: []`.
- `description` and `components` remain JSON columns on `bike_details`.
- Re-saving an unchanged row refreshes its TTL, because `updated_at` carries `onupdate=now` — the same behaviour the blob upsert had when it rewrote `time_stored`.

See [`app/DB_MIGRATION.md`](app/DB_MIGRATION.md) for the full schema and what is still pending (search).

#### `scripts/migrate_bike_details.py`

One-off backfill that copies every `bike_details_cache` row into `bikes` + `bike_details` + `bike_detail_photos`, preserving each row's real age (`time_stored` → `created_at`/`updated_at`, `ttl` → `ttl_seconds`) and the original photo ordering (array index → `display_order`). It also brings `bikes` up to the current schema: adds `brand_norm` / `model_norm` if absent and backfills them for **every pre-existing `bikes` row** (not just the ones it creates — older rows would otherwise be invisible to the normalised lookup and get duplicated on the next save), merges `bikes` rows that share a normalised identity, creates the `uq_bike_brand_model_norm` unique index, and removes the test-script leftovers (`bike_results` / `accessories` rows, and any `bikes` row nothing references).

```bash
cd backend
python scripts/migrate_bike_details.py                # idempotent — re-running is a no-op
python scripts/migrate_bike_details.py --force        # rebuild details rows that already exist
python scripts/migrate_bike_details.py --drop-legacy  # also DROP TABLE bike_details_cache
python scripts/migrate_bike_details.py --db other.db  # operate on a different SQLite file
```

It is importable too — `migrate(db_path=None, drop_blob_table=False, force=False, verbose=True) -> dict` returns a stats dict (rows migrated, photos written, rows merged, leftovers deleted, plus `blob_tables_dropped`, a **list of dropped table names**). Dropping the legacy blob tables is opt-in from both entry points — `migrate(drop_blob_table=True)` or `--drop-legacy` — so a default call from either keeps them.

A bike that already has a `bike_details` row is left alone, so the default run is safe to repeat. Dropping the legacy blob tables (`bike_details_cache`, `search_cache`) is deliberately **not** part of a default run — the parity test needs to read the blob tables alongside the ORM ones. Pass `--drop-legacy` once parity is green.

#### `scripts/test_details_parity.py`

Pytest regression for the ORM read path (`pytest scripts/test_details_parity.py -v`). For each cached bike it reads the same record through the legacy blob path and the ORM path and asserts the two `BikeDetailsResponse` objects are equal field for field — `company`/`model` casing echo, full `description`, the whole `components` tree including nested `SpecItem` ordering, and `photos` in the same order — plus a forced-stale row returning `None` from both. It runs against a **copy** of the pre-migration `cache.db` in the scratchpad (override with `TODO019_SNAPSHOT_DB`), so staleness can be forced without touching real data, and it carries its own ~15-line blob reader rather than importing the removed `store` helpers, so it stays runnable after the cutover.

## Search Cache

`POST /v1/bike/search` resolves through a **three-step cascade** (TODO-024), stopping at the first step that produces bikes:

| # | Step | Cost | Condition |
|---|------|------|-----------|
| 1 | Generic response cache (`app/cache.py`) | 0 outbound calls | Exact normalised match on the full request (every filter field) |
| 2 | **DB details search** (`repository.find_bikes_by_details`) | 0 outbound calls | ≥1 DB-checkable field is set **and** ≥1 bike matches every one of them |
| 3 | **One** Claude call (`app/bike_finder.py`, `app/prompts/bike_search.md`) | 1 call | Everything else |

### How the DB step matches

A bike matches when **every** checkable field given matches. A bike missing the relevant spec row does not match that field, and a bike with no `bike_detail` row can only match on `brand`/`model`. Brand and model are compared **exactly** after Python `.strip().lower()` (never SQL `lower()`, which is ASCII-only).

| `SearchRequest` field | Source in DB | Rule |
|---|---|---|
| `brand`, `model` | `bike.brand` / `bike.model` | case-insensitive exact |
| `frame_material` | `Frame / Frame`, `spec_key='Material'` | synonyms — Aluminum ↔ aluminium/alloy/6061…, Steel ↔ chromoly/cro-mo/hi-ten…, Carbon |
| `wheel_size` | any `spec_key='Wheel Size'`, or `Wheels/*` `Size` | number token (`29` in `29 x 2.4`); `700c` ↔ `28`, `650b` ↔ `27.5` |
| `frame_size` | `Frame / Frame`, `spec_key='Sizes'` / `'Size'` | size token in the list (`SM`/`MD`/`LG` aliased) |
| `gender` | `spec_key='Gender'` | Male/Female also match unisex; Universal = unisex |
| `is_electric` | `Electric / Powertrain` category present / absent | |
| `battery_capacity_wh` | `Electric / Powertrain / Battery`, `spec_key='Capacity'` | parsed Wh within ±10 % |
| `brake_type` | `Brakes/*` element names, descriptions, spec values | Hydraulic → `hydraulic` (also matches Polish `hydrauliczne`); Mechanical → `mechanical`/cable disc/Polish `mechaniczn`; V-brake / Rim → rim keywords (incl. Polish `obręczow`/`szczękow`) and **no** `disc`/`tarcz` mention — element descriptions are generated in Polish |
| `drivetrain` | `Drivetrain/*` element names, descriptions, spec values | `Nx` token (`1x12`, not `52x36T`), else chainring count (`50/34T` = 2x; single ring and no front derailleur = 1x) |
| `belt_drive` | `Drivetrain/*` `element_name` contains `belt` | |
| `bike_type`, `year`, `search` | — | **not checkable**, ignored by the DB step |

A request with **only** non-checkable fields skips the DB and goes straight to the AI call. **Every** matching DB bike is returned (no cap, TODO-025), highest `match_score` first — never topped up with AI results.

`match_score` / `explanation` / `accessories` of a DB hit come from the bike's most recent `search_bike_rating_cache` row when one exists; otherwise `match_score = 10`, `accessories = []` and the explanation lists the matched fields, e.g. `"Pasuje: rama karbonowa, koła 29\", hamulce tarczowe hydrauliczne."` (Polish, like the AI-generated explanations).

### A DB hit deliberately does not warm the generic cache

`set_cached` is never called on the step-2 path. The generic `cache` table has **no `ttl` column** and `get_cached` never checks age — writing a DB-sourced result there would pin that answer permanently, even after the DB changes.

**Tests:** `scripts/test_search.py` TC-20 – TC-25 against a live server: brand+model DB hit (TC-20), DB miss → one AI call (TC-21), non-checkable-only → AI (TC-22), legacy `price_max` ignored (TC-23), spec-field DB hit with no AI and no cache row (TC-24), and no regression on the generic-cache path (TC-25).

## Endpoints

### `POST /v1/bike/search`

Find every matching bike (no cap, min 1) — from the DB when its details match, otherwise from one Claude call. All fields are optional but at least one must be provided.

```http
POST http://localhost:8000/v1/bike/search
Content-Type: application/json

{
  "search": "comfortable bike for daily 10 km city commute, mostly paved roads",
  "brand": "Trek",
  "model": "FX 3",
  "year": 2023,
  "wheel_size": "29\"",
  "is_electric": false,
  "bike_type": "Gravel",
  "frame_size": "M",
  "gender": "Universal",
  "frame_material": "Carbon",
  "brake_type": "Hydraulic Disc",
  "drivetrain": "2x",
  "belt_drive": false,
  "battery_capacity_wh": 500
}
```

All fields except `search` default to `null` (no constraint). The backend assembles an enriched query such as `"Brand: Trek, Type: Gravel, Frame size: M — comfortable bike…"` and, on a DB miss, sends it to a single Claude call. All fields participate in the SQLite cache key, so two searches that differ only in a filter return distinct results. `price_max`, `rider_height_cm`, `rider_weight_kg`, `has_suspension` and `is_kids` were removed (TODO-023); they are silently ignored if sent, so a payload made only of them is rejected with 422.

**Flow:**
0. SQLite reads only — generic cache, then the DB details search over `bike` + `bike_detail_component` (skipped when no checkable field is set). **A hit at either step returns immediately, making zero outbound HTTP calls.** See [Search Cache](#search-cache)
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku (no tools) with `app/prompts/bike_search.md` and the enriched query; returns every matching bike as a JSON array (min 1: when nothing meets every filter, the closest bike with a low `match_score` and an explanation naming the unmet filter; `max_tokens=8000`, a warning is logged on `stop_reason == "max_tokens"`), parsed with `app/json_extract.extract_json()`; `explanation` and `accessories` come back in Polish (brand/model and named components untranslated). Runs only on a DB miss

A response with no parseable JSON returns `bikes: []` (never a 502) and is not cached; an upstream API error is a 502. When the AI returns bikes, the response is written to the generic cache and to `search_cache` + `search_bike_rating_cache` via `store.save_search`. A DB-served result is **not** written back to either — see [Search Cache](#search-cache).

---

### `GET /v1/bike/search-cache`

Follow-up read served **purely from the search tables** (`searches` + `bike_results`, read via `app/repository.py`) — makes **no** web/Claude call. Two modes:

- `?query=<enriched query>` — exact (case-insensitive, trimmed) repeat of a prior search, matched on `searches.query`. Returns 404 if not cached or the entry is older than its 24 h TTL. Bikes come back in their original score-weighted order (`ORDER BY bike_results.position`).
- `?brand=<brand>` — lookup-by-attribute: every cached bike of that brand across all fresh cached searches (de-duplicated by brand+model). **`brand` is matched exactly** (against `bikes.brand_norm`, so casing and surrounding whitespace are ignored) — a partial brand name will not match. This matches the behaviour this endpoint has always shipped: the live implementation in `store.py` did an exact normalised compare too. The ORM's previously unused `ilike` substring variant was never wired to an endpoint, so no caller loses anything.

```http
GET http://localhost:8000/v1/bike/search-cache?query=Brand:%20Trek%20%E2%80%94%20trail%20riding
GET http://localhost:8000/v1/bike/search-cache?brand=Trek
```

**Response:**
```json
{
  "query": "Brand: Trek — trail riding",
  "cached": true,
  "bikes": [ { "brand": "Trek", "model": "Marlin 5", "accessories": [], "match_score": 8.0, "explanation": "…" } ]
}
```

Returns 422 if neither `query` nor `brand` is provided.

**Flow:** none — SQLite read only.

---

### `GET /v1/bike/details-cache`

Follow-up details lookup served **purely from the ORM details tables** (`bikes` + `bike_details` + `bike_detail_photos`, read via `app/repository.py`) — makes **no** web/Claude call. Returns 404 if the `(company, model)` pair is not cached or the entry is older than its 30-day TTL. The `company`/`model` match is case-insensitive, and the response echoes the casing you asked with.

```http
GET http://localhost:8000/v1/bike/details-cache?company=Canyon&model=Grizl%20CF%207%20ESC
```

**Response:** identical shape to `POST /v1/bike/details` (`company`, `model`, `description`, `components`, `photos`).

**Flow:** none — SQLite read only.

---

### `POST /v1/bike/missing`

Record that a user asked for a section of a bike's details view that has no data (the "Request data" button, TODO-026/027). One row per `(bike, missing_type)` in `bike_missing_request`; the first request creates it with `counter = 1`, every later one adds 1 (a single atomic SQLite upsert). The table shows which data for which bikes users want most. **No** AI call and **no** generic cache.

```http
POST http://localhost:8000/v1/bike/missing
Content-Type: application/json

{
  "company": "Trek",
  "model": "Marlin 5",
  "missing_type": "photos"
}
```

**Response:** `{ "bike_id": 1, "missing_type": "photos", "counter": 2 }`

- `missing_type` is a free string chosen by the frontend (`photos`, `description`, `components`, `review`, `offers_new`, `offers_used`). The backend strips it and rejects empty/whitespace-only or longer than 64 characters with **422**. `company`/`model` must be non-empty (422).
- The bike is looked up in the existing `bike` table by `company` + `model`, normalised in Python (`strip().lower()`, like `find_bikes_by_details`), and is **never created**: `save_search` always writes it before the details view can open.
- Bike not found (only after a swallowed `save_search` failure) → logged at **ERROR**, returns **200** `{ "bike_id": null, "missing_type": "photos", "counter": 0 }`, nothing written. A failed write is logged at ERROR and returns the same shape.
- No spam protection: every call adds 1; the frontend stops repeat clicks.
- The table is created at startup by `init_db()` (`create_all` adds missing tables to an existing `cache.db`), so no migration step is needed.

**Flow:** none — no outbound HTTP calls; one SQLite read of `bike` plus one upsert into `bike_missing_request`.

**Tests:** `scripts/test_search.py` TC-27 – TC-29 against a live server: counter 1 → 2 plus a separate row for a second `missing_type` on a seeded fixture bike, with no generic-cache row (TC-27); unknown bike → 200, `bike_id: null`, `counter: 0`, no bike created (TC-28); invalid `missing_type` → 422 (TC-29).

---

### `POST /v1/bike/details`

Return the full component list for a specific bike model.

```http
POST http://localhost:8000/v1/bike/details
Content-Type: application/json

{
  "company": "Canyon",
  "model": "Grizl CF 7 ESC"
}
```

**Response includes:** `description` (4–5 sentence plain-text overview, written in Polish), `components` (category tree — each element `description` is Polish, while category/subcategory/spec keys, element names and spec values stay English), `photos` (up to 8 manufacturer product image URLs).

On the happy path the result is also written to the queryable ORM details tables via `repository.save_bike_details` (see [Details storage — normalised ORM tables](#details-storage--normalised-orm-tables)). A cached repeat is served from those tables with **zero outbound calls**; the lookup is case-insensitive and the response echoes the caller's casing.

**Flow (all three run in parallel via `asyncio.gather`):**
1. `POST https://api.anthropic.com/v1/messages` × 8 — Claude Haiku with `web_search_20250305` tool, one focused search per component category (sequential): Frame, Drivetrain, Brakes, Wheels, Cockpit, Saddle & Seatpost, Lighting, Accessories
2. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool + prompt caching, generates a 4–5 sentence bike overview in Polish
3. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool finds the official manufacturer product page URL, then Playwright (`PLAYWRIGHT_HEADLESS`; unset = visible browser) scrapes up to 8 product `<img>` URLs from the rendered page

**Parsing:** each category response goes through the shared `app/json_extract.py` `extract_json()`, which pulls the first parseable fenced block or balanced `{...}` / `[...]` out of surrounding prose. The model routinely narrates ("I'll search for the Brakes specifications...") before emitting the JSON, so a parser that assumed the whole response was JSON silently dropped whole categories. A category with genuinely no JSON in its response is logged and skipped — never a 502.

---

### `POST /v1/bike/review`

Return an aggregated review score, explanation, source links, and an aggregate rating derived from multiple curated review sources for a specific bike model.

```http
POST http://localhost:8000/v1/bike/review
Content-Type: application/json

{
  "company": "Canyon",
  "model": "Grizl CF 7 ESC"
}
```

**Response:**
```json
{
  "score": 8,
  "explanation": "Canyon Grizl CF 7 ESC jest powszechnie chwalony za...",
  "ref": ["https://...", "https://..."],
  "rating": 7.7,
  "sources_used": 3
}
```

- `explanation` — 5–10 sentences in **Polish** (forced by `app/prompts/bike_review.md` § Language; the fallback is `"Recenzja niedostępna."`).
- `score` — a single synthesised editorial verdict (integer 0–10), as before.
- `rating` — the **aggregate** rating (float 0–10) computed from per-source scores across the curated sources.
- `sources_used` — count of curated sources that contributed a score to the aggregate; unaffected by the disagreement rule below — every consulted source still counts.
- `ref` — source URLs, guaranteed-ordered Tier 1 → Tier 2 → Tier 3 (best professional source first), not just whatever order the model emitted them in.

**Aggregation methodology** (curated source list and tier weights in [`backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md`](../backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md)):
Claude searches the curated sources and returns a per-source score for each source it found a review on, tagged with a `type`. The backend computes a weighted mean and normalises to 0–10:

| Source type | Examples | Weight |
|---|---|---|
| `pro_numeric` | bikeradar.com, cyclingweekly.com, bikeperfect.com | 3× |
| `pro_qualitative` | pinkbike.com, bikemag.com, gcn.com | 2× |
| `community` | mtbr.com, reddit.com, forumrowerowe.org / bikestats.pl | 1× |

`rating = Σ(score × weight) / Σ(weight)`, rounded to 1 decimal. A non-zero rating **requires at least one professional (`pro_numeric` or `pro_qualitative`) source**; if only community sources are found, `rating` is `0.0` and `sources_used` is `0`.

**Source disagreement:** when the spread between the highest and lowest per-source score exceeds `DISAGREEMENT_THRESHOLD` (3.0 points, a module-level constant in `app/bike_review_finder.py`), a weighted mean would hide a genuinely divisive verdict, so `rating` is anchored instead — to the mean of the `pro_numeric` scores, falling back to `pro_qualitative` if no `pro_numeric` source is present. `sources_used` is not affected; every consulted source still counts. When the rule fires, the backend (not the model) appends a Polish sentence to `explanation` stating the spread and which camp the rating follows. Below the threshold, aggregation is the unchanged weighted mean above.

The curated list is a starting point, not a whitelist: if no curated source covers the model, Claude may use any other credible review site or owner forum, tagged with the closest matching `type`. This prevents a bike with real but non-curated coverage from returning nothing.

**Cache:** keyed on `{company, model}`; stored on the happy path only when `ref` is non-empty **and** `sources_used >= 1`. The extra `sources_used` condition stops a degenerate `rating: 0.0` response from being pinned in the cache for that bike forever. The full extended response — including `rating` and `sources_used` — is cached, so a repeat call returns the same rating.

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches the curated sources, returns a per-source score array plus a synthesised overall score, 5–10 sentence explanation, and source URLs; the backend then computes the weighted aggregate rating
2. `POST https://api.anthropic.com/v1/messages` × 0–1 — **repair pass, only if step 1 ended in prose instead of the JSON object.** Re-sends step 1's text findings with no tools and an assistant prefill of `{`, so the model can only emit the object. Avoids discarding an already-paid-for web search

The response parser scans **every** text block for the first balanced `{...}` rather than assuming the last block is pure JSON, and strips any `<cite>` markup `web_search` injects into the explanation.

---

### `POST /v1/bike/offer`

Return current buying offers from Polish cycling marketplaces for a specific bike model.

```http
POST http://localhost:8000/v1/bike/offer
Content-Type: application/json

{
  "company": "Canyon",
  "model": "Grizl CF 7 ESC"
}
```

**Response:**
```json
{
  "offers": [
    {
      "brand": "Canyon",
      "model": "Grizl CF 7",
      "price": "8 999 zł",
      "is_new": false,
      "url": "https://www.olx.pl/oferta/...",
      "photos": ["https://img.olx.pl/...jpg"],
      "source": "allegro.pl"
    }
  ]
}
```

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches allegro.pl; returns 1 offer with price, condition, direct link, and photo URLs

---

### `POST /v1/bike/used`

Return the used-bike listings from OLX.pl **stored in the database** for a specific bike model — a pure read of `bike_offer` + `bike_offer_photos` (TODO-031). **No** AI call, **no** generic cache, no TTL: the rows are written only by the on-demand searcher service (see [`POST /v1/bike/used/search`](#post-v1bikeusedsearch)); nothing stored → 200 with an empty list.

```http
POST http://localhost:8000/v1/bike/used
Content-Type: application/json

{
  "company": "Trek",
  "model": "Marlin 5"
}
```

**Response:**
```json
{
  "offers": [
    {
      "brand": "Trek",
      "model": "Marlin 5",
      "price": "2 500 zł",
      "is_new": false,
      "url": "https://www.olx.pl/d/oferta/...",
      "photos": ["https://ireland.apollo.olxcdn.com/...jpg"],
      "source": "olx.pl",
      "city": "Warszawa"
    }
  ],
  "info": ""
}
```

- The bike is looked up in `bike` by `company` + `model` normalised in Python (`strip().lower()`, never SQL `lower()`) and is never created; `brand`/`model` on every offer are the bike row's stored casing.
- Offers are the bike's `bike_offer` rows with `source = 'olx.pl'` in `id` order (insertion order); `photos` are its `bike_offer_photos` rows ordered by `display_order`; `is_new` is always `false`; `city` comes from the row. `info` is always `""`.
- Unknown bike, no rows, or a DB error → `{ "offers": [], "info": "" }` (logged, never a 5xx) so the details view keeps rendering.

**Flow:** none — no outbound HTTP calls; one DB read of `bike` + `bike_offer` + `bike_offer_photos`.

**Tests:** `scripts/test_search.py` TC-30 (seeded fixture bike with 2 `olx.pl` offers → exactly those 2 in `id` order, photos in `display_order`, < 5 s — the read is ~0.5 s, the rest is Windows refusing `localhost` as `::1` first, no generic-cache row) and TC-31 (unknown bike → 200 `{ "offers": [], "info": "" }` in < 5 s).

---

### `POST /v1/bike/used/search`

Run the OLX search **on demand** through the separate searcher service (`searcher/`, TODO-031) and wait for it. The searcher runs the Claude Code CLI (subscription OAuth token — no Anthropic API key) with `bike_offer_olx.md`, scrapes up to 4 photos per listing with Playwright, and **replaces** the bike's `olx.pl` rows in `bike_offer` + `bike_offer_photos` — so the next `POST /v1/bike/used` returns them. Triggered by the frontend's **Poproś o dane** button in the "Używane" card (alongside `POST /v1/bike/missing`); also usable from `curl`. Never cached.

```http
POST http://localhost:8000/v1/bike/used/search
Content-Type: application/json

{
  "company": "Trek",
  "model": "Marlin 5"
}
```

**Response:** the searcher's `{ offers, info }` — the same shape as `POST /v1/bike/used` (the searcher's extra `bike_id` / `saved` fields are dropped). A search that finds nothing is a **200** with `offers: []`.

- **404** `"Bike not found"` when the bike is not in the `bike` table (Python-normalised brand/model compare, like `/v1/bike/missing`). The searcher itself creates missing bikes for direct `curl` calls, but the backend never lets anonymous web traffic mint `bike` rows — they would surface in the DB-first search — nor spend a subscription run on them.
- **503** when `SEARCHER_URL` or `SEARCHER_API_KEY` is unset (`"OLX searcher is not configured"`), when the searcher cannot be reached / does not answer within `SEARCHER_TIMEOUT` (default 600 s; connect timeout 10 s) (`"OLX searcher unavailable"` — the exception text stays in the log), or when a search is already running (`"OLX searcher is busy — try again in a moment"`): the backend admits `SEARCHER_MAX_INFLIGHT` (default 1, never more than the searcher's `SEARCHER_MAX_CONCURRENT`) distinct searches and the searcher answers 503 itself when its slot is taken — nothing queues, because a queued search would outlive the timeout and end in a second paid run. A second request for the same `company`/`model` while one is running joins that search instead of starting another.
- **502** when the searcher answers with a non-200/503 — its `detail` (≤ 300 chars) is passed through (e.g. `401` for a wrong `SEARCHER_API_KEY`, `502` when the `claude` CLI fails) — or with a malformed body.
- `company` / `model` must be non-empty and at most 255 characters (422).

**Flow:**
1. `POST {SEARCHER_URL}/v1/search/olx` × 1 — the searcher service (header `X-Searcher-Key: $SEARCHER_API_KEY`, body `{company, model}`), which runs the `claude` CLI once (`WebSearch`/`WebFetch`, `claude-haiku-4-5-20251001`) and Playwright once per listing, then writes the rows. The backend itself makes no Anthropic call.

**Tests:** `scripts/test_search.py` TC-32 — an unknown bike is a **404** whatever the searcher's state; then it probes `GET {SEARCHER_URL}/health` (3 s) and, when reachable, runs a live Trek Marlin 5 search (200, every `url` on `https://www.olx.pl/`, `source = "olx.pl"`, no generic-cache row) and checks that `POST /v1/bike/used` then returns the same offers (DB round-trip); otherwise expects **503** and prints SKIP for the live part.

---

### `POST /v1/bike/ceneo`

Return current buying offers from ceneo.pl for a specific bike model.

```http
POST http://localhost:8000/v1/bike/ceneo
Content-Type: application/json

{
  "company": "Canyon",
  "model": "Grizl CF 7 ESC"
}
```

**Response:**
```json
{
  "offers": [
    {
      "brand": "Canyon",
      "model": "Grizl CF 7",
      "price": "8 999 zł",
      "is_new": true,
      "url": "https://www.ceneo.pl/rowery/canyon-grizl-cf-7",
      "photos": [],
      "source": "ceneo.pl"
    }
  ],
  "info": ""
}
```

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches ceneo.pl; returns 1 offer with price, condition, and direct link

---

### `POST /v1/bike/decathlon`

Return the current buying offer from decathlon.pl for a specific bike model.

```http
POST http://localhost:8000/v1/bike/decathlon
Content-Type: application/json

{
  "company": "Rockrider",
  "model": "ST 100"
}
```

**Response:**
```json
{
  "offers": [
    {
      "brand": "Rockrider",
      "model": "ST 100",
      "price": "1199 zł",
      "is_new": true,
      "url": "https://www.decathlon.pl/p/rockrider-st-100",
      "photos": [],
      "source": "decathlon.pl"
    }
  ],
  "info": ""
}
```

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches decathlon.pl; returns 1 new offer with price and direct link (no photos — pages require JS rendering)

---

### `POST /v1/equipment/details`

Return an overview, component-tree spec sheet, and photos for a piece of cycling equipment (helmet, light/electronics, lock/security, or apparel/bags/accessories). The gear counterpart to `/v1/bike/details`. **No shopping/offer links** are ever included.

```http
POST http://localhost:8000/v1/equipment/details
Content-Type: application/json

{
  "company": "POC",
  "model": "Octal MIPS",
  "category": "helmets"
}
```

- `company` is optional (defaults to `""`), `model` is required, `category` is optional — one of `helmets`, `lights`, `locks`, `apparel`. If `category` is omitted it is **inferred** from the item name (keyword match; falls back to `apparel`).

**Response includes:** `category` (resolved slug), `description` (4–5 sentence cited overview), `components` (same category → subcategory → element → spec tree as bikes), `photos` (up to 8 manufacturer product image URLs). No offer/buy links.

**Flow (all three run in parallel via `asyncio.gather`):**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku, one focused search using the resolved category's `equipment_details_{slug}.md` prompt, returns the component tree (web_search currently disabled behind a `TODO` flag, mirroring `/v1/bike/details`)
2. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool + prompt caching, generates a 4–5 sentence equipment overview
3. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool finds the official manufacturer product page URL, then Playwright (`PLAYWRIGHT_HEADLESS`; unset = visible browser) scrapes up to 8 product `<img>` URLs from the rendered page

**Parsing:** same shared `extract_json()` as `/v1/bike/details` — see that endpoint's Parsing note.

**Cache:** keyed on `{company, model, category}`; always cached (empty is a valid result).

---

### `POST /v1/equipment/review`

Return an aggregated review score, explanation, and source links for a piece of cycling equipment. Review/forum **source** links are allowed; offer/buy links are never included.

```http
POST http://localhost:8000/v1/equipment/review
Content-Type: application/json

{
  "company": "POC",
  "model": "Octal MIPS"
}
```

**Response:**
```json
{
  "score": 8,
  "explanation": "The POC Octal MIPS is widely praised as one of the most protective...",
  "ref": ["https://..."]
}
```

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches for 3–5 reviews, then synthesises a score 0–10, a 5–10 sentence explanation, and one source URL

**Cache:** keyed on `{company, model}`; cached **only when `ref` is non-empty** (fallbacks are never cached).

---

### `POST /v1/bike/parse`

Extract structured bike attributes (brand, model, year, wheel size, electric flag) from a free-text query. Used by the frontend to auto-populate the structured search fields before the user submits their search.

```http
POST http://localhost:8000/v1/bike/parse
Content-Type: application/json

{
  "text": "Looking for Trek Marlin 7 2023, 29 inch wheels, with suspension"
}
```

**Response:**
```json
{
  "brand": "Trek",
  "model": "Marlin 7",
  "year": 2023,
  "wheel_size": "29\"",
  "is_electric": null
}
```

Fields not found in the text are returned as `null`. All fields are optional in the response. Only these five fields are extracted — rider height/weight, suspension and kids flags were removed (TODO-023), so text mentioning only those yields the 400 below.

**`400 Bad Request` when nothing could be extracted.** If *every* field would be `null`, the
endpoint returns `{"detail": "Bike not available in our database"}` instead of an all-`null`
200 — such a payload is useless to the caller, since it populates no filters. The frontend
turns this into a warning above the search box and does **not** run the search.
Both the genuine "no attributes mentioned" case and `parse_free_text`'s exception fallback
land here, since both yield no fields. An empty parse is **not** cached, and the check also
runs on the cache-hit path so an all-`null` row written by an older build cannot be served
as a 200.

`brand` is also extracted from Polish and English brand-constraint phrasing — "Firma tylko Tesla", "marka Trek", "tylko Specialized", "brand only Canyon" — copying the name verbatim (casing preserved). The name after such a keyword is extracted even when it is not a known bicycle maker. Place names following a preposition ("po Wrocławiu", "w Krakowie") are treated as locations, never as a brand. A text whose only candidate was such a place name therefore has nothing left to extract and comes back as a `400`.

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku (no web search, pure text extraction) with `app/prompts/bike_parse.md` system prompt; returns a JSON object with only the confident field extractions
