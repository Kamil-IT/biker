# Database Migration: JSON Cache → SQLAlchemy ORM

## Overview

This migration moves from JSON serialization in SQLite to a proper relational database schema using SQLAlchemy ORM.

### Old Approach
- Generic `cache` table with `(endpoint, request, response_json)`
- Searchable `search_cache` and `bike_details_cache` with JSON blobs
- No relationships or foreign keys
- TTL managed in application code

### New Approach
- Normalized `bikes` table — single source of truth for bike identity
- Related tables: `bike_results`, `bike_details`, `bike_offers`, `accessories`, `photos`
- Foreign key constraints
- TTL stored per record in the database
- Proper relationships via SQLAlchemy ORM

## Status

| Half | Tables | Live path | State |
|---|---|---|---|
| **Bike details** | `bikes` + `bike_details` + `bike_detail_photos` | `app/repository.py` | ✅ **Done** (TODO-019 phase 1) |
| **Search** | `searches` + `bike_results` + `accessories` | `app/repository.py` | ✅ **Done** (TODO-019 phase 2) |
| **Offers** | `bike_offers` + `bike_offer_photos` | none — **nothing writes them** | ⛔ **Pending** — the honest next task |

Offers are the remaining gap: `bike_offers` and `bike_offer_photos` exist in the schema but are
**empty, and no code path populates them**. `find_offer_prices` — the `price_max` gate on the
DB-first search branch — still reads the raw `cache` table written by the four offer endpoints, and
has no ORM equivalent. Migrating it means first making something write `bike_offers` at all.

### ⚠️ Running the migration is a prerequisite, not a suggestion

**Deploying this change without running `scripts/migrate_bike_details.py` leaves search silently
broken.** This is not a theoretical risk — three people hit it independently.

`init_db()` calls SQLAlchemy's `create_all()`, which creates **missing tables** but never `ALTER`s an
existing one. A `cache.db` that predates this change already has a `bike_results` table, so it keeps
the old columns: no `search_id`, no `position`. `repository.save_search` then raises
`OperationalError` on every write — and the `except Exception` around it (correct in itself: a cache
write must never break the request) logs it as non-fatal and moves on.

The result is a **silent** failure with no distinguishing signal:

- Nothing is ever written to `searches` / `bike_results`.
- TODO-009's DB-first branch therefore never hits, so **every** search runs the full AI pipeline.
- Latency and API spend go up with nothing obviously broken.

**Safety net:** `repository` now detects this specific failure — an `OperationalError` whose text
contains `no such column` / `no such table` — and logs it at **ERROR** naming the remedy, instead of
letting it blend into the routine non-fatal cache warnings. If you see that line, the migration has
not been run against this database. It is a detector, not a fix: the write still fails until you run
the script.

So the deploy order is fixed:

```bash
cd backend
python scripts/migrate_bike_details.py     # bring the schema and data up to date
uvicorn app.main:app --reload --port 8000  # only then start the app
```

Verify it took — a healthy database has both columns:

```bash
python -c "import sqlite3; print([r[1] for r in sqlite3.connect('cache.db').execute('PRAGMA table_info(bike_results)')])"
# expect search_id and position to appear in the list
```

### Self-heal: placeholder casing is repaired on every run

A database migrated by an **earlier build** carries placeholder (all-lowercase) casing on its `bikes`
rows, which search results then surface as `cannondale` instead of `Cannondale`. Skip-based
idempotency would never revisit those rows — a migration that cannot repair its own earlier output is
a trap — so the repair is **unconditional**:

`_repair_placeholder_casing()` runs on **every invocation**, after both backfills, regardless of what
was skipped as already-migrated. It re-reads the `search_cache` blobs — the only place real casing
survives — and upgrades placeholder rows by the same rule as `_get_or_create_bike`. **A plain re-run
repairs; `--force` is not required.**

```bash
cd backend
python scripts/migrate_bike_details.py     # repairs casing as a matter of course
```

Two returned keys report it:

- **`casing_repaired`** — list of `old -> new` strings, one per upgraded row.
- **`placeholders_left`** — list of `brand/model` still placeholder-cased *and* referenced by a search
  result. Non-empty means the repair could not finish; the script escalates it in its report.

**The repair depends on `search_cache` still existing.** Once it has been dropped, the original casing
is simply gone and nothing can reconstruct it — the script prints a loud warning naming each affected
bike. Those names recover on their own the next time a real search returns that bike, since the live
write path applies the same upgrade rule. This is a concrete reason to keep the legacy blob tables
until you are confident: it interacts directly with `--drop-legacy`, so drop only after a run reports
an empty `placeholders_left`.

