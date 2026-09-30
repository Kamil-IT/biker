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
pip install -U anthropic   # existing venv: -r never upgrades an installed unpinned package; the Docker image always gets the newest
copy .env.example .env   # then edit .env with your real ANTHROPIC_API_KEY
python scripts/migrate_photos_bike_id.py --dry-run   # REQUIRED once on every existing database — see note below
python scripts/migrate_photos_bike_id.py
uvicorn app.main:app --reload --port 8000
```

> **Run `scripts/migrate_photos_bike_id.py` once on every existing database before starting the app** — SQLite
> `cache.db` or PostgreSQL (`--db <sqlite file>` / `--url <sqlalchemy url>` pick another one; the default is
> `$DATABASE_URL`, else `cache.db`). Bike photos are keyed on `bike.id` now, not on the details row, and `init_db()`'s
> `create_all()` never `ALTER`s an existing table, so an older `bike_detail_photos` keeps `bike_detail_id`. Until the
> script has run, `POST /v1/bike/photos` answers `{"photos": []}` and logs an **ERROR** naming the script, and the
> **searcher refuses to start**.
>
> **Deploy order (data safety):** the migration must run against a database BEFORE the new backend or searcher runs against it. On
> production: (1) migrate Cloud SQL, (2) deploy backend and searcher together right after, (3) deploy the frontend. Once migrated, the
> **old** backend breaks on that database (it still writes `bike_detail_id`): expect a short window between steps 1 and 2 in which
> its details save fails (rolls back, logs a warning, no data lost). The new `save_bike_details` updates the `bike_detail` row in
> place instead of deleting it, so it can no longer cascade-delete photos through the old `bike_detail_id` foreign key. See [Photos migration](#photos-migration-scriptsmigrate_photos_bike_idpy) below and
> [`app/DB_MIGRATION.md`](app/DB_MIGRATION.md).

`SEARCHER_URL` / `SEARCHER_API_KEY` (TODO-031/032/033/035) point `POST /v1/bike/used/search`, `POST /v1/bike/decathlon/search`,
`POST /v1/bike/allegro/search` and `POST /v1/bike/photos/search` at the on-demand searcher (top-level `searcher/`, `http://localhost:8100` locally; the key
is sent as `X-Searcher-Key` and must equal the searcher's own `SEARCHER_API_KEY`). `SEARCHER_TIMEOUT` (seconds, default 600)
bounds one search. `SEARCHER_MAX_INFLIGHT` (default **10**, was 2) is how many distinct searches this backend lets run at once across
all five routes — the "Nowe" card fires the Decathlon and Allegro searches together and a details page can add OLX and photos — and must never exceed the searcher's
capacity (`SEARCHER_MAX_CONCURRENT`, locally 10; on Cloud Run `--max-instances 10` with `--concurrency 1`); an eleventh search is
refused with 503, nothing queues. The cap is per backend process: two backend instances admit up to 20 between them. Leave `SEARCHER_URL` unset to run without the searcher — all five routes then answer 503,
while `POST /v1/bike/used/olx`, `POST /v1/bike/decathlon`, `POST /v1/bike/allegro` and `POST /v1/bike/photos` and `POST /v1/bike/review` keep serving whatever is stored in
the database.

```bash
# In a second terminal:
python scripts/test_search.py   # one happy path per endpoint without an Anthropic call: search (DB hit) + search-cache, details-cache, missing, popular, used, used/search, decathlon, decathlon/search, allegro, allegro/search, photos, photos/search, review, review/search; add --ai for the API cases
python scripts/test_details.py  # smoke-test POST /v1/bike/details
```

```bash
# One-off per existing database: re-key bike_detail_photos to bike_id (idempotent)
python scripts/migrate_photos_bike_id.py --dry-run
python scripts/migrate_photos_bike_id.py

# One-off per existing database (TODO-037): copy the generic-cache bike reviews into bike_review / bike_review_source
# (idempotent; --force overwrites, --db / --url pick another database). The tables themselves are created by init_db().
python scripts/copy_review_cache_to_table.py --dry-run
python scripts/copy_review_cache_to_table.py
```

### Seed the popular bikes (`bike_popular`)

The home page's "Najpopularniejsze rowery" section (TODO-034) is served by `GET /v1/bike/popular` from the
`bike_popular` table, which nothing in the app writes. Fill it with:

```bash
python scripts/seed_popular_bikes.py              # replace the table contents with 3 automatically picked bikes
python scripts/seed_popular_bikes.py --dry-run    # only print what would be inserted
python scripts/seed_popular_bikes.py --count 5    # pick 5 instead of 3
python scripts/seed_popular_bikes.py --bike "Giant|Revolt Advanced Pro" --bike "Trek|Marlin 5"   # your own list, in this order
```

The script targets `$DATABASE_URL` (the local `biker-pg` through `.env`) and **replaces** the table contents on every run.
Without `--bike` it picks bikes that have complete data — a `bike_detail` row (the description the card shows), photos in
`bike_detail_photos`, and a stored review in `bike_review` with a real (non-zero) `rating` —
so every card shows points and a blurb. `--bike "Brand|Model"` (repeatable) overrides the automatic pick and fixes the
order. Production gets the same rows only when the user decides to run it there.

### Docker image

`backend/Dockerfile` is the image docker compose and Cloud Run both use: Python 3.14 slim, `patchright install --with-deps chromium`,
non-root user, `uvicorn` on `$PORT` (default 8000). `.env`/`cache.db` are excluded by `.dockerignore` — `ANTHROPIC_API_KEY`
and `DATABASE_URL` come from the environment; under compose the Cloud SQL password arrives as the mounted pgpass file (`PGPASSFILE`). `PLAYWRIGHT_HEADLESS=true` (read by `app/browser_config.py`) runs the equipment
photo scraper without a display; unset keeps the visible browser for local debugging (the OLX image scraper moved to
`searcher/` in TODO-031, the Allegro one was deleted in TODO-033 without a replacement — allegro.pl answers 403 to Chromium,
so Allegro offers carry no photos — and the backend launches no marketplace browser any more). See the root
`README.md` § Run with Docker.

On Cloud Run (`scripts/deploy.ps1`, service `biker-backend`) the same image gets
`DATABASE_URL=postgresql+psycopg://biker@/biker?host=/cloudsql/biker-engine-prod:europe-central2:biker-pg` — the unix socket
mounted by `--add-cloudsql-instances`, still no password — plus `PGPASSWORD` and `ANTHROPIC_API_KEY` as Secret Manager
references (`db-password`, `anthropic-api-key`). libpq picks `PGPASSWORD` up exactly like the pgpass file, so nothing in
`app/` changes between compose and Cloud Run. See the root `README.md` § Deploy to GCP.

