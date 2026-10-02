# Database Migration: JSON Cache → SQLAlchemy ORM

## Overview

This migration moves from JSON serialization in SQLite to a proper relational database schema using SQLAlchemy ORM.

### Old Approach
- Generic `endpoint_req_to_body_cache` table with `(endpoint, request, response_json)`
- Searchable `search_cache` and the retired `bike_details_cache` with JSON blobs
- No relationships or foreign keys
- TTL managed in application code

### New Approach
- Normalized `bike` table — single source of truth for bike identity
- Related tables: `bike_component`, `bike_offer`, `photos` (the per-search tables `search_cache` +
  `search_bike_rating_cache` were dropped in TODO-043 — see below)
- Foreign key constraints (enforced — on SQLite `app/models.py` sets `PRAGMA foreign_keys=ON` on every engine
  connection; PostgreSQL always enforces them)
- Database chosen by `DATABASE_URL` (unset → SQLite `cache.db`, or PostgreSQL); copy an existing `cache.db` into
  PostgreSQL with `scripts/copy_sqlite_to_postgres.py` (TODO-028, see `backend/README.md`)
- TTL via module constants compared against `time_stored` / `updated_at`
- Proper relationships via SQLAlchemy ORM

## Database Schema

### Core Tables

**`bike`**
```
id (PK)
brand: str
model: str
created_at: datetime
updated_at: datetime
UNIQUE(brand, model)
```

> `search_cache` / `search_bike_rating_cache` (one row per query / one per returned bike) existed until TODO-043;
> `store.save_search` now only inserts the found bikes into `bike`.

**`bike_details`** — Full specifications
```
id (PK)
bike_id (FK → bike.id, UNIQUE)
description: text (JSON serialized BikeDescription)
short_description: text NOT NULL DEFAULT '' (TODO-041 — two-sentence Polish summary; scripts/migrate_short_description.py)
created_at: datetime
updated_at: datetime
```