To check for placeholder rows independently of the script:

```bash
python -c "import sqlite3; print(sqlite3.connect('cache.db').execute('SELECT count(*) FROM bikes WHERE brand = brand_norm').fetchone()[0])"
```

A non-zero count means placeholder rows are present (a genuinely all-lowercase brand also matches —
the same imprecision noted under Display casing).

> **Phase ordering is load-bearing.** The details backfill seeds `bikes` with placeholder casing and
> the search backfill supplies the real casing, so **the search step must run after the details
> step**. `migrate()` sequences this internally, so following the runbook is safe — but anyone
> documenting or invoking the phases separately must preserve that order.

### Details — done (TODO-019)

`POST /v1/bike/details` and `GET /v1/bike/details-cache` now read and write the normalised ORM
tables through `app/repository.py`. The JSON-blob `bike_details_cache` table and its
`save_bike_details` / `get_bike_details` helpers are gone from `app/store.py`.

What changed, and what deliberately did not:

- **TTL is unchanged at 30 days**, but it is computed from `bike_details.updated_at + ttl_seconds`
  instead of `time_stored + ttl`. `updated_at` carries `onupdate=now`, so re-saving an unchanged row
  refreshes its TTL — the same behaviour the blob upsert had when it rewrote `time_stored`.
- **Photos are rows** in `bike_detail_photos` ordered by `display_order`, not a JSON array. Zero rows
  deserialise back to `photos: []`, never `None`.
- **`bikes` gains normalised lookup columns `brand_norm` / `model_norm`**, populated by
  `models.norm()` (Python `.strip().lower()`) and constrained by
  `UNIQUE(brand_norm, model_norm)`. Lookups match those columns **exactly**, so `"Trek"`/`"Marlin 5"`
  and `"trek"`/`"marlin 5"` hit the same row — the behaviour the blob cache got from its
  `strip().lower()` key. A `@validates("brand", "model")` handler on `Bike` derives both columns, so
  they cannot drift apart — see the schema block below for the one case it does not cover.
- **Normalise in Python, not in SQL.** The obvious alternative — no new column, just
  `func.lower(brand) == company.strip().lower()` — is wrong here, and subtly enough that it is worth
  spelling out. SQLite's built-in `lower()` is **ASCII-only**; Python's `.lower()` is not. They agree
  on ASCII and disagree the moment an **uppercase non-ASCII** character is involved:

  ```
  Riese & Müller   sqlite lower -> riese & müller   python -> riese & müller   agree
  RIESE & MÜLLER   sqlite lower -> riese & mÜller   python -> riese & müller   DIFFER
  Škoda            sqlite lower -> Škoda            python -> škoda            DIFFER
  ```

  Note what this means: the canonical spelling `Riese & Müller` is **unaffected** — the failure needs
  all-caps input, or a brand whose initial is non-ASCII. That rarity is the danger, not a reason to
  dismiss it: when it does hit, the lookup misses and `save_bike_details` mints a **duplicate `bikes`
  identity**, which is the exact case-split bug this migration exists to fix. Do not "simplify" this
  back to `func.lower(...)`.
- **`bikes.brand` / `bikes.model` keep their real casing on write.** They are the shared identity row
  for search results and offers too, so normalising them in place would corrupt what search stores —
  which is why the normalised forms live in separate columns rather than replacing them. A save
  reuses an existing identity rather than creating a second row for it.
- **The response echoes the caller's casing**, not the stored row's — same as the blob path did.
- **Response payload shape is completely unchanged.** This is a storage-layer swap, invisible to the
  frontend.