Browser launches are capped per process by `BROWSER_MAX_CONCURRENCY` (default 2, `app/browser_config.py` `BROWSER_SLOTS`):
every scraper left in the backend (only the equipment photo finder since TODO-035 — the bike photo scraper moved to the searcher) holds one slot around `sync_playwright()` + `chromium.launch()`.
One launch costs 0.5–0.9 GiB (node driver + Chromium tree, and Cloud Run's `/tmp` is memory-backed), so two fit in the
2 GiB instance next to the app; a third request waits for a slot instead of getting the instance OOM-killed. Raise it only
together with `--memory` in `scripts/deploy.ps1`.

## Unit tests

```bash
cd backend
pytest -m "not llm"
```

`pytest.ini` scopes default collection to `scripts/test_browser_slots.py`, `scripts/test_searcher_client_photos.py`,
`scripts/test_searcher_client_review.py` and `scripts/test_reviews_repository.py`, so a bare `pytest` run covers the stored-review read and the cache-copy script (temp SQLite),
the searcher client's photo and review routes (mocked httpx: request, single-flight, busy mapping, in-flight cap 10, body validation)
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
| Details | `bike` + `bike_detail` + `bike_detail_component` | `bike.(brand_norm, model_norm)` — `.strip().lower()` of brand+model | none (TODO-035) |

Both reference the shared `bikes` identity row, so a bike found by search and a bike with cached details are the same row.

- Both are indexed on their key columns and upsert on conflict (a re-run refreshes the entry).
- Freshness: searches are fresh for 24 h (`store.SEARCH_TTL_SECONDS`, a module constant on `time_stored`; there is no per-row `ttl_seconds` column) and a stale one is treated as a miss (never served). **Details have no TTL** since TODO-035 (`repository.TTL_DETAILS` was removed): a stored details row is served whatever its age.
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
- **Photos are not part of the details response any more** (TODO-035): `BikeDetailsResponse` has no `photos` field. They live in `bike_detail_photos`, keyed on `bike_id` (not on the details row), are read by `POST /v1/bike/photos` (`app/photos_repository.py`, `display_order, id`) and written only by the searcher's photo search — insert-only, for a bike that has none. `save_bike_details` neither writes nor deletes them.
- `description` and `components` remain JSON columns on `bike_details`.
- `save_bike_details` updates the bike's `bike_detail` row **in place** (stable id, description replaced, component rows deleted and re-inserted) instead of deleting and re-creating it. `updated_at` is set on every save, but nothing reads it for freshness any more.

See [`app/DB_MIGRATION.md`](app/DB_MIGRATION.md) for the full schema and what is still pending (search).

#### Photos migration (`scripts/migrate_photos_bike_id.py`)

`bike_detail_photos` used to hang off the details row (`bike_detail_id` → `bike_detail.id`); with the photos searcher
(TODO-035) it hangs off the bike: `bike_detail_id` is **replaced** by `bike_id INTEGER NOT NULL REFERENCES bike(id) ON DELETE
CASCADE` (indexed). Columns afterwards: `id`, `bike_id`, `url`, `display_order`. The table keeps its name.

```bash
cd backend
python scripts/migrate_photos_bike_id.py --dry-run     # report only; database: $DATABASE_URL (backend/.env), else cache.db
python scripts/migrate_photos_bike_id.py               # migrate
python scripts/migrate_photos_bike_id.py --db path/to/copy.db
python scripts/migrate_photos_bike_id.py --url postgresql+psycopg://biker:biker@localhost:5432/<db>
```

- One transaction on SQLite and PostgreSQL; SQLite rebuilds the table, PostgreSQL alters it in place. Before committing it
  checks row by row that every photo kept its id, url and `display_order` and points at the bike its old details row belonged to —
  any mismatch rolls back and leaves the database unchanged (exit code 1).
- Photo rows whose details row (or that row's bike) is missing cannot be re-keyed: they are listed, copied into the table
  `bike_detail_photos_orphans` (`id, bike_detail_id, bike_id, url, display_order`) in the same transaction (and that copy is verified),
  and left out of the migrated table — never dropped silently. Row and bike counts are printed before and after.
- PostgreSQL runs under `LOCK TABLE … SHARE ROW EXCLUSIVE` on the photos and details tables, so concurrent writes cannot skew the verification.
- Idempotent: an already migrated table is re-checked (`NOT NULL`, the FK to `bike` with `ON DELETE CASCADE`, the `bike_id` index) and only a missing piece is repaired; an absent table is left to `init_db()`, which creates it with the new schema. Importable as
  `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`.
- **Required on every existing database, and BEFORE the new backend or searcher runs against it** (production order: migrate Cloud SQL, deploy backend + searcher together, then the frontend): the searcher refuses to start on an unmigrated database, the backend answers `{"photos": []}` (ERROR log) until it has run, and the old backend breaks on a migrated database.
- The older `migrate_bike_details.py` / `test_details_parity.py` (blob → ORM backfill and parity test) no longer exist in the tree.

## Search Cache

`POST /v1/bike/search` resolves through a **two-step cascade** (TODO-024), stopping at the first step that produces bikes:

| # | Step | Cost | Condition |
|---|------|------|-----------|
| 1 | **DB details search** (`repository.find_bikes_by_details`) | 0 outbound calls | ≥1 DB-checkable field is set **and** ≥1 bike matches every one of them |
| 2 | **One** Claude call (`app/bike_finder.py`, `app/prompts/bike_search.md`) | 1 call | Everything else |

The endpoint does **not** use the generic response cache (`app/cache.py`, table `endpoint_req_to_body_cache`) at all — see [No generic cache for search](#no-generic-cache-for-search).

### How the DB step matches

A bike matches when **every** checkable field given matches. A bike missing the relevant spec row does not match that field, and a bike with no `bike_detail` row can only match on `brand`/`model`. Brand and model are compared **exactly** after Python `.strip().lower()` (never SQL `lower()`, which is ASCII-only).

| `SearchRequest` field | Source in DB | Rule |
|---|---|---|
| `brand`, `model` | `bike.brand` / `bike.model` | case-insensitive exact |
| `wheel_size` | any `spec_key='Wheel Size'`, or `Wheels/*` `Size` | number token (`29` in `29 x 2.4`); `700c` ↔ `28`, `650b` ↔ `27.5` |
| `frame_size` | `Frame / Frame`, `spec_key='Sizes'` / `'Size'` | size token in the list (`SM`/`MD`/`LG` aliased) |
| `is_electric` | `Electric / Powertrain` category present / absent | |
| `bike_type`, `year`, `search` | — | **not checkable**, ignored by the DB step |

A request with **only** non-checkable fields skips the DB and goes straight to the AI call. **Every** matching DB bike is returned (no cap, TODO-025), highest `match_score` first — never topped up with AI results.

`match_score` / `explanation` / `accessories` of a DB hit come from the bike's most recent `search_bike_rating_cache` row when one exists; otherwise `match_score = 10`, `accessories = []` and the explanation lists the matched fields, e.g. `"Pasuje: marka Trek, koła 29\", elektryczny."` (Polish, like the AI-generated explanations).

### No generic cache for search

`/v1/bike/search` neither reads nor writes `endpoint_req_to_body_cache` (`get_cached` / `set_cached`). That table has **no TTL** and the first write wins, so any answer stored there is served for that exact request body forever. That is how the answers stored before TODO-025 (capped at 5 bikes) kept coming back after the cap was removed. The DB step always reflects the current `bike` table, and an AI answer is stored only as data: `store.save_search` writes the bikes into `bike` and their ratings into `search_cache` + `search_bike_rating_cache`. A later search by brand/model then finds those bikes in the DB. A spec filter (`wheel_size`, `frame_size`, `is_electric`) also needs their `bike_detail` rows, and free-text-only or `bike_type`/`year`-only searches are never checkable. Those repeats call Claude again every time, because nothing replays an earlier answer. The old `/v1/bike/search` rows in `endpoint_req_to_body_cache` are dead: nothing reads them.

**Test:** `scripts/test_search.py` `case_search_db_hit_and_search_cache` seeds a stale generic-cache row for the exact request body and asserts the DB answer is returned instead; the `--ai` free-text case asserts no generic-cache row is written.

## Endpoints

**Anthropic 400s:** any endpoint whose Anthropic API call is rejected with a 400 (`anthropic.BadRequestError`, e.g. *"Your credit balance is too low to access the Anthropic API…"*) answers **400** `{"detail": "<Anthropic's error message>"}` via the app-wide handler in `app/main.py`, instead of an unhandled 500 (or, for search, a 502). The searcher-backed `/v1/bike/*/search` routes answer the same **400** `{"detail": …}` when the searcher's `claude -p` hit the Claude subscription limit (TODO-038, handler `searcher_limit_reached`).

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
  "frame_size": "M"
}
```

All fields except `search` default to `null` (no constraint). The backend assembles an enriched query such as `"Brand: Trek, Type: Gravel, Frame size: M — comfortable bike…"` and, on a DB miss, sends it to a single Claude call. Nothing is served from a response cache, so every request is answered from the current DB (or the AI). `price_max`, `rider_height_cm`, `rider_weight_kg`, `has_suspension` and `is_kids` were removed (TODO-023), and so were `gender`, `frame_material`, `brake_type`, `drivetrain`, `belt_drive` and `battery_capacity_wh` (together with the search form's "Opcje zaawansowane" group); they are silently ignored if sent, so a payload made only of them is rejected with 422.

**Flow:**
0. DB reads only — the DB details search over `bike` + `bike_detail_component` (skipped when no checkable field is set). **A hit returns immediately, making zero outbound HTTP calls.** No generic-cache lookup. See [Search Cache](#search-cache)
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku (no tools) with `app/prompts/bike_search.md` and the enriched query; returns every matching bike as a JSON array (min 1: when nothing meets every filter, the closest bike with a low `match_score` and an explanation naming the unmet filter; `max_tokens=8000`, a warning is logged on `stop_reason == "max_tokens"`), parsed with `app/json_extract.extract_json()`; `explanation` and `accessories` come back in Polish (brand/model and named components untranslated). Runs only on a DB miss

A response with no parseable JSON returns `bikes: []` (never a 502) and nothing is stored; an upstream API error is a 502, except an Anthropic 400, which is a 400 with Anthropic's message. When the AI returns bikes, they are written to `bike` + `search_cache` + `search_bike_rating_cache` via `store.save_search` — never to the generic cache. A DB-served result is not written anywhere — see [Search Cache](#search-cache).

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

Follow-up details lookup served **purely from the ORM details tables** (`bike` + `bike_detail` + `bike_detail_component`, read via `app/repository.py`) — makes **no** web/Claude call. Returns 404 if the `(company, model)` pair is not stored; there is **no TTL** (a stored row is served whatever its age, TODO-035). The `company`/`model` match is case-insensitive, and the response echoes the casing you asked with.

```http
GET http://localhost:8000/v1/bike/details-cache?company=Canyon&model=Grizl%20CF%207%20ESC
```

**Response:** identical shape to `POST /v1/bike/details` (`company`, `model`, `description`, `components` — no `photos`; use `POST /v1/bike/photos`).

**Flow:** none — database read only.

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

### `GET /v1/bike/popular`

The hand-curated "Najpopularniejsze rowery" list the home page shows before the first search (TODO-034). One row per bike in `bike_popular` (`bike_id` FK → `bike.id` ON DELETE CASCADE, unique; `position` = display order, 1 first, deliberately not unique), written only by `scripts/seed_popular_bikes.py` (see [Seed the popular bikes](#seed-the-popular-bikes-bike_popular)). A pure DB read via `app/popular_repository.py` — **no** AI call, **no** generic cache, no TTL. The expert rating shown on each card is **not** part of this response: the frontend asks `POST /v1/bike/review` for every bike separately.

```http
GET http://localhost:8000/v1/bike/popular
```

**Response:**
```json
{
  "bikes": [
    { "brand": "Giant", "model": "Revolt Advanced Pro", "description": "Pierwsze zdanie opisu. Drugie zdanie opisu." },
    { "brand": "Trek", "model": "Marlin 5", "description": "" }
  ]
}
```

- Rows ordered by `position`, then `id`. `brand` / `model` are the `bike` row's values as stored (the single source of display casing).
- `description` = the `text` of the bike's stored `BikeDescription` JSON (`bike_detail.description`) cut to its **first two sentences** by `popular_repository.first_sentences`: a sentence ends with `.` `!` `?` or `…` (plus an optional closing quote/bracket) followed by whitespace and an upper-case word, so `ok. 12 kg` or `np. 29-calowe` does not split; there is no abbreviation dictionary, so an upper-case brand right after an abbreviation (`m.in. Shimano`) still splits — a rare over-cut on a card blurb, accepted. `""` when the bike has no `bike_detail` row or its JSON does not parse (logged at WARNING). The details TTL is ignored — an old description is still a fine blurb.
- Empty table → **200** `{ "bikes": [] }`. A DB error → **200** `{ "bikes": [] }` + ERROR log, never a 500 (the home page must render regardless).
- `bike_popular` is created at startup by `init_db()` like every other table — no migration step. Deleting a `bike` row cascades to its `bike_popular` row.

**Flow:** none — no outbound HTTP call; one DB read (`bike_popular` joined to `bike`, left-joined to `bike_detail`).

**Tests:** `scripts/test_search.py` `case_popular` against a live server: two fixture bikes in `bike_popular` (B at position 1 without details, A at position 2 with a three-sentence description whose first sentence contains `ok. 12 kg`) → 200, B before A among the returned bikes, A's `description` = exactly the first two sentences, B's `""`, stored casing echoed, < 5 s, no generic-cache row.

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

**Response includes:** `description` (4–5 sentence plain-text overview, written in Polish), `components` (category tree — each element `description` is Polish, while category/subcategory/spec keys, element names and spec values stay English). **No `photos`** since TODO-035 — they come from [`POST /v1/bike/photos`](#post-v1bikephotos).

On the happy path the result is also written to the queryable ORM details tables via `repository.save_bike_details` (see [Details storage — normalised ORM tables](#details-storage--normalised-orm-tables)). A repeat is served from those tables with **zero outbound calls** and no expiry; the lookup is case-insensitive and the response echoes the caller's casing. It writes no photos and never touches the stored ones.

**Flow (both run in parallel via `asyncio.gather`):**
1. `POST https://api.anthropic.com/v1/messages` × 8 — Claude Haiku with `web_search_20250305` tool, one focused search per component category (sequential): Frame, Drivetrain, Brakes, Wheels, Cockpit, Saddle & Seatpost, Lighting, Accessories
2. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool + prompt caching, generates a 4–5 sentence bike overview in Polish

No photo search runs here any more (the bike photo finder moved to the searcher).

**Parsing:** each category response goes through the shared `app/json_extract.py` `extract_json()`, which pulls the first parseable fenced block or balanced `{...}` / `[...]` out of surrounding prose. The model routinely narrates ("I'll search for the Brakes specifications...") before emitting the JSON, so a parser that assumed the whole response was JSON silently dropped whole categories. A category with genuinely no JSON in its response is logged and skipped — never a 502.

---

### `POST /v1/bike/photos`

Return the photos **stored in the database** for a bike (TODO-035) — a pure read of `bike_detail_photos` through `app/photos_repository.py`, ordered by `display_order, id`. **No AI call, no generic cache, no TTL.** The details page calls it when it opens; the rows get there only through `POST /v1/bike/photos/search` below.

```http
POST http://localhost:8000/v1/bike/photos
Content-Type: application/json

{
  "company": "Trek",
  "model": "Marlin 5"
}
```

**Response:** `{ "photos": ["https://...jpg", "https://...jpg"] }` — an unknown bike, a bike with no stored photos or a database error (an unmigrated `bike_detail_photos` included — that one also logs an **ERROR** naming `scripts/migrate_photos_bike_id.py`) is a **200** `{ "photos": [] }`, never an error. The frontend then shows the **Poproś o dane** button in the gallery slot.

- `company` / `model` must be non-empty and at most 255 characters (422).
- The app never replaces or deletes a photo; a details re-save leaves them alone.

**Flow:** none — no outbound HTTP calls; one DB read of `bike` + `bike_detail_photos`.

**Tests:** `scripts/test_search.py` `case_photos` — a seeded fixture bike with three photo rows inserted out of order and **no** `bike_detail` row → exactly those URLs in `display_order`, no generic-cache row, under 5 s; an unknown bike → a fast empty 200.

---

### `POST /v1/bike/photos/search`

Run the bike photo search **on demand** through the separate searcher service (`searcher/`, TODO-035) and wait for it. Given a bike that already has stored photos, the searcher returns them straight from the database without a search. Otherwise it runs the Claude Code CLI once (subscription OAuth token — no Anthropic API key) with `bike_photos.md` to find the official manufacturer product page, checks that URL is a public http(s) address, opens the page with Playwright once (`domcontentloaded` + 4 s wait) and takes up to 8 product `<img>` URLs (the former backend scraper, same `_IMG_SRC` / `_SKIP` regexes), then stores them in `bike_detail_photos` — **only for a bike that has none, and never replacing anything**. A search that finds nothing writes nothing. Triggered by the frontend's **Poproś o dane** button in the gallery slot (alongside `POST /v1/bike/missing`); also usable from `curl`. Never cached.

```http
POST http://localhost:8000/v1/bike/photos/search
Content-Type: application/json

{
  "company": "Trek",
  "model": "Marlin 5"
}
```

**Response:** `{ "photos": [...] }` — the bike's photos as now stored, in display order (the searcher's extra `bike_id` / `saved` fields are dropped). A search that finds nothing is a **200** with `photos: []`.

- **404** `"Bike not found"` when the bike is not in the `bike` table (Python-normalised brand/model compare) — checked **before** any searcher call, so anonymous traffic cannot spend a subscription run.
- **503** when `SEARCHER_URL` or `SEARCHER_API_KEY` is unset (`"Photos searcher is not configured"`), when the searcher cannot be reached / does not answer within `SEARCHER_TIMEOUT` (default 600 s; connect timeout 10 s) (`"Photos searcher unavailable"` — the exception text stays in the log), or when no search slot is free (`"Photos searcher is busy — try again in a moment"`): the backend admits `SEARCHER_MAX_INFLIGHT` (default 10) distinct searches across **all five** routes, the searcher answers 503 itself when its own slots are taken, and Cloud Run answers **429** once every `biker-searcher` instance is busy (`--max-instances 10`, `--concurrency 1`) — the 429 is mapped to the same 503 busy; nothing queues. A second request for the same `company`/`model` while one is running joins that search instead of starting another.
- **400** `{"detail": "<the CLI's notice>"}` when the searcher's `claude -p` run was refused because the Claude subscription limit is used up (TODO-038) — the searcher answers 400 with the CLI's own text (e.g. *"You've hit your session limit · resets 1am (Europe/Warsaw)"*), `searcher_client` raises `SearcherLimitReached`, and the app-wide handler `searcher_limit_reached` in `app/main.py` relays it — the same shape as the Anthropic credit-balance 400. Not a 502 / 503.
- **502** when the searcher answers with a non-200/400/503/429 — its `detail` (≤ 300 chars) is passed through (e.g. `401` for a wrong `SEARCHER_API_KEY`, `502` when the `claude` CLI fails) — or with a malformed body. Unlike the old in-backend finder, a failed CLI run is an error here (the UI button becomes clickable again), not an empty `photos`.
- `company` / `model` must be non-empty and at most 255 characters (422).
- **Security:** the page URL comes out of an LLM reading the web while the searcher's browser runs inside our network, so the CLI gets `WebSearch` only (no `WebFetch`), the product URL must be http/https on public addresses only, Playwright's request routing aborts every request to a non-public host (redirects, sub-resources, XHR, JS navigations; service workers blocked), and stored image URLs must be http/https, ≤ 2048 chars, not a local name or private IP literal. Accepted limitation: DNS rebinding.
- **No rate limit** on this trigger yet: with the limit at 10, anyone can start up to 10 parallel subscription runs for existing bikes, and a bike whose search found nothing can be searched again without limit (the UI disables the button, `curl` does not). The per-IP rate limit ("Step 2" of the deploy) is the planned answer.
- With 10 slots but 2 browsers per searcher process, a local/compose searcher can make searches queue for a browser and exceed the backend's 600 s timeout (the backend answers 503; the searcher still finishes and stores the photos, so a retry returns them without a second paid run). On Cloud Run (`--concurrency 1`) this does not occur.
- The searcher's `saved` is the number written by the search; a caller that joined a running search gets the same value although it wrote nothing (the backend drops the field).
- Known pre-existing issue, out of scope: `save_bike_details` finds the bike by exact brand/model while the photo lookup uses the normalised identity, and duplicate `bike` rows that differ only by casing exist, so photos on the newer duplicate are unreachable through this endpoint.
- A run took 36 s end to end in the searcher's 2026-09-29 probe (Trek Marlin 4: CLI 18 s, scrape 17 s, 6 photos); the repeat request was answered from the database in 0.5 s.

**Flow:**
1. `POST {SEARCHER_URL}/v1/search/photos` × 1 — the searcher service (header `X-Searcher-Key: $SEARCHER_API_KEY`, body `{company, model}`), waited for up to `SEARCHER_TIMEOUT`; it reads `bike_detail_photos`, and only if the bike has none runs the `claude` CLI once (`WebSearch` only), opens the manufacturer page with Playwright once and writes the rows. The backend itself makes no Anthropic call and launches no browser for this route.

**Tests:** `scripts/test_search.py` `case_photos_search` — an unknown bike is a **404** before any searcher call. Deliberately no live photo run (every searcher run is a paid subscription search); `searcher/scripts/test_searcher.py` covers the searcher's own route without one.

---

### `POST /v1/bike/review`

Return the expert review **stored in the database** for a specific bike model — a pure read of `bike_review` + `bike_review_source` (TODO-037, the same move `/v1/bike/allegro` made in TODO-033). **No** AI call, **no** generic cache, no TTL: the rows are written only by the on-demand searcher service (see [`POST /v1/bike/review/search`](#post-v1bikereviewsearch)). The old `web_search` finder rows under the generic-cache key `/v1/bike/review` are not read any more; `scripts/copy_review_cache_to_table.py` carries the usable ones over once.

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

- Unknown bike, no stored review or a database error (that one also logs an **ERROR**) → **200** with the empty review `{ "score": 0, "explanation": "", "ref": [], "rating": 0.0, "sources_used": 0 }`, never an error. The frontend reads it as "no data" and shows the **Poproś o dane** button in the "Recenzja eksperta" section; the home page's popular cards read `rating` 0 as "Brak oceny".
- `explanation` — Polish; `score` — integer 0–10 editorial verdict; `rating` — the weighted aggregate (float 0–10) computed by the searcher; `sources_used` — number of sources that contributed a score; `ref` — source URLs in the stored order (Tier 1 → Tier 2 → Tier 3), read `ORDER BY display_order, id`.
- `company` / `model` must be non-empty and at most 255 characters (422).
- The aggregation rules (source weights 3/2/1, `DISAGREEMENT_THRESHOLD` 3.0 anchoring, `ref` ordering) now live in `searcher/app/review_finder.py`; tier list in [`backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md`](../backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md).

**Flow:** none — no outbound HTTP calls; one DB read of `bike` + `bike_review` + `bike_review_source`.

**Tests:** `scripts/test_search.py` `case_review` — a seeded fixture bike with a review and two sources → the stored values, `ref` in `display_order`, no generic-cache row, under 5 s; a bike without a review and an unknown bike → a fast empty-review 200. `scripts/test_reviews_repository.py` (pytest) covers `get_review` and the copy script.

---

### `POST /v1/bike/review/search`

Run the expert-review search **on demand** through the separate searcher service (`searcher/`, TODO-037) and wait for it. The searcher runs the Claude Code CLI once (subscription OAuth token — no Anthropic API key) over the curated review sources, computes the weighted `rating`, and **replaces** the bike's stored review and sources **only when `ref` is non-empty and `sources_used >= 1`** — an empty or degenerate result writes and deletes nothing. Triggered by the frontend's **Poproś o dane** button in the "Recenzja eksperta" section (alongside `POST /v1/bike/missing`); also usable from `curl`. Never cached.

```http
POST http://localhost:8000/v1/bike/review/search
Content-Type: application/json

{
  "company": "Canyon",
  "model": "Grizl CF 7 ESC"
}
```

**Response:** the same shape as `/v1/bike/review` — the review now stored for the bike (the searcher's `bike_id` / `saved` are dropped); a search that found nothing usable is a **200** with the empty review.

- **404** `"Bike not found"` when the bike is not in the `bike` table — checked **before** any searcher call.
- **Already stored → returned without a searcher call:** when the bike already has a stored review with a non-empty `ref` and `sources_used >= 1`, that review is returned at once (200) — a repeat click or a scripted caller cannot spend another subscription run on it.
- **503** when `SEARCHER_URL` or `SEARCHER_API_KEY` is unset (`"Review searcher is not configured"`), the searcher is unreachable / does not answer within `SEARCHER_TIMEOUT` (`"Review searcher unavailable"`), or no search slot is free (`"Review searcher is busy — try again in a moment"`; the in-flight cap `SEARCHER_MAX_INFLIGHT` and the searcher's slots are shared with all other searcher routes, Cloud Run's 429 maps to the same 503) — nothing queues. Identical concurrent requests for the same bike share one search.
- **400** `{"detail": "<the CLI's notice>"}` when the searcher's `claude -p` run was refused because the Claude subscription limit is used up (TODO-038) — the searcher answers 400 with the CLI's own text (e.g. *"You've hit your session limit · resets 1am (Europe/Warsaw)"*), `searcher_client` raises `SearcherLimitReached`, and the app-wide handler `searcher_limit_reached` in `app/main.py` relays it — the same shape as the Anthropic credit-balance 400. Not a 502 / 503.
- **502** with the searcher's `detail` (≤ 300 chars) when it fails (wrong key, `claude` CLI error, DB error) or answers with a malformed body.
- `company` / `model` must be non-empty and at most 255 characters (422).

**Flow:**
1. DB read of `bike` (404 when missing) and of `bike_review` / `bike_review_source` — a usable stored review is returned here, with **no** outbound call.
2. Otherwise `POST {SEARCHER_URL}/v1/search/review` × 1 — the searcher service (header `X-Searcher-Key: $SEARCHER_API_KEY`, body `{company, model}`), waited for up to `SEARCHER_TIMEOUT`; it runs the `claude` CLI once (`WebSearch` + `WebFetch`, no browser) and writes `bike_review` / `bike_review_source`. The backend itself makes no Anthropic call.

**Tests:** `scripts/test_search.py` `case_review_search` — an unknown bike is a **404** before any searcher call, and a bike with a seeded review gets that review back fast without a searcher call (no paid run); `scripts/test_searcher_client_review.py` covers the client with a mocked transport; `searcher/scripts/test_searcher.py` covers the searcher route without a paid run.

---

### `POST /v1/bike/allegro`

Return the allegro.pl offers **stored in the database** for a specific bike model — a pure read of `bike_offer` (TODO-033, the same move `/v1/bike/used/olx` made in TODO-031 and `/v1/bike/decathlon` in TODO-032). **No** AI call, **no** generic cache, no TTL: the rows are written only by the on-demand searcher service (see [`POST /v1/bike/allegro/search`](#post-v1bikeallegrosearch)); nothing stored → 200 with an empty list. The old `web_search` finder's rows under the generic-cache key `/v1/bike/offer` are not read any more (dead rows, deliberately not backfilled).

```http
POST http://localhost:8000/v1/bike/allegro
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
      "price": "2 319 zł",
      "is_new": false,
      "url": "https://allegro.pl/oferta/rower-gorski-mtb-trek-marlin-5-29-l-shimano-hydraulika-poserwisie-noweopony-18571327937",
      "photos": [],
      "source": "allegro.pl",
      "city": null
    }
  ],
  "info": ""
}
```

- The bike is looked up in `bike` by `company` + `model` normalised in Python (`strip().lower()`, never SQL `lower()`) and is never created; `brand`/`model` on every offer are the bike row's stored casing.
- Offers are the bike's `bike_offer` rows with `source = 'allegro.pl'` in `id` order (insertion order); `is_new` is the row's, as the searcher read it off the listing (an Allegro listing is used unless the page says new, so `false` is the common value — the frontend then shows it in the "Używane" card); `photos` is always `[]` — the Allegro search stores no photos by design (allegro.pl answers 403 to every automated fetch, Chromium included, so the searcher's photo scrape was dropped after the probes); `city` is `null`. `info` is always `""`.
- Unknown bike, no rows, or a DB error → `{ "offers": [], "info": "" }` (logged, never a 5xx) so the details view keeps rendering.
- `company` / `model` must be non-empty and at most 255 characters (422).

**Flow:** none — pure DB read of `bike` + `bike_offer`, no outbound call.

**Tests:** `scripts/test_search.py` `case_allegro` — a seeded fixture bike with 1 `allegro.pl` offer (`is_new` true, `city` null, no photo row) → exactly that offer (`url`, `price`, `city`, `photos == []`) in < 5 s with no generic-cache row under either `/v1/bike/offer` or `/v1/bike/allegro`; then an unknown bike → 200 `{ "offers": [], "info": "" }`.

---

### `POST /v1/bike/allegro/search`

Run the Allegro search **on demand** through the separate searcher service (`searcher/`, TODO-033) and wait for it. The searcher runs the Claude Code CLI (subscription OAuth token — no Anthropic API key) with `bike_offer_allegro.md` (the backend's prompt rewritten for the CLI: WebSearch results only, because allegro.pl answers HTTP 403 to every automated fetch — so a listing whose price no search snippet shows is stored with `price: ""`), stores every offer with `photos: []` (no Playwright — allegro.pl answers 403 to Chromium too, so the photo scrape that first shipped with TODO-033 was dropped after the probes on the user's decision: nothing to gain, ~10 s and a browser launch per run wasted), and **replaces** the bike's `allegro.pl` rows in `bike_offer` (≤ 3 offers; `bike_offer_photos` is never written) — so the next `POST /v1/bike/allegro` returns them. Triggered by the frontend's **Poproś o dane** button in the "Nowe" card, which fires it **together with** `POST /v1/bike/decathlon/search` (alongside `POST /v1/bike/missing`); also usable from `curl`. Never cached.

```http
POST http://localhost:8000/v1/bike/allegro/search
Content-Type: application/json

{
  "company": "Trek",
  "model": "Marlin 5"
}
```

**Response:** the searcher's `{ offers, info }` — the same shape as `POST /v1/bike/allegro` (the searcher's extra `bike_id` / `saved` fields are dropped). A search that finds nothing is a **200** with `offers: []` (the stored rows are kept).

- **404** `"Bike not found"` when the bike is not in the `bike` table (Python-normalised brand/model compare, like `/v1/bike/used/search`) — checked **before** any searcher call, so anonymous traffic can neither mint `bike` rows nor spend a subscription run.
- **503** when `SEARCHER_URL` or `SEARCHER_API_KEY` is unset (`"Allegro searcher is not configured"`), when the searcher cannot be reached / does not answer within `SEARCHER_TIMEOUT` (default 600 s; connect timeout 10 s) (`"Allegro searcher unavailable"` — the exception text stays in the log), or when no search slot is free (`"Allegro searcher is busy — try again in a moment"`): the backend admits `SEARCHER_MAX_INFLIGHT` (default 10) distinct searches across **all five** routes, the searcher answers 503 itself when its own slots are taken, and Cloud Run answers **429** "Rate exceeded" once every `biker-searcher` instance is busy (`--max-instances 10`, `--concurrency 1`) — the 429 is mapped to the same 503 busy; nothing queues. A second request for the same `company`/`model` while one is running joins that search instead of starting another.
- **400** `{"detail": "<the CLI's notice>"}` when the searcher's `claude -p` run was refused because the Claude subscription limit is used up (TODO-038) — the searcher answers 400 with the CLI's own text (e.g. *"You've hit your session limit · resets 1am (Europe/Warsaw)"*), `searcher_client` raises `SearcherLimitReached`, and the app-wide handler `searcher_limit_reached` in `app/main.py` relays it — the same shape as the Anthropic credit-balance 400. Not a 502 / 503.
- **502** when the searcher answers with a non-200/400/503/429 — its `detail` (≤ 300 chars) is passed through (e.g. `401` for a wrong `SEARCHER_API_KEY`, `502` when the `claude` CLI fails) — or with a malformed body.
- `company` / `model` must be non-empty and at most 255 characters (422) — they reach the searcher's CLI prompt and its `bike` row.
- A run takes a minute or two: the 2026-09-26 probes with the CLI-tuned prompt found 3 real offers in 67 s (Kross Level 3.0) and 75 s (Trek Marlin 4). The ~10 s Playwright photo pass those probes still ran returned 0 photos every time (DataDome 403 on the offer pages), which is why it was removed — the route launches no browser now. The SDK-era prompt had needed 286 s (Trek Marlin 5) or given up empty, which is why it was rewritten.

**Flow:**
1. `POST {SEARCHER_URL}/v1/search/allegro` × 1 — the searcher service (header `X-Searcher-Key: $SEARCHER_API_KEY`, body `{company, model}`), waited for up to `SEARCHER_TIMEOUT`; it runs the `claude` CLI once (`WebSearch`/`WebFetch`, no Playwright) and writes the rows. The backend itself makes no Anthropic call.

**Tests:** `scripts/test_search.py` `case_allegro_search` — an unknown bike is a **404** before any searcher call. Deliberately no live Allegro run (every searcher run is a paid subscription search); the one live run kept in the suite is `case_decathlon_search`, which goes through the same proxy code path.

---

### `POST /v1/bike/used/olx`

Return the used-bike listings from OLX.pl **stored in the database** for a specific bike model — a pure read of `bike_offer` + `bike_offer_photos` (TODO-031). **No** AI call, **no** generic cache, no TTL: the rows are written only by the on-demand searcher service (see [`POST /v1/bike/used/search`](#post-v1bikeusedsearch)); nothing stored → 200 with an empty list.

```http
POST http://localhost:8000/v1/bike/used/olx
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

**Tests:** `scripts/test_search.py` `case_used` — a seeded fixture bike with 1 `olx.pl` offer and 1 photo → exactly that offer (`url`, `price`, `city`, `photos`), `is_new` false, `source = "olx.pl"`, `info` empty.

---

### `POST /v1/bike/used/search`

Run the OLX search **on demand** through the separate searcher service (`searcher/`, TODO-031) and wait for it. The searcher runs the Claude Code CLI (subscription OAuth token — no Anthropic API key) with `bike_offer_olx.md`, scrapes up to 4 photos per listing with Playwright, and **replaces** the bike's `olx.pl` rows in `bike_offer` + `bike_offer_photos` — so the next `POST /v1/bike/used/olx` returns them. Triggered by the frontend's **Poproś o dane** button in the "Używane" card (alongside `POST /v1/bike/missing`); also usable from `curl`. Never cached.

```http
POST http://localhost:8000/v1/bike/used/search
Content-Type: application/json

{
  "company": "Trek",
  "model": "Marlin 5"
}
```

**Response:** the searcher's `{ offers, info }` — the same shape as `POST /v1/bike/used/olx` (the searcher's extra `bike_id` / `saved` fields are dropped). A search that finds nothing is a **200** with `offers: []`.

- **404** `"Bike not found"` when the bike is not in the `bike` table (Python-normalised brand/model compare, like `/v1/bike/missing`). The searcher itself creates missing bikes for direct `curl` calls, but the backend never lets anonymous web traffic mint `bike` rows — they would surface in the DB-first search — nor spend a subscription run on them.
- **503** when `SEARCHER_URL` or `SEARCHER_API_KEY` is unset (`"OLX searcher is not configured"`), when the searcher cannot be reached / does not answer within `SEARCHER_TIMEOUT` (default 600 s; connect timeout 10 s) (`"OLX searcher unavailable"` — the exception text stays in the log), or when a search is already running (`"OLX searcher is busy — try again in a moment"`): the backend admits `SEARCHER_MAX_INFLIGHT` (default 10, never more than the searcher's `SEARCHER_MAX_CONCURRENT`) distinct searches across all five routes and the searcher answers 503 itself when its slots are taken (Cloud Run's 429 at `--max-instances` counts as busy too) — nothing queues, because a queued search would outlive the timeout and end in a second paid run. A second request for the same `company`/`model` while one is running joins that search instead of starting another.
- **400** `{"detail": "<the CLI's notice>"}` when the searcher's `claude -p` run was refused because the Claude subscription limit is used up (TODO-038) — the searcher answers 400 with the CLI's own text (e.g. *"You've hit your session limit · resets 1am (Europe/Warsaw)"*), `searcher_client` raises `SearcherLimitReached`, and the app-wide handler `searcher_limit_reached` in `app/main.py` relays it — the same shape as the Anthropic credit-balance 400. Not a 502 / 503.
- **502** when the searcher answers with a non-200/400/503/429 — its `detail` (≤ 300 chars) is passed through (e.g. `401` for a wrong `SEARCHER_API_KEY`, `502` when the `claude` CLI fails) — or with a malformed body.
- `company` / `model` must be non-empty and at most 255 characters (422).

**Flow:**
1. `POST {SEARCHER_URL}/v1/search/olx` × 1 — the searcher service (header `X-Searcher-Key: $SEARCHER_API_KEY`, body `{company, model}`), which runs the `claude` CLI once (`WebSearch`/`WebFetch`, `claude-haiku-4-5-20251001`) and Playwright once per listing, then writes the rows. The backend itself makes no Anthropic call.

**Tests:** `scripts/test_search.py` `case_used_search` — an unknown bike is a **404** before any searcher call. Deliberately no live OLX run (every searcher run is a paid subscription search); the one live run kept in the suite is `case_decathlon_search`, which goes through the same proxy code path.

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

Return the decathlon.pl offers **stored in the database** for a specific bike model — a pure read of `bike_offer` (TODO-032, the same move `/v1/bike/used/olx` made in TODO-031). **No** AI call, **no** generic cache, no TTL: the rows are written only by the on-demand searcher service (see [`POST /v1/bike/decathlon/search`](#post-v1bikedecathlonsearch)); nothing stored → 200 with an empty list.

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
      "price": "1249 zł",
      "is_new": true,
      "url": "https://www.decathlon.pl/p/rower-gorski-mtb-27-5-cala-rockrider-st-100/_/R-p-192872",
      "photos": [],
      "source": "decathlon.pl",
      "city": null
    }
  ],
  "info": ""
}
```

- The bike is looked up in `bike` by `company` + `model` normalised in Python (`strip().lower()`, never SQL `lower()`) and is never created; `brand`/`model` on every offer are the bike row's stored casing.
- Offers are the bike's `bike_offer` rows with `source = 'decathlon.pl'` in `id` order (insertion order), `is_new` from the row (the searcher stores what the model reported, default `true`), `photos` always `[]` (no Playwright scrape for Decathlon) and `city` `null`. `info` is always `""`.
- Unknown bike, no rows, or a DB error → `{ "offers": [], "info": "" }` (logged, never a 5xx) so the details view keeps rendering.
- `company` / `model` must be non-empty and at most 255 characters (422).

**Flow:** none — pure DB read of `bike_offer` / `bike_offer_photos`, no outbound call.

**Tests:** `scripts/test_search.py` `case_decathlon` — a seeded fixture bike with 1 `decathlon.pl` offer (`is_new` true, `city` null) → exactly that offer with `photos: []` in < 5 s and no generic-cache row; then an unknown bike → 200 `{ "offers": [], "info": "" }`.

---

### `POST /v1/bike/decathlon/search`

Run the Decathlon search **on demand** through the separate searcher service (`searcher/`, TODO-032) and wait for it. The searcher runs the Claude Code CLI (subscription OAuth token — no Anthropic API key) with `bike_offer_decathlon.md` (moved there byte-identical from the backend) and **replaces** the bike's `decathlon.pl` rows in `bike_offer` (≤ 3 offers, no photos) — so the next `POST /v1/bike/decathlon` returns them. Triggered by the frontend's **Poproś o dane** button in the "Nowe" card (alongside `POST /v1/bike/missing`); also usable from `curl`. Never cached.

```http
POST http://localhost:8000/v1/bike/decathlon/search
Content-Type: application/json

{
  "company": "Rockrider",
  "model": "ST 100"
}
```

**Response:** the searcher's `{ offers, info }` — the same shape as `POST /v1/bike/decathlon` (the searcher's extra `bike_id` / `saved` fields are dropped). A search that finds nothing is a **200** with `offers: []`.

- **404** `"Bike not found"` when the bike is not in the `bike` table (Python-normalised brand/model compare, like `/v1/bike/used/search`) — checked **before** any searcher call, so anonymous traffic can neither mint `bike` rows nor spend a subscription run.
- **200** `{ "offers": [], "info": "Decathlon nie sprzedaje marki Trek — w sklepie są tylko marki własne (Rockrider, Btwin, Triban, Van Rysel, Elops, Riverside, Stilus, Tilt)." }` **immediately, with no searcher call**, when `company` is not a Decathlon house brand (`app/decathlon_brands.py`: `rockrider`, `btwin`, `triban`, `vanrysel`, `elops`, `riverside`, `stilus`, `tilt`, `decathlon`, compared lower-cased with apostrophes, hyphens, dots and whitespace removed, so `B'Twin` / `b-twin` / `VAN RYSEL` all match). Decathlon sells only its own brands, so this is what closes `TODO_ISSUE_010` (Decathlon offers always empty for foreign brands).
- **503** when `SEARCHER_URL` or `SEARCHER_API_KEY` is unset (`"Decathlon searcher is not configured"`), when the searcher cannot be reached / does not answer within `SEARCHER_TIMEOUT` (default 600 s; connect timeout 10 s) (`"Decathlon searcher unavailable"` — the exception text stays in the log), or when a search is already running (`"Decathlon searcher is busy — try again in a moment"`): the `SEARCHER_MAX_INFLIGHT` slots (default 10) are **shared with the OLX, Allegro and photo searches** — they mirror the searcher's capacity, and the "Nowe" card fires this search together with `/v1/bike/allegro/search` — and the searcher answers 503 itself when its slots are taken (Cloud Run's 429 at `--max-instances` counts as busy too); nothing queues. A second request for the same `company`/`model` while one is running joins that search instead of starting another.
- **400** `{"detail": "<the CLI's notice>"}` when the searcher's `claude -p` run was refused because the Claude subscription limit is used up (TODO-038) — the searcher answers 400 with the CLI's own text (e.g. *"You've hit your session limit · resets 1am (Europe/Warsaw)"*), `searcher_client` raises `SearcherLimitReached`, and the app-wide handler `searcher_limit_reached` in `app/main.py` relays it — the same shape as the Anthropic credit-balance 400. Not a 502 / 503.
- **502** when the searcher answers with a non-200/400/503/429 — its `detail` (≤ 300 chars) is passed through (e.g. `401` for a wrong `SEARCHER_API_KEY`, `502` when the `claude` CLI fails) — or with a malformed body.
- `company` / `model` must be non-empty and at most 255 characters (422) — they reach the searcher's CLI prompt and its `bike` row.

**Flow:**
1. `POST {SEARCHER_URL}/v1/search/decathlon` × 1 — the searcher service (header `X-Searcher-Key: $SEARCHER_API_KEY`, body `{company, model}`), which runs the `claude` CLI once (`WebSearch`/`WebFetch`, no Playwright) and writes the rows. The backend itself makes no Anthropic call. — **or none** when the brand is not a Decathlon house brand (answered from the allowlist).

**Tests:** `scripts/test_search.py` `case_decathlon_search` — an unknown bike is a **404** whatever the searcher's state; a seeded fixture bike of a foreign brand is a 200 with `offers: []` and an `info` naming Decathlon in < 5 s with no searcher call and no generic-cache row; then, only when `GET {SEARCHER_URL}/health` answers (otherwise SKIP), it runs a live `Decathlon` / `Rockrider ST 100` search — the identity the DB-first search already carries, not a fresh `Rockrider` / `ST 100` row, because a decathlon.pl product URL is globally unique in `bike_offer` and a duplicate identity would capture it (the `bike` row is seeded if missing and kept; 200, every `url` on `https://www.decathlon.pl/`, `source = "decathlon.pl"`, `photos: []`, no generic-cache row) and, when at least one offer came back, checks that `POST /v1/bike/decathlon` then returns the same `(url, price)` set (DB round-trip; 0 offers prints a WARNING — the stored rows are kept, so only their shape is checked).

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