**`bike_detail_photos`** — Photos of a bike (keyed on the bike, not on its details row — see
[Photos re-keyed to `bike_id`](#photos-re-keyed-to-bike_id))
```
id (PK)
bike_id (FK → bike.id, ON DELETE CASCADE, NOT NULL, indexed)
url: str
display_order: int
```

**`bike_details_component`** — One (category, subcategory) pair
```
id (PK)
bike_details_id (FK → bike_details.id)
category: str        e.g. "Frame"    — repeats across the rows sharing it
subcategory: str     e.g. "Fork"
display_order: int   running counter across the whole tree
```

**`bike_details_component_element`** — A named part
```
id (PK)
component_id (FK → bike_details_component.id)
name: str            e.g. "Shimano GRX RD-RX822 12s"
description: text    often "" — never NULL
display_order: int
```

**`bike_details_component_spec`** — One key/value spec row
```
id (PK)
element_id (FK → bike_details_component_element.id)
key: str             e.g. "Weight"
value: str           e.g. "580 g"
display_order: int
```
NOT unique on (element_id, key) — the source data repeats keys within an
element, and many elements carry no specs at all.

**`bike_offer`** — Marketplace listings
```
id (PK)
bike_id (FK → bike.id)
price: str
is_new: bool
url: str (UNIQUE)
source: str (allegro.pl, olx.pl, ceneo.pl, decathlon.pl)
city: str (nullable, for used bikes)
created_at: datetime
created_at_list: datetime (when listed on marketplace)
UNIQUE(bike_id, url)
```

**`bike_offer_photos`** — Photos for offers
```
id (PK)
bike_offer_id (FK → bike_offer.id)
url: str
display_order: int
```

**`bike_missing_request`** — "Request data" clicks per bike + missing section (TODO-026)
```
id (PK)
bike_id (FK → bike.id)
missing_type: str (≤ 64 chars, free string from the frontend)
counter: int (1 on first request, +1 on each later one)
UNIQUE(bike_id, missing_type)
```
New table only — `init_db()`'s `create_all()` creates it on an existing database at startup, so it needs no
migration step.

**`bike_review`** — the stored expert review of a bike (TODO-037)
```
id (PK)
bike_id (FK → bike.id, ON DELETE CASCADE, UNIQUE, indexed)
score: int (0–10)
explanation: text
rating: float (0–10 weighted aggregate)
sources_used: int
created_at, updated_at: datetime (naive UTC, like every other table)
```

**`bike_review_source`** — the review's `ref` URLs (TODO-037)
```
id (PK)
review_id (FK → bike_review.id, ON DELETE CASCADE, indexed)
url: str (≤ 2048)
display_order: int (the tier-sorted `ref` order; read ORDER BY display_order, id)
```
Written only by the searcher (`POST /v1/search/review`), read by `app/reviews_repository.py` `get_review` for
`POST /v1/bike/review` — no TTL, no generic cache. New tables: `init_db()` creates them, no schema migration.

## Reviews copied out of the generic cache (TODO-037)

Before TODO-037 each review was a JSON blob in `endpoint_req_to_body_cache` (endpoint `'/v1/bike/review'`). Carry
them over once per database — the old cache rows stay behind as dead rows:

```bash
cd backend
python scripts/copy_review_cache_to_table.py --dry-run   # $DATABASE_URL (backend/.env), else backend/cache.db
python scripts/copy_review_cache_to_table.py
python scripts/copy_review_cache_to_table.py --db path/to/copy.db
python scripts/copy_review_cache_to_table.py --url postgresql+psycopg://biker:biker@localhost:5432/<db>
python scripts/copy_review_cache_to_table.py --force     # overwrite reviews already in bike_review
```

- Copies only rows with a non-empty `ref` and `sources_used >= 1` (the rest → `skipped_degenerate`); unreadable JSON →
  `unparseable`. The bike is found by Python-normalised brand/model and never created (miss → `skipped_unknown_bike`,
  listed); a bike that already has a review → `skipped_existing` unless `--force`.
- `ref` order → `display_order` 0..n-1; `created_at`/`updated_at` = the cache row's `time_stored`.
- One transaction through the app's engine (SQLite and PostgreSQL); `--dry-run` rolls back and creates no tables; a
  second run copies nothing. Importable: `copy_reviews(url_or_path=None, dry_run=False, force=False, verbose=True) ->
  dict`. Exit code 1 on failure.
- Local run on a copy of `cache.db` (2026-09-29): 26 cached rows → 17 copied (57 sources), 9 degenerate, 0 unknown
  bikes, 0 unparseable; second run 0 copied / 17 skipped_existing.

## Migration Steps

### 1. Install SQLAlchemy
```bash
pip install -r requirements.txt
```

### 2. Initialize Database (Backup First!)
```python
# In main.py or startup event:
from app.models import init_db
init_db()  # Creates all tables if they don't exist
```

### 3. Update Application Code

> Historical: `get_search_by_query` / `find_bikes_by_brand` were removed later; only `save_search` remains.

**Old:**
```python
from app import store
store.save_search(query, bikes)
result = store.get_search_by_query(query)
```

**New:**
```python
from app import repository
repository.save_search(query, bikes)
result = repository.get_search_by_query(query)
```

### 4. Migrate Existing Data (Optional)

If you have existing cache.db with JSON data:
```python
from app.store import get_search_by_query as old_get
from app.repository import save_search

# Read old data
old_data = old_get(query)
# Write to new schema
save_search(query, old_data)
```

## API surface (current)

- Search storage — `app.store`: only `save_search` remains, and since TODO-043 it only makes sure every
  AI-found bike exists in `bike` (the readers `get_search_by_query` / `find_bikes_by_brand`, the
  `GET /v1/bike/search-cache` endpoint and then the two per-search tables themselves were removed).
- Details — `app.repository`: `save_bike_details`, `get_bike_details`
  (backed by `bike.description` / `bike.short_description` + `bike_component`; no TTL — stored details are returned whatever their age). Since TODO-041 `POST /v1/bike/details` is a pure read of them (normalised brand/model lookup, `short_description` included) and the live writer is the searcher (`POST /v1/bike/details/search`, `searcher/app/repository.py` `save_details`); helpers `empty_details`, `has_complete_details`, `accessory_chips`, `fill_bike_results`.
- Bike photos — `app.photos_repository`: `get_bike_photos` (`POST /v1/bike/photos`) and `save_bike_photos`
  (offline pipeline only); the searcher's photo search is the live writer (backed by `bike_detail_photos`).
- DB-first search (TODO-024) — `app.repository.find_bikes_by_details`: matches
  `/v1/bike/search` checkable fields against `bike` + `bike_component`.
- Missing-data requests (TODO-026) — `app.repository.record_missing_request`:
  looks up an existing `bike` and upserts `bike_missing_request` (`POST /v1/bike/missing`).

(The `bike_results` + `accessories` tables and `repository`'s own copies of the
search helpers were removed once the store versions became authoritative.)

## Photos re-keyed to `bike_id`

`bike_detail_photos` used to hang off the details row (`bike_detail_id` → `bike_detail.id`), so re-saving details
deleted and re-inserted a bike's photos, and photos could not exist without details. With the photos searcher, photos
belong to the bike: column `bike_detail_id` is **replaced** by `bike_id INTEGER NOT NULL REFERENCES bike(id) ON DELETE
CASCADE` (index `ix_bike_detail_photos_bike_id`); the table keeps its name. Columns: `id, bike_id, url, display_order`,
read in `display_order, id` order.

- `repository.save_bike_details` no longer writes photos and never deletes them: it updates the `bike_detail` row in
  place (its id stays stable) and replaces only its component rows, so even on a not-yet-migrated database — where the
  old `bike_detail_id … ON DELETE CASCADE` FK still exists — a re-save cannot cascade-delete photos; `get_bike_details` returns no photos (`BikeDetailsResponse` has no `photos` field). `TTL_DETAILS` is gone.
- Writers never replace photos: the searcher (and `photos_repository.save_bike_photos`) insert only for a bike that
  has none; a search that finds nothing writes nothing.

**The migration is required on every pre-existing database, and it must run BEFORE the new backend and searcher are
deployed on it** — `init_db()`'s `create_all()` never `ALTER`s a table. Until it runs,
`photos_repository.get_bike_photos` logs an ERROR naming the script and returns `{photos: []}`, and the searcher
refuses to start. Order: back up → `--dry-run` → migrate → deploy backend + searcher.

```bash
cd backend
python scripts/migrate_photos_bike_id.py --dry-run          # $DATABASE_URL (backend/.env), else backend/cache.db
python scripts/migrate_photos_bike_id.py
python scripts/migrate_photos_bike_id.py --db path/to/copy.db
python scripts/migrate_photos_bike_id.py --url postgresql+psycopg://biker:biker@localhost:5432/<db>
```

- **SQLite** cannot drop a FK column in place, so the table is rebuilt (`CREATE bike_detail_photos_new` → `INSERT …
  SELECT` through `bike_detail` → `DROP` → `RENAME` → `CREATE INDEX`). **PostgreSQL** is altered in place (`ADD
  COLUMN bike_id` → `UPDATE … FROM bike_detail` → `SET NOT NULL` + FK `bike_detail_photos_bike_id_fkey` + index →
  `DROP COLUMN bike_detail_id`) under `LOCK TABLE bike_detail_photos, bike_detail IN SHARE ROW EXCLUSIVE MODE`, taken
  right after `BEGIN` so concurrent writes cannot skew the verification; ids and the id sequence are kept on both.
- One transaction on both dialects; before committing it verifies row by row that every photo kept its id, url and
  `display_order` and points at the bike its old details row belonged to — any mismatch or error rolls back.
- Rows whose details row (or that row's bike) is missing cannot be re-keyed: they are listed and copied, in the same
  transaction, into **`bike_detail_photos_orphans`** (`id` PK, `bike_detail_id`, `bike_id`, `url`, `display_order`;
  created only when there are orphans, `ON CONFLICT (id) DO NOTHING`), then left out of the migrated table. Nothing
  reads that table — it is the record to inspect or restore from. Prints before/after row, bike and orphan counts.
- Idempotent: a table already keyed on `bike_id` is checked for `NOT NULL`, the `ON DELETE CASCADE` FK to `bike` and
  the `bike_id` index — all present → `already-migrated`, nothing written; any missing → `repaired` through the same
  rebuild / `ALTER` path (rows pointing at no bike go to the orphans table). An absent table is reported as `absent`
  and left to `init_db()`, which creates it with the new schema. Importable:
  `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict` (`status`, `rows_before`, `rows_after`, `orphans`,
  `bikes_with_photos`, `gaps`, `verified`, `error`). Exit code 1 on failure.
- On PostgreSQL the migrated table lists `bike_id` last (added column) — harmless, the ORM addresses columns by name.

## Search match score dropped (`search_bike_rating_cache.rating`)

TODO-040 removed `match_score` from `POST /v1/bike/search` and `BikeResult`; the search cards show the expert rating from
`bike_review` instead. Its column `search_bike_rating_cache.rating` was dropped by `scripts/migrate_drop_search_rating.py`
(run 2026-09-30 on `cache.db`, the local PostgreSQL and Cloud SQL). The script is gone since TODO-043 dropped the whole table.

## Search tables dropped (`search_cache`, `search_bike_rating_cache`)

TODO-043 drops both per-search tables. They were write-only since the cache-read endpoints went (TODO-024/025) and held
nothing but the search → bike link plus `""` / `"[]"` payloads since TODO-041. `store.save_search` now only makes sure the
found bikes exist in `bike` (`repository._find_bike_id` lookup, new rows keep the caller's casing); `SEARCH_TTL_SECONDS` is gone.

```bash
cd backend
python scripts/migrate_drop_search_tables.py --dry-run          # $DATABASE_URL (backend/.env), else backend/cache.db
python scripts/migrate_drop_search_tables.py
python scripts/migrate_drop_search_tables.py --db path/to/copy.db
python scripts/migrate_drop_search_tables.py --url postgresql+psycopg://biker@127.0.0.1:6543/<db>
```

- `DROP TABLE search_bike_rating_cache` (child: FKs to `search_cache` and `bike`) then `DROP TABLE search_cache`, one
  transaction on both dialects; the `bike` row count is compared before and after, a difference rolls back (exit code 1).
- Idempotent: neither table → `already-migrated`; a half-dropped database (one table left) is still migrated. Importable:
  `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict` (`status`, `dropped`, `bikes_before`, `bikes_after`, `verified`, `error`).
- Deploy order: the new backend never touches the tables, so **deploy the backend first, then drop** — no failing window. Dropping
  first only makes the old backend's `save_search` log a WARNING per AI search (the answer is still returned, nothing stored is lost).
- Run 2026-10-01: local PostgreSQL `biker-pg` (`search_bike_rating_cache` 199 + `search_cache` 46 rows, `bike` 723 kept) and
  `cache.db` (206 + 47, `bike` 674 kept) and Cloud SQL (210 + 48, `bike` 728 kept, on-demand backup first); second run `already-migrated`.

## Short description added (`bike_detail.short_description`)

TODO-041 adds `bike_detail.short_description` (`TEXT NOT NULL DEFAULT ''`, model default `""` + `server_default=""`): the
two-sentence Polish summary the searcher writes; `POST /v1/bike/search` shows it as a result card's `explanation`.
`create_all()` never `ALTER`s a table, so every pre-existing database needs `scripts/migrate_short_description.py` once.

**Run it BEFORE the new backend or searcher runs on that database** — the new ORM reads and writes the column, and the
searcher refuses to start without it. The OLD backend keeps working on a migrated database (the column has a server
default). Production order: Cloud SQL on-demand backup → migrate Cloud SQL → deploy backend + searcher together → deploy the frontend.

```bash
cd backend
python scripts/migrate_short_description.py --dry-run          # $DATABASE_URL (backend/.env), else backend/cache.db
python scripts/migrate_short_description.py
python scripts/migrate_short_description.py --db path/to/copy.db
python scripts/migrate_short_description.py --url postgresql+psycopg://biker:biker@localhost:5432/<db>
```

- `ALTER TABLE bike_detail ADD COLUMN short_description TEXT NOT NULL DEFAULT ''` on both dialects, only when the column
  is missing; existing rows get `''` (no backfill). Row counts compared before and after; a mismatch rolls back (exit code 1).
- Idempotent: column present → `already-migrated`; no table → `absent` (left to `init_db()`). Importable:
  `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`.
- A search result's text and chips are read from `bike_detail` at request time (the per-search tables went in TODO-043).
- `scripts/purge_details_cache.py` (`--dry-run`, `--db`, `--url`) deletes the dead `endpoint_req_to_body_cache` rows of
  `'/v1/bike/details'` — local only; Cloud SQL on an explicit go.

## bike_detail dropped (details moved onto `bike`)

`bike_detail` held one row per bike (`description` JSON, `short_description`, timestamps). It is gone:

- `bike.description` — `TEXT`, **nullable**, the JSON-serialised `BikeDescription`; **NULL = the bike has no details**. "Has details" means `bike.description IS NOT NULL` everywhere (backend, searcher, discovery processor, seed script).
- `bike.short_description` — `TEXT NOT NULL DEFAULT ''` (`server_default` too).
- `bike_detail_component.bike_detail_id` → **`bike_id`** (FK → `bike.id` `ON DELETE CASCADE`, `NOT NULL`, indexed `ix_bike_detail_component_bike_id`), same pattern as the photos re-key. The table kept its name here; the rename to `bike_component` is the next section.
- No details timestamps carry over. `repository.save_bike_details` therefore returns a **bool** (True = committed, False = failed and rolled back) instead of the old "`bike_detail.updated_at` ≥ save start" check the discovery processor used.
- Re-saving updates the bike row's columns in place and replaces its component rows (the searcher's `save_details` replaces only the half the run produced; a components-only run on a bike without details also writes the empty description JSON so the bike counts as having details).

`scripts/migrate_drop_bike_detail.py` (`--dry-run`, `--db <sqlite file>`, `--url <sqlalchemy url>`, importable `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`) does it in ONE transaction: add the `bike` columns → copy descriptions (`''` short description when `bike_detail` lacks the column) → re-key the components (SQLite: table rebuild; PostgreSQL: `ADD COLUMN` → `UPDATE … FROM bike_detail` → `NOT NULL` + FK + index → `DROP COLUMN bike_detail_id`, under `LOCK TABLE bike, bike_detail, bike_detail_component IN SHARE ROW EXCLUSIVE MODE`) → `DROP TABLE bike_detail`. Component rows without a detail row or bike go whole into `bike_detail_component_orphans`. Verified before commit; any mismatch rolls back (exit code 1). Idempotent (`already-migrated`; a missing piece is repaired). It refuses to run while `bike_detail_photos` still has `bike_detail_id` — run `migrate_photos_bike_id.py` first (`migrate_short_description.py` is optional).

**Deploy order:** (1) Cloud SQL on-demand backup, (2) run the script on Cloud SQL through the proxy — **only on the user's explicit go** — (3) deploy the backend and the searcher together, (4) the frontend is unchanged (API shapes did not change). The OLD backend breaks on a migrated database (its ORM still queries `bike_detail`), and the NEW searcher refuses to start on an unmigrated one (its `init_db()` names this script; the former `short_description` startup check is replaced by it). The new backend on an unmigrated database fails every details read/write too.

Local `biker-pg` (2026-10-01): 619 details, 32972 component rows, 0 orphans, verified; rerun `already-migrated`.

## Equipment tables (TODO-042)

_(Written before the component table was renamed — the script addresses `bike_detail_component`, which is what it finds when run in order; next section.)_

TODO-042 gives equipment (helmets, lights, locks, apparel) a DB identity, so `POST /v1/equipment/details` and
`POST /v1/equipment/photos` become pure DB reads and the searcher writes what it finds. Models in
`app/equipment_models.py` (imported at the bottom of `app/models.py`, so `create_all()` builds them):

| Table | Columns |
|---|---|
| `equipment` | `id`, `category` (slug ≤ 32), `company` (≤ 255, may be `""`), `model` (≤ 512 — the bike tree's element name), `company_norm`, `model_norm` (Python `strip().lower()` via `@validates`), `created_at`; `UNIQUE(category, company_norm, model_norm)` = `uq_equipment_identity` |
| `equipment_detail` | `id`, `equipment_id` (FK → `equipment.id` `ON DELETE CASCADE`, UNIQUE), `description` (JSON `BikeDescription`), `short_description` (`TEXT NOT NULL DEFAULT ''`), `created_at`, `updated_at` |
| `equipment_detail_component` | the flat shape of `bike_detail_component` (no `equipment_id`), `equipment_detail_id` FK → `equipment_detail.id` `ON DELETE CASCADE` |
| `equipment_detail_photos` | `id`, `equipment_id` (FK → `equipment.id` `ON DELETE CASCADE`, `NOT NULL`, indexed), `url` (≤ 2048), `display_order` |
| `bike_detail_component` | **+** `equipment_id` (nullable, FK → `equipment.id` `ON DELETE SET NULL`, index `ix_bike_detail_component_equipment_id`) |

`bike_detail_component.equipment_id` links one bike's element to the equipment row it was searched as — only that bike's
rows with that element name, never globally. `repository.save_bike_details` deletes and re-inserts a bike's component rows,
so it snapshots `element_name → equipment_id` (Python-normalised) first and puts the link back on the new rows with the same
name; an `equipment_id` arriving in the saved data is ignored (it may be another database's id, e.g. `copy_to_db.py`).
`get_bike_details` returns each element's `equipment_id` (from its first row).

**Run `scripts/migrate_equipment_tables.py` on every pre-existing database BEFORE the new backend or searcher runs on it —
and AFTER `scripts/migrate_drop_bike_detail.py` (§ bike_detail dropped).** The script refuses (`failed`, exit code 1, nothing
written) a `bike_detail_component` still keyed on `bike_detail_id`: that migration rebuilds the table on SQLite from a fixed
column list, so an `equipment_id` added before it would be dropped together with its links (PostgreSQL alters in place and keeps
the column). Should it happen anyway, running `migrate_equipment_tables.py` again re-adds the column and its index; the links
come back with the next equipment search.
`init_db()` creates the four missing tables on startup but never adds the column, so on an unmigrated database every ORM read
or write of `bike_detail_component` fails (`no such column` / `UndefinedColumn`): `POST /v1/bike/details` answers 500 (the read
raises), the DB-first search logs a WARNING and falls back to AI, `save_bike_details` rolls back with a WARNING. The searcher refuses to start without the column. The OLD backend
keeps working on a migrated database (nullable column, new tables ignored), so the window between migrating and deploying is
safe. Production order: Cloud SQL on-demand backup → migrate Cloud SQL through the proxy → deploy backend + searcher together →
deploy the frontend — only on the user's explicit go.

```bash
cd backend
python scripts/migrate_equipment_tables.py --dry-run          # $DATABASE_URL (backend/.env), else backend/cache.db
python scripts/migrate_equipment_tables.py
python scripts/migrate_equipment_tables.py --db path/to/copy.db
python scripts/migrate_equipment_tables.py --url postgresql+psycopg://biker:biker@localhost:5432/<db>
```

- One transaction: `create_all(checkfirst=True)` on just the four equipment tables, then — only when missing — SQLite
  `ALTER TABLE bike_detail_component ADD COLUMN equipment_id INTEGER REFERENCES equipment (id) ON DELETE SET NULL`;
  PostgreSQL `ADD COLUMN` → `ADD CONSTRAINT bike_detail_component_equipment_id_fkey … ON DELETE SET NULL` under
  `LOCK TABLE bike_detail_component IN SHARE ROW EXCLUSIVE MODE`; then `CREATE INDEX IF NOT EXISTS ix_bike_detail_component_equipment_id`.
  The `bike_detail_component` row count is compared before and after and every new `equipment_id` must be NULL; a mismatch rolls back (exit code 1).
- Idempotent: everything present → `already-migrated`; a missing index (or, on PostgreSQL, FK) is repaired on its own; no
  `bike_detail_component` table → `absent` (left to `init_db()`). Importable `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`
  (`status`, `rows_before`, `rows_after`, `tables_created`, `column_added`, `verified`, `error`).
- Verified 2026-10-01: on a scratch copy of `cache.db` (31 826 component rows, 2 bikes with equipment) — dry run wrote nothing, the real run created the four tables and the column with its FK and index, kept every row, second run `already-migrated`; on the local PostgreSQL `biker-pg` (32 972 rows) — dry run clean, the real run created everything and kept every row, second run `already-migrated`. Cloud SQL migration pending user's explicit go.
- After the merge with main (PR #137 bike_detail dropped, PR #136 TODO-043), 2026-10-01: a fresh scratch copy of `cache.db`
  still on the `bike_detail` layout — `migrate_equipment_tables.py` refused (dry run and real), then
  `migrate_drop_bike_detail.py` migrated (566 details, 31 826 component rows, 0 orphans), `migrate_drop_search_tables.py`
  dropped the two search tables, then `migrate_equipment_tables.py` dry run → real run `migrated` (four tables, column + FK +
  index, 31 826 rows kept) → `already-migrated`. Local `biker-pg` (already on both layouts): dry run `already-migrated`
  (32 972 rows). Production order: `migrate_drop_bike_detail.py` → `migrate_equipment_tables.py` → deploy backend + searcher
  → frontend.

_(The `equipment_detail` / `equipment_detail_component` tables above were merged away by TODO-044 — see the section after the rename.)_

## `bike_detail_component` renamed to `bike_component`

Keyed on `bike.id` since the bike_detail drop above, the component spec tree no longer belonged to a "detail" row, so the table is now **`bike_component`** (ORM class `BikeComponent` in `backend/app/models.py` and the searcher's copy). Columns (`equipment_id` included), constraints and data are unchanged; only names moved: table, indexes (`ix_bike_component_*`), and on PostgreSQL the `bike_component_pkey` / `bike_component_bike_id_fkey` / `bike_component_equipment_id_fkey` constraints and the `bike_component_id_seq` sequence. The leftover `bike_detail_component_orphans` table (if the drop migration created one) becomes `bike_component_orphans`. The API shapes are untouched; the frontend never saw the table name. `migrate_drop_bike_detail.py` and `migrate_equipment_tables.py` still address the old name — run them first; on a renamed database each answers `already-migrated` / `absent` and writes nothing.

`scripts/migrate_rename_bike_component.py` (`--dry-run`, `--db <sqlite file>`, `--url <sqlalchemy url>`, importable `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict` with `status`, `rows_before/after`, `renamed`, `verified`, `error`) does it in ONE transaction: `ALTER TABLE … RENAME` → rename the indexes (SQLite drops and recreates them, PostgreSQL `ALTER INDEX … RENAME`), the PostgreSQL constraints and sequence, and the orphans table → verify every row (every column) reads back identical from `bike_component` and nothing is left under the old name, else roll back (exit code 1). Idempotent: `already-migrated`; leftover old names are `repaired`. An empty `bike_detail_component` next to a populated `bike_component` (an OLD backend's `create_all()` recreated it) is dropped; an empty `bike_component` next to a populated old table (the NEW backend started too early) is dropped and the rename goes ahead; both populated → refused. Tests: `scripts/test_migrate_rename_bike_component.py`.

**Deploy order:** (1) Cloud SQL on-demand backup, (2) run the script on Cloud SQL through the proxy — **only on the user's explicit go** — (3) deploy the backend and the searcher together, (4) the frontend is unchanged. The OLD backend breaks on a migrated database (its ORM still queries `bike_detail_component`, and its `create_all()` recreates it empty — rerun the script afterwards, it drops the empty duplicate), and the NEW searcher refuses to start on an unmigrated one (its `init_db()` names this script).

## `equipment_detail` merged into `equipment` (TODO-044, `scripts/migrate_merge_equipment_detail.py`)

The equipment details row duplicated what `bike` carries since PR #137, so `equipment_detail` is gone and its component table is
`equipment_component`. Layout (`app/equipment_models.py`, verbatim copy in `searcher/app/models.py`):

| Table | Columns |
|---|---|
| `equipment` | `id`, `category` (slug ≤ 32), `name` / `name_norm` (≤ 512, NOT NULL - the element name from a bike's spec tree, the lookup identity), `company` (≤ 255) / `model` (≤ 512) / `company_norm` / `model_norm` (the **researched** brand and model: `""` and the name until a details search fills them), `description` (`Text`, **nullable** - JSON `BikeDescription`, NULL = no details), `short_description` (`TEXT NOT NULL DEFAULT ''`), `created_at`, `updated_at`; `UNIQUE(category, name_norm)` = `uq_equipment_name` (replaces `uq_equipment_identity`) |
| `equipment_component` | the flat shape of `bike_component` (no `equipment_id` link, no `is_linkable`), `equipment_id` FK → `equipment.id` `ON DELETE CASCADE`, NOT NULL, indexed |
| `equipment_detail_photos` | unchanged |

The norm columns follow `name` / `company` / `model` through `@validates` (Python `strip().lower()`); a Core insert / update sets them itself.
`equipment_component.equipment_id` is the OWNER of the row (not an element link like `bike_component.equipment_id`), so
`component_tree.rebuild_components(..., element_links=False)` is used for equipment.

**company / model rule.** A details search asks the model for the identified manufacturer (`company`) and the model name without the brand (`model`).
`save_equipment_details` finds the row by `(category, name)` - never by company / model - and fills only what is missing: `company` when the stored one is `""`,
`model` when the stored one is empty or still the name; stored values are never overwritten and a `""` never counts. The photo save never touches them. Existing
rows are not backfilled by AI. Reads without `equipment_id` match `name_norm` (company `""`: the spec-tree click) or the researched pair or `name_norm` of "company model".

```bash
cd backend
python scripts/migrate_merge_equipment_detail.py --dry-run     # report only; database: $DATABASE_URL (backend/.env), else cache.db
python scripts/migrate_merge_equipment_detail.py               # migrate
python scripts/migrate_merge_equipment_detail.py --db path/to/copy.db
python scripts/migrate_merge_equipment_detail.py --url postgresql+psycopg://biker:biker@localhost:5432/<db>
```

- One transaction on both dialects (SQLite rebuilds `equipment`; PostgreSQL alters it in place under `LOCK TABLE equipment, equipment_detail, equipment_detail_component IN SHARE ROW EXCLUSIVE MODE`): add the columns → copy each detail row's description / short_description / `updated_at` (else `created_at`) → backfill `name` (= model, or "company model" for a row with a company) and `name_norm` in Python → swap the unique constraint → create `equipment_component` from the ORM model and copy every component row keeping its id (PostgreSQL: sequence reset) → drop `equipment_detail_component` and `equipment_detail`.
- Component rows without a detail row (or whose equipment is missing) are copied whole into `equipment_component_orphans` and left out of the new table, never dropped silently. Verified before commit (every equipment row keeps its columns and gets its old detail row's description / short_description - NULL / `''` without one; every component row keeps id, equipment and content; photo and `bike_component` link counts unchanged); any mismatch, or two rows that would share `(category, name_norm)`, rolls back with exit code 1.
- Idempotent: `already-migrated`; a migrated database where an OLD backend's `create_all()` recreated the empty `equipment_detail` / `equipment_detail_component` (or `equipment_component` is missing) is `repaired` - the empty leftovers are dropped, non-empty ones are refused. An empty `equipment_component` the NEW backend created before the migration is dropped and rebuilt. A database without `equipment` is left to `init_db()` (`absent`). Refused while `bike_detail_component` is not yet renamed. `migrate_equipment_tables.py` creates no table next to the pre-merge layout.
- **Required on every existing database, AFTER `migrate_equipment_tables.py`, `migrate_drop_bike_detail.py` and `migrate_rename_bike_component.py`, and BEFORE the new backend or searcher runs against it** (production: Cloud SQL backup → migrate through the proxy, only on the user's explicit go → deploy backend + searcher together → the frontend is unchanged). The new searcher refuses to start on an unmerged database (it checks `equipment.name` and `equipment_component`); the OLD backend breaks on a migrated one. Unit tests (`scripts/test_migrate_merge_equipment_detail.py`) run on SQLite. The PostgreSQL branch was rehearsed 2026-10-02 on a copy of the local `biker-pg` (`migrated` → `already-migrated` → `repaired` after an old-code `create_all()`). Run 2026-10-02: local `biker-pg` 3 equipment / 3 details / 22 component rows, 0 orphans, `migrated`; `backend/cache.db` (empty equipment tables) `migrated`. Cloud SQL on-demand backup "before migrate_merge_equipment_detail" taken 2026-10-02.

- **Run on Cloud SQL 2026-10-02** (after the on-demand backup "before migrate_merge_equipment_detail"): 3 equipment / 3 details / 28 component rows, 0 orphans, `migrated`; rerun `already-migrated`. Deployed with tag 92394ac (also shipped PR #145 rename and #146 is_linkable): searcher `biker-searcher-00010-dkq`, backend `biker-backend-00017-8vb`, frontend `biker-frontend-00012-m56`. Before that run the old backend had recreated an empty `bike_detail_component` on Cloud SQL beside the populated `bike_component`, and the rename script's repair path failed on PostgreSQL (`relation "bike_detail_component_id_seq" does not exist`: the empty table's owned sequence went with its DROP) - fixed afterwards: the sequence is renamed only while the source table's id column still owns the old name and the new name is free.

## Component link flag (`bike_component.is_linkable`, ISSUE-016)

Every component element name used to render as a link to the equipment view, including "None included", "Owner's Manual" and "Alloy Platform Pedals" — each click spent four Anthropic calls on an empty page. The decision now lives in the data:

- `bike_component.is_linkable` — `BOOLEAN NOT NULL DEFAULT TRUE` (`server_default` too), repeated on every spec row of the element like the other element-level columns. `True` = the name identifies one specific, searchable product (brand + model / part number); `False` = a not-supplied placeholder, paperwork, or a generic part without a brand. `equipment_detail_component` has no such column (equipment trees never link).
- Who decides: the **searcher's model** at search time (`is_linkable` is a required boolean per element in `DETAILS_SCHEMA`, the rule is spelled out in `searcher/app/prompts/bike_details.md`; only a literal `true` counts, a missing flag is `False`). The two writers without a model — the discovery scraper (`webscraper/centrumrowerowe/product_parser.py`) and the backfill below — use the shared regex heuristic `backend/app/linkable.py` (`is_linkable(name, subcategory)`: not-supplied phrases, paperwork, a name equal to its subcategory, measurements are not model codes, a generic English/Polish vocabulary; `True` needs one specific token). The model's verdict is stored as is — the heuristic never overrides it.
- API: `ComponentElement.is_linkable: bool` (default `True` in the backend schema, so equipment finders and old fixtures keep the old behaviour); `component_tree.flatten_components(..., include_linkable=True)` emits it for bike rows only; the frontend's `ElementItem` links the name only when the flag is `true`.

`scripts/migrate_component_linkable.py` (`--dry-run`, `--reclassify`, `--db <sqlite file>`, `--url <sqlalchemy url>`, importable `migrate(url_or_path=None, dry_run=False, reclassify=False, verbose=True) -> dict` with `status`, `rows_before/after`, `linkable`, `not_linkable`, `verified`, `error`) does it in ONE transaction: `ALTER TABLE … ADD COLUMN is_linkable BOOLEAN NOT NULL DEFAULT TRUE` → classify every row with the heuristic → `UPDATE … SET is_linkable = FALSE` for the rows that came out `False` (PostgreSQL under `LOCK TABLE bike_component IN SHARE ROW EXCLUSIVE MODE`). Verified before commit (row count unchanged, every stored flag equals the computed one); any mismatch rolls back (exit code 1). `--dry-run` prints the true/false distribution and the most frequent names of each class — review it before the real run. Idempotent: a present column = `already-migrated` and the rows are **not** touched (flags written by the model are kept); `--reclassify` re-runs the heuristic over every row — for tuning the regexes only, it overwrites the model's decisions. Run it AFTER `migrate_rename_bike_component.py` (a database still on `bike_detail_component` is refused).

**Deploy order:** (1) Cloud SQL on-demand backup, (2) run the script on Cloud SQL through the proxy — **only on the user's explicit go** — (3) deploy the backend and the searcher together, (4) deploy the frontend. The NEW backend's ORM selects the column, so it fails every details read on an unmigrated database; the NEW searcher refuses to start on one (its `init_db()` names this script). The OLD backend keeps working on a migrated database (server default `TRUE`, i.e. the old behaviour). The frontend must go last: it links a name only when `is_linkable` is `true`, so against an old backend (no field) it would show no links at all.

Local `biker-pg` (2026-10-02): 32972 rows → 27468 linkable / 5504 not after `--reclassify` with the tuned vocabulary (first run 27829 / 5143; most frequent `false`: "Frame | Frame" 320, empty names, "Front Derailleur | None" 89, "Pedals | None included" 76, "Reflector Set", "Gearing", "Included Items | Rear Rack"), verified; rerun `already-migrated`. The column survived the table rename (it was added before `migrate_rename_bike_component.py` ran locally). Cloud SQL `biker-pg` migrated 2026-10-02 by the user through the proxy (after an on-demand backup): 33216 rows → 27676 linkable / 5540 not, verified, `RESULT: migrated`. **Not yet deployed** — Cloud Run still runs the pre-ISSUE-016 backend and searcher (safe: server default TRUE = the old behaviour), so production links are unchanged until `deploy.ps1` runs; a details search run on production in the meantime stores `TRUE` for every element (old prompt) — consider `--reclassify` for such a bike after the deploy.

## Benefits

✅ **Data Integrity** — Foreign keys, unique constraints, cascading deletes
✅ **Queryability** — Rich ORM queries instead of JSON parsing
✅ **Relationships** — One-to-many (Bike → BikeOffer, Bike → BikeComponent, Bike → BikeDetailPhoto)
✅ **Photo Management** — Proper ordering and sourcing
✅ **Indexed Lookups** — Brand, source, URL indices for fast queries
✅ **Future Extensions** — Easy to add new fields, relationships

## Example Queries

**Find all Trek bikes from cached searches:**
```python
from app.models import Bike, get_session

session = get_session()
trek_bikes = session.query(Bike).filter(Bike.brand.ilike("trek%")).all()
```

**Get all offers for a specific bike:**
```python
bike = session.query(Bike).filter_by(brand="Trek", model="Marlin 5").first()
offers = bike.offers  # Via relationship
```

**Find cheapest offer across all bikes:**
```python
from sqlalchemy import desc
cheapest = session.query(BikeOffer).order_by(BikeOffer.price).first()
```

## Rollback

To keep the old JSON-based system:
1. Don't call `init_db()`
2. Keep importing from `app.store` instead of `app.repository`
3. Remove `sqlalchemy` from `requirements.txt`
4. Delete `app/models.py` and `app/repository.py`

## Next Steps

1. Add new Offer endpoints to populate `bike_offer` table — **mostly done (TODO-031/032/033):** the on-demand searcher
   (`searcher/app/repository.py` `save_offers(company, model, offers, source)`, sources `'olx.pl'`, `'decathlon.pl'` and
   `'allegro.pl'`, upsert on `url` scoped to (bike, source), replace semantics per bike and source) writes it and
   `backend/app/offers_repository.py` `get_used_offers` / `get_decathlon_offers` / `get_allegro_offers` read it for
   `POST /v1/bike/used/olx` / `POST /v1/bike/decathlon` / `POST /v1/bike/allegro` (Allegro rows carry `bike_offer_photos`
   from the searcher's Playwright scrape). Only Ceneo still goes through the generic response cache (and the UI does not
   call it); the old Allegro rows under the generic-cache key `/v1/bike/offer` are dead — nothing reads them (TODO-033
   decision 5: no backfill)
2. Add Bike model to bike creation flow (currently implicit in search results)
3. Create analytics queries (e.g., most-searched brands, price trends)
4. Add data export/backup utilities