Backfilled by `scripts/migrate_bike_details.py` (see [Migrating the details blob rows](#migrating-the-details-blob-rows)):
all 9 legacy blob rows migrated with their original ages preserved, 60 photo rows written, and the
test-script leftovers cleaned up (6 `bike_results` + 8 `accessories` rows, plus 2 orphaned `bikes`
rows). Re-running is a verified no-op. Read-back parity against the blob path is field-for-field
identical for all 9 bikes; `specialized`/`allez sprint` reads back `photos: []`, and the non-ASCII
key `riese & müller`/`nevo4 gt` round-trips intact.

### Search — done (TODO-019 phase 2)

`search_cache`'s JSON blob is replaced by id references into `bikes`. A new **`searches`** table owns
query identity and freshness, and `bike_results` hangs off it:

- **`searches`** — `id` PK · `query TEXT NOT NULL UNIQUE` (the `norm()`'d enriched query, the same key
  `store.save_search` used) · `created_at` · `ttl_seconds` (24 h).
- **`bike_results`** gains `search_id` FK → `searches.id` (`ondelete=CASCADE`, indexed) and
  `position INTEGER`.

Two things here are worth understanding rather than just reading off:

- **Why `position` exists.** The 5 bikes are allocated by score weight, so their order carries
  meaning. A JSON blob preserved that ordering for free; a set of rows does not — without an explicit
  column the order on read is whatever the query planner returns. Dropping it would be a **silent**
  regression: the right bikes, ranked wrong, with nothing failing. `position` makes the ordering
  explicit and `get_search_by_query` orders by it.
- **How this resolves the empty `.filter()`.** That defect — previously the blocker for migrating
  search at all — disappears rather than being patched. Query identity and TTL now live on the parent
  `searches` row, so the read is `Search.query == norm(query)` followed by ordering the children by
  `position`. There is no longer anything to filter `BikeResult` by, so there is no empty `.filter()`
  left to get wrong.

**Cutover.** `main.py` imports `save_search` / `get_search_by_query` / `find_bikes_by_brand` /
`find_bike_by_brand_model` from `.repository`. `store.py` loses its search helpers and the
`search_cache` DDL, keeping only `find_offer_prices` and `init_store`. As with the details half,
`search_cache` is dropped behind `--drop-legacy`, never on a default run.

#### Display casing: placeholder rows are upgraded, never downgraded

`bikes.brand` / `bikes.model` are the **single source of display casing** for search results, so what
is stored there is what the user sees. That creates a problem the details migration inherited: the
old details blob keyed on `strip().lower()`, so every `bikes` row it seeded holds an all-lowercase
value. Left alone, any brand that had ever been through the details cache would render lowercase in
search results — `cannondale` instead of `Cannondale`.

The get-or-create therefore treats a stored value **equal to its own normalised form** as a
placeholder carrying no casing information, and lets the first caller that supplies real casing
upgrade it:

```python
if stored == norm(stored) and incoming.strip() != norm(incoming):
    setattr(bike, attr, incoming.strip())
```

The rule is **monotonic** — an all-lowercase incoming value never overwrites real casing — so two
writers disagreeing cannot make the row oscillate. It settles on the first real casing it sees and
stays there.

The one accepted imprecision: a brand genuinely written all-lowercase (a stylised wordmark) is
indistinguishable from a placeholder and will be "upgraded" by any caller passing a capitalised
form. That is the right trade — the alternative is every migrated brand rendering lowercase forever.

#### Behaviour change: `find_bikes_by_brand` is an exact match

`GET /v1/bike/search-cache?brand=` **stops matching partial brand names.** The ORM version compares
`brand_norm` exactly where `repository`'s old unused implementation used an `ilike` substring match.

This is a deliberate alignment, not a regression: `store.py` is the **live** implementation and has
always done an exact normalised compare, so shipped behaviour is unchanged. What changes is that the
ORM path is brought into line with it. The `ilike` version was never wired into an endpoint, so no
caller ever saw substring matching.

Offers stay out of scope — see [Status](#status). `find_offer_prices` continues to read the raw
`cache` table, and `bike_offers` remains empty and unpopulated.

## Database Schema

### Core Tables

**`bikes`**
```
id (PK)
brand: str            — real casing, as supplied
model: str            — real casing, as supplied
brand_norm: str       — models.norm(brand), indexed
model_norm: str       — models.norm(model), indexed
created_at: datetime
updated_at: datetime
UNIQUE(brand, model)
UNIQUE(brand_norm, model_norm)
```
`models.norm(text)` is `text.strip().lower()` in Python. A **`@validates("brand", "model")`** handler
on `Bike` derives both `_norm` columns — chosen over an `__init__` override precisely because it also
fires on **later assignment** (`bike.brand = "..."`), which would otherwise leave a stale norm column
and break every subsequent lookup for that bike.

**The one gap:** `@validates` does not fire on a bulk `session.query(Bike).update(...)`. Edit
`brand`/`model` through the ORM, or write both `_norm` columns yourself in the same statement.

All identity lookups match `brand_norm` / `model_norm` exactly — see
[Details — done](#details--done-todo-019) for why the normalisation happens in Python rather than via
SQL `lower()`.

**`searches`** — Cached search identity + freshness
```
id (PK)
query: str        — norm()'d enriched query
created_at: datetime
ttl_seconds: int (default 24 h)
UNIQUE(query)
```

**`bike_results`** — Search results, references a search and a bike
```
id (PK)
search_id (FK → searches.id, ON DELETE CASCADE, indexed, nullable — see below)
bike_id (FK → bikes.id)
position: int     — score-weighted rank; read back ORDER BY position
match_score: float
explanation: text
created_at: datetime
```

`search_id` is nullable for the `ALTER TABLE` path only — SQLite cannot add a `NOT NULL` column
without a default, and a default `search_id` would be meaningless. Orphaned `bike_results` are **not**
a supported state: every write path sets it, and a **NULL means a pre-migration leftover**, which is
exactly how the migration's `_cleanup()` tells old test-script rows from migrated data and deletes
them.

**`accessories`** — Items in search results, references bike_results
```
id (PK)
bike_result_id (FK → bike_results.id)
name: str
```

**`bike_details`** — Full specifications
```
id (PK)
bike_id (FK → bikes.id, UNIQUE)
description: text (JSON serialized BikeDescription)
components: text (JSON serialized list[BikeCategory])
created_at: datetime
updated_at: datetime
ttl_seconds: int (default 30 days)
```

**`bike_detail_photos`** — Photos for bike details
```
id (PK)
bike_details_id (FK → bike_details.id)
url: str
display_order: int
```

**`bike_offers`** — Marketplace listings
```
id (PK)
bike_id (FK → bikes.id)
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
bike_offer_id (FK → bike_offers.id)
url: str
display_order: int
```

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

Both halves have been switched over. `app/main.py` now reads:

```python
from .store import init_store, find_offer_prices
from .repository import (
    save_search, get_search_by_query, find_bikes_by_brand,
    find_bike_by_brand_model, save_bike_details, get_bike_details,
)
from .models import init_db
```

`find_offer_prices` is all that still comes from `store.py`, because it reads the raw `cache` table
and has no ORM equivalent. Because every signature is identical, both cutovers were import swaps —
no call sites changed.

### 4. Migrating the details blob rows

`scripts/migrate_bike_details.py` is the one-off backfill. It copies every `bike_details_cache` row
into `bikes` + `bike_details` + `bike_detail_photos`, preserving each row's real age
(`time_stored` → `created_at`/`updated_at`, `ttl` → `ttl_seconds`) and the original photo ordering
(array index → `display_order`). Beyond the copy it also brings `bikes` up to the current schema:

1. `ALTER TABLE` in `brand_norm` / `model_norm` if absent, then backfill them on **every pre-existing
   `bikes` row** — not only the rows it creates. Rows written before this task would otherwise be
   invisible to the normalised lookup and get duplicated on the next save.
2. Merge `bikes` rows that share a normalised identity into one, repointing dependents at the
   survivor. Only a full normalised `(brand, model)` match merges — `Canyon/Grizl CF 7` and
   `Canyon/Grizl` are different bikes and stay separate.
3. Create the `uq_bike_brand_model_norm` unique index (after the merge, so it cannot fail on
   pre-existing duplicates).
4. Clean up the test-script leftovers (`bike_results` / `accessories` rows, and any `bikes` row
   nothing references).

It reads the blob table with raw sqlite3 and writes via SQLAlchemy against the same file, pointing
the ORM at it with `models.configure_db(path)` (restoring the previous engine afterwards) — which is
also how the parity test runs everything against a scratchpad copy instead of the real `cache.db`.
`models.DEFAULT_DB_PATH` is the fallback when no path is given.

It is also **importable**, which is how the parity test drives it:

```python
from scripts.migrate_bike_details import migrate

stats = migrate(db_path=None, drop_blob_table=False, force=False, verbose=True)
```

It returns a stats dict — `bikes`, `details`, `photos`, `skipped`, `legacy_rows`, `norm_backfilled`,
`merged_bikes`, `merged_names`, `casing_repaired`, `placeholders_left`, `bike_results_deleted`,
`accessories_deleted`, `orphan_bikes_deleted`, `orphan_names`, `blob_tables_dropped` (a **list of
dropped table names**, empty when nothing was dropped — not a bool). `casing_repaired` and
`placeholders_left` are covered under
[Self-heal](#self-heal-placeholder-casing-is-repaired-on-every-run).

Dropping the legacy blob tables is **opt-in from both entry points** — `migrate(drop_blob_table=True)`
or `--drop-legacy`. A default call from either keeps them, because the parity tests read the blob
path and cannot be re-run once it is gone.

```bash
cd backend
python scripts/migrate_bike_details.py                # idempotent — re-running is a no-op
python scripts/migrate_bike_details.py --force        # rebuild details rows that already exist
python scripts/migrate_bike_details.py --drop-legacy  # also drop bike_details_cache + search_cache
python scripts/migrate_bike_details.py --db /path/to/other.db   # operate on a different SQLite file
```

A bike that already has a `bike_details` row is skipped, so the default run is safe to repeat.
`DROP TABLE bike_details_cache` is deliberately **not** part of a default run — the parity test has
to read the blob table alongside the ORM one. Pass `--drop-legacy` once parity is green.

### 5. Verifying parity

`scripts/test_details_parity.py` (`pytest scripts/test_details_parity.py -v`) reads each cached bike
through both the legacy blob path and the ORM path and asserts the two `BikeDetailsResponse` objects
are equal field for field — casing echo, full `description`, the whole `components` tree including
nested `SpecItem` ordering, `photos` in the same order — plus a forced-stale row returning `None`
from both. It runs against a **copy** of the pre-migration `cache.db` in the scratchpad (override
with `TODO019_SNAPSHOT_DB`), and carries its own small blob reader rather than importing the removed
`store` helpers, so it stays runnable after the cutover as a permanent regression test.

## API Compatibility

`app.store` and `app.repository` split the surface between them:

| Helper | Lives in |
|---|---|
| `save_search(query, bikes, ttl) → None` | **`repository.py` (live)** — removed from `store.py` |
| `get_search_by_query(query) → Optional[list[BikeResult]]` | **`repository.py` (live)** — removed from `store.py` |
| `find_bikes_by_brand(brand) → list[BikeResult]` | **`repository.py` (live)** — removed from `store.py` |
| `find_bike_by_brand_model(brand, model) → list[BikeResult]` | **`repository.py` (live)** — removed from `store.py` |
| `find_offer_prices(brand, model) → list[float]` | `store.py` only — reads the raw `cache` table, no ORM equivalent |
| `save_bike_details(company, model, data, ttl) → None` | **`repository.py` (live)** — removed from `store.py` |
| `get_bike_details(company, model) → Optional[BikeDetailsResponse]` | **`repository.py` (live)** — removed from `store.py` |

Every signature is identical to the one it replaced, which is what made both cutovers an import swap.
`store.py` is now down to `init_store` and `find_offer_prices`.

## Benefits

✅ **Data Integrity** — Foreign keys, unique constraints, cascading deletes
✅ **Queryability** — Rich ORM queries instead of JSON parsing
✅ **Relationships** — One-to-many (Bike → BikeResults), One-to-one (Bike → BikeDetails)
✅ **Photo Management** — Proper ordering and sourcing
✅ **Indexed Lookups** — Brand, source, URL indices for fast queries
✅ **Future Extensions** — Easy to add new fields, relationships

## Example Queries

**Find all Trek bikes from cached searches:**
```python
from app.models import Bike, BikeResult, get_session

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

The details half is live, so a rollback is no longer a matter of simply not calling `init_db()` —
`store.py` no longer defines `save_bike_details` / `get_bike_details`, and the blob table is dropped
once `--drop-legacy` has run. To go back you would have to restore those two helpers and the
`bike_details_cache` DDL in `store.py`, re-point the `app/main.py` imports at `.store`, and backfill
the blob table from the ORM tables. Keep a copy of `cache.db` from before the migration if you want
that option cheaply.

The same applies to the search half: `store.py` no longer defines the search helpers or the
`search_cache` DDL. Note one asymmetry — rolling search back also loses `position`, since the blob
carried ordering implicitly and a restored blob would have to be rebuilt from `bike_results` in
`position` order to preserve it.

## Next Steps

1. **Offers** — the one remaining gap. Nothing writes `bike_offers` / `bike_offer_photos`, so the
   four offer endpoints' results live only in the raw `cache` table and `find_offer_prices` reads
   them from there. Populating `bike_offers` has to come before any ORM equivalent of that helper.
2. Create analytics queries (e.g., most-searched brands, price trends)
3. Add data export/backup utilities
