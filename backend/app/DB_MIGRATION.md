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
- Related tables: `bike_detail`, `bike_offer`, `photos`, and the search cache
  (`search_cache` + `search_bike_rating_cache`)
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

**`search_cache`** — one cached search query
```
id (PK)
query: text (UNIQUE)
time_stored: str (ISO-8601)
```

**`search_bike_rating_cache`** — one bike a search returned (replaces the old
`bike_results` + `accessories` tables)
```
id (PK)
search_cache_id (FK → search_cache.id, CASCADE)
bike_id (FK → bike.id, CASCADE)
explanation: text
accessories: text (JSON array of strings)
display_order: int
```

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

- Search cache — `app.store`: `save_search`, `get_search_by_query`,
  `find_bikes_by_brand` (backed by `search_cache` + `search_bike_rating_cache`).
- Details — `app.repository`: `save_bike_details`, `get_bike_details`
  (backed by `bike_detail` + `bike_detail_component`; no TTL — stored details are returned whatever their age). Since TODO-041 `POST /v1/bike/details` is a pure read of them (normalised brand/model lookup, `short_description` included) and the live writer is the searcher (`POST /v1/bike/details/search`, `searcher/app/repository.py` `save_details`); helpers `empty_details`, `has_complete_details`, `accessory_chips`, `fill_bike_results`, `search_fill_for`.
- Bike photos — `app.photos_repository`: `get_bike_photos` (`POST /v1/bike/photos`) and `save_bike_photos`
  (offline pipeline only); the searcher's photo search is the live writer (backed by `bike_detail_photos`).
- DB-first search (TODO-024) — `app.repository.find_bikes_by_details`: matches
  `/v1/bike/search` checkable fields against `bike` + `bike_detail_component`.
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

TODO-040 removed `match_score` from `POST /v1/bike/search`, `GET /v1/bike/search-cache` and `BikeResult`; the search
cards show the expert rating from the stored reviews in `bike_review` instead (`POST /v1/bike/review/cached`). The column that stored the
score, `search_bike_rating_cache.rating` (`FLOAT NOT NULL`), is dropped from the model and from every existing
database by `scripts/migrate_drop_search_rating.py`. `display_order` stays (the AI answer's order).

**Run it on every pre-existing database BEFORE the new backend is deployed on it** — `create_all()` never `ALTER`s a
table, and the new `save_search` does not write `rating`, so on an unmigrated database the `NOT NULL` column makes
it fail (rollback + WARNING; the search answer is still returned, the bikes are just not stored). Once migrated, the
**old** backend's `save_search` fails the same way until the new one is deployed. Production order: migrate Cloud
SQL → deploy the backend → deploy the frontend.

```bash
cd backend
python scripts/migrate_drop_search_rating.py --dry-run          # $DATABASE_URL (backend/.env), else backend/cache.db
python scripts/migrate_drop_search_rating.py
python scripts/migrate_drop_search_rating.py --db path/to/copy.db
python scripts/migrate_drop_search_rating.py --url postgresql+psycopg://biker:biker@localhost:5432/<db>
```

- `ALTER TABLE search_bike_rating_cache DROP COLUMN rating` on both dialects (SQLite ≥ 3.35 — the column has no index,
  key or constraint); PostgreSQL first takes `LOCK TABLE search_bike_rating_cache IN SHARE ROW EXCLUSIVE MODE`.
- One transaction: every row's `id, search_cache_id, bike_id, explanation, accessories, display_order` is snapshotted
  before and compared after; any difference or error rolls back (exit code 1). Row counts are printed.
- Idempotent: no `rating` column → `already-migrated`; no table → `absent` (left to `init_db()`). Importable:
  `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict` (`status`, `rows_before`, `rows_after`, `verified`, `error`).
- Verified 2026-09-30: a copy of `cache.db` (206 rows) and the local PostgreSQL (199 rows) — rows kept, second run a no-op.

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
- `search_bike_rating_cache.explanation` / `accessories` are kept (no migration) but `store.save_search` writes `""` / `"[]"`;
  a search result's text and chips are read from `bike_detail` at request time.
- `scripts/purge_details_cache.py` (`--dry-run`, `--db`, `--url`) deletes the dead `endpoint_req_to_body_cache` rows of
  `'/v1/bike/details'` — local only; Cloud SQL on an explicit go.

## Benefits

✅ **Data Integrity** — Foreign keys, unique constraints, cascading deletes
✅ **Queryability** — Rich ORM queries instead of JSON parsing
✅ **Relationships** — One-to-many (Bike → BikeOffer, SearchCache → ratings), One-to-one (Bike → BikeDetails)
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
