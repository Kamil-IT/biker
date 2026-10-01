# Bike discovery from centrumrowerowe.pl

Local scripts that fill the biker database with bikes from the centrumrowerowe.pl catalogue
**without any AI call**. A scraper queues every product the shop lists, a processor fetches each
product page, parses it and stores the bike the way the backend reads it, and a copy script moves
the result into another database. Nothing here runs on its own or on GCP — you start each step by
hand. The backend code is never modified; the scripts import it.

## How it works

```
listing pages ──scrape_rowery.py──▶ bike_discovery + bike_discovery_listing ──process_queue.py──▶ bike
                                                                                  bike.description (+ bike_detail_component)
                                                                                  bike_detail_photos
                                    copy_to_db.py: local database ───────────────▶ another database (e.g. Cloud SQL)
```

### 1. `scrape_rowery.py` — find the bikes

Downloads `https://www.centrumrowerowe.pl/rowery/?page=1..N`. Every listing page carries a JSON-LD
`ItemList` block, so the products come out of the HTML as data (name, price, URL) without parsing
the layout. The ~2000 listing rows are colour/size variants: rows sharing the `pd<digits>` product id
in the URL collapse into one product (~1300). For each product the scraper:

- splits the listed name into bike type, brand and model (`name_split.py`, e.g.
  `Rower trekkingowy ROMET Wagant 3` → `trekkingowy` / `ROMET` / `Wagant 3`),
- keeps the lowest price among the variants,
- strips `?v_Id=` from the URL.

Each product is upserted as a **listing** in `bike_discovery_listing` (one product in one shop, unique
by `(source, source_product_id)`) and linked to its **bike** in `bike_discovery` (the bike and its
processing state, unique by normalised company + model). A new listing goes to the bike with the same
normalised name; a missing bike is inserted as `pending`, so one bike can have many listings. A
re-scrape refreshes only the listing's name, link, price and `last_seen_at`; it never touches an
existing bike (`status`, `attempts`, `bike_id`, `company`, `model`, `bike_type`) and a known listing
never changes bike, so nothing is processed twice. It prints `bikes inserted`, `listings inserted`
and `listings updated`.

### 2. `process_queue.py` — fetch, parse, store

Claims a batch of `pending` bikes (PostgreSQL: `SELECT … FOR UPDATE SKIP LOCKED`) and, per bike,
tries its listings newest `last_seen_at` first, using the parser registered for the listing's shop
(`PARSERS`; only `centrumrowerowe.pl` so far). The first page that parses wins; each attempt is
recorded on the listing (`fetched_at`, `fetch_error`, `NULL` after a success). Per listing:

1. **Fetch** the product page — https on `centrumrowerowe.pl` only, redirects followed by hand
   (max 3, same hosts), `--delay` seconds between pages. 404/410 → `skipped` (product gone).
2. **Parse** it with `product_parser.py` (pure function, no network): the Polish description from
   the page's own article, up to 8 photos, the brand in its real casing (`Romet`, not the JSON-LD's
   `ROMET`), and the *Specyfikacja* table. `spec_mapping.py` maps the Polish sections and labels to
   the backend's English categories (`Frame`, `Drivetrain`, `Brakes`, `Wheels`, `Cockpit`,
   `Saddle & Seatpost`, `Lighting`, `Accessories`, `Electric / Powertrain`). Frame sizes go to
   `Frame / Frame / Sizes` and the wheel size to `Wheels / Wheelset / Wheel size`, which is where
   the backend's DB-first search looks; only e-bike pages get `Electric / Powertrain`; unknown
   labels land in `Accessories / Other`; values are fitted to the column sizes read from
   `app.models`.
3. **Store** through the backend's own functions (`bike_store.py`): the bike in `bike` (looked up
   by normalised brand + model, reusing the stored casing so no duplicate row is minted), details
   on the bike row (`description`; `short_description` stays `""` — the parser writes none) + `bike_detail_component` rows and photos in
   `bike_detail_photos` (only when the bike has none). `POST /v1/bike/details` reads the bike row
   directly (TODO-041), so no generic-cache entry is written any more. A save counts only when
   `repository.save_bike_details` returns True (it swallows errors and reports them as False).
4. **Mark** the bike: `done`; `skipped` when the bike already had details (nothing overwritten —
   photos are still added if it had none) or every listing is gone (404/410); `failed` with
   `last_error` and a backoff of 1 h, then 6 h — the third failure is final until `--retry-failed`.
   A bike fails only when *every* listing failed (`last_error` is `pid: error; …` when there are
   several); a store error, a listing of a shop without a parser (`UnknownSource`) or a bike with no
   listings ("bike has no listings — nothing to fetch") fail it at once. The stored casing is written
   to `company`/`model` unless another `bike_discovery` row already has that normalised identity.

A claimed row holds a 15-minute lease (`locked_at`, refreshed per row); a row taken over by another
run is reported as `lost` and not written. Ctrl+C releases the claimed rows back to `pending`.

### 3. `copy_to_db.py` — copy the result elsewhere

Reads the `bike_discovery` rows with their listings, the processed bikes, their details and photos
from the source database into memory, then writes them into the target: bikes are matched by
`(company_norm, model_norm)` and listings by `(source, source_product_id)` (a listing already in the
target stays on its bike there), existing details and photos in the target are kept, queue rows get the **target's** bike ids and are never downgraded (a `done` target row
stays `done`; `in_progress` becomes `pending`). The run is idempotent — a second run changes
nothing. Counters include `listings_inserted` and `listings_unchanged`.

### 4. `migrate_discovery_listings.py` — move an old database to the two-table layout

Databases created before TODO-039 have one `bike_discovery` table with the shop columns on the bike
row. Run this **once per existing database before any other script** — they all refuse the old layout
with a message pointing here. It moves each old row's shop columns into one listing, fills
`company_norm`/`model_norm`, merges rows that share a normalised identity (survivor: highest status
`done` > `skipped` > `failed` > `in_progress` > `pending`, ties → lowest id; it gets every listing and
keeps its `bike_id`, or takes the first one a merged row had), then drops the moved columns and the old
`UNIQUE(source, source_product_id)`. One transaction, verified before commit (listing count = old row
count, every listing linked, no bike lost its `bike_id`); a mismatch rolls back with exit code 1.
SQLite rebuilds the table, PostgreSQL alters it in place under an `ACCESS EXCLUSIVE` lock. A second
run prints "already migrated". Run on the local PostgreSQL `biker-pg` on 2026-09-30 (rehearsed first on a PostgreSQL copy of the real table): `old_rows=1310 bikes=1278 listings=1310 merged_groups=30 merged_rows=32 bike_id_conflicts=0` - the merged groups are men's/women's variants of the same model name (e.g. "Rower crossowy ROMET Orkan 5 CS" + "... damski ..."); a second run printed "already migrated". Run on GCP Cloud SQL the same evening (through the proxy, `--allow-remote`, started by the user by hand): identical numbers (1310 → 1278 bikes, 1310 listings, 49 done / 1 skipped / 1228 pending, 50 `bike_id` kept), second run "already migrated". After the migration, on `biker-pg` (2026-09-30): a full re-scrape saw 1311 products and inserted 7 bikes + 7 listings (new `pd` ids in the catalogue; 6 old ones were not seen) and updated 1304 listings; `process_queue.py --limit 5` gave `done=5 skipped=0 failed=0`; 194 unit tests pass.

## Files

| file | role |
|---|---|
| `scrape_rowery.py` | listing scraper → listing + bike upsert (or `rowery.csv`) |
| `name_split.py` | `split_name("Rower trekkingowy ROMET Wagant 3")` → type / company / model |
| `product_parser.py` | `parse_product(html, url) -> ParsedBike`, `to_details_response()` |
| `spec_mapping.py` | the Polish → English dictionary for sections, labels and spec keys |
| `process_queue.py` | dispatcher + worker: claim a bike, try its listings, parse, store, mark |
| `discovery_repo.py` | bike / listing lookups shared by scraper, processor and copy script |
| `migrate_discovery_listings.py` | one-off: old one-table `bike_discovery` → bike + listing tables |
| `bike_store.py` | storing helpers shared by the processor and the copy script |
| `copy_to_db.py` | copy bikes + listings + details + photos into another database |
| `db.py` | backend bootstrap (`sys.path`, `backend/.env`), `BikeDiscovery` + `BikeDiscoveryListing` models, `check_target()` |
| `tests/` | pytest on saved product pages in `tests/fixtures/`, temp SQLite only |

## Tables

`bike_discovery` — the bike and its processing state:

| column | notes |
|---|---|
| `company`, `model`, `bike_type` | from the listing name; `company`/`model` set to the bike's stored casing once processed |
| `company_norm`, `model_norm` | `strip().lower()`; **UNIQUE** together (`uq_bike_discovery_identity`) |
| `status` | `pending` → `in_progress` → `done` / `skipped` / `failed` |
| `attempts`, `last_error`, `next_attempt_at` | retry bookkeeping (max 3 attempts, backoff 1 h / 6 h) |
| `locked_at` | 15-minute lease of an `in_progress` row |
| `bike_id` | FK → `bike.id` (ON DELETE SET NULL) once the bike exists |
| `created_at`, `updated_at` | |

`bike_discovery_listing` — one product in one shop (one bike can have many):

| column | notes |
|---|---|
| `discovery_id` | FK → `bike_discovery.id` (ON DELETE CASCADE), not null |
| `source`, `source_product_id` | `centrumrowerowe.pl`, `pd27404`; **UNIQUE** together |
| `raw_name`, `details_link`, `price` | listed name, product URL without `?v_Id=`, lowest variant price |
| `first_seen_at`, `last_seen_at`, `updated_at` | |
| `fetched_at`, `fetch_error` | last attempt to fetch the page and its error (`NULL` after a fetch that parsed) |

Indexes: `(status, next_attempt_at)` on the bike, `(discovery_id)` and `(source, last_seen_at)` on the
listing. `bike_id IS NOT NULL` means the bike is in `bike`; `status = 'done'` means this run stored
its details. `db.ensure_table()` creates both tables on first use, and refuses a database that still
has the old one-table layout (run `migrate_discovery_listings.py` first).

## Running

Requirements: the backend venv (`backend/.venv`, Python 3.14 — SQLAlchemy, httpx, pydantic) plus
`beautifulsoup4` and `pytest` from `requirements.txt`. The database is the `DATABASE_URL` from
`backend/.env` (the local `biker-pg` container by default). Every script prints the masked
database URL at start and **refuses a non-local database** unless `--allow-remote` is given
(port 6543 — the Cloud SQL proxy — and `/cloudsql` sockets count as remote).

```powershell
cd webscraper\centrumrowerowe
$env:PYTHONUTF8 = '1'
..\..\backend\.venv\Scripts\pip.exe install -r requirements.txt   # once

# 0. only on a database created before TODO-039 (one-table bike_discovery): migrate it first
..\..\backend\.venv\Scripts\python.exe migrate_discovery_listings.py --dry-run   # runs and rolls back
..\..\backend\.venv\Scripts\python.exe migrate_discovery_listings.py

# 1. queue the catalogue (~70 pages, ~1300 products)
..\..\backend\.venv\Scripts\python.exe scrape_rowery.py
..\..\backend\.venv\Scripts\python.exe scrape_rowery.py --dry-run --max-pages 2   # counts only
..\..\backend\.venv\Scripts\python.exe scrape_rowery.py --csv                     # also write rowery.csv

# 2. process the queue (about 3 s per bike)
..\..\backend\.venv\Scripts\python.exe process_queue.py --limit 20
..\..\backend\.venv\Scripts\python.exe process_queue.py --limit 5 --dry-run     # fetch + parse + print, write nothing
..\..\backend\.venv\Scripts\python.exe process_queue.py --retry-failed           # put failed rows back first

# 3. copy the result into Cloud SQL (proxy in another terminal:
#    cloud-sql-proxy --gcloud-auth --port 6543 biker-engine-prod:europe-central2:biker-pg)
$env:PGPASSFILE = 'C:\path\to\backend\gcp-prod-pgpass.conf'
..\..\backend\.venv\Scripts\python.exe copy_to_db.py --target-url postgresql+psycopg://biker@127.0.0.1:6543/biker --allow-remote --dry-run
..\..\backend\.venv\Scripts\python.exe copy_to_db.py --target-url postgresql+psycopg://biker@127.0.0.1:6543/biker --allow-remote
```

Flags:

| script | flag | meaning |
|---|---|---|
| `scrape_rowery.py` | `--csv` | also write `rowery.csv` (name;price;url) |
| | `--dry-run` | print counts, write nothing |
| | `--max-pages N` | stop after N listing pages |
| | `--allow-remote` | allow a non-local database |
| `process_queue.py` | `--limit N` | rows per run (default 20) |
| | `--delay S` | seconds between page fetches (default 1.0) |
| | `--source` | only bikes that have a listing from this shop |
| | `--retry-failed` | reset every `failed` row to `pending` with 0 attempts before claiming |
| | `--dry-run` | fetch, parse and print; claim nothing, write nothing |
| | `--allow-remote` | allow a non-local database |
| `copy_to_db.py` | `--target-url URL` | database to write (password via `PGPASSFILE` / `PGPASSWORD`) |
| | `--source-url URL` | database to read (default: `DATABASE_URL` from `backend/.env`) |
| | `--source`, `--limit` | only bikes listed by this shop (and only its listings) / at most N bikes |
| | `--dry-run` | report what would change, write nothing |
| | `--allow-remote` | required for a non-local target |
| `migrate_discovery_listings.py` | `--url URL` | database to migrate (default: `DATABASE_URL` from `backend/.env`) |
| | `--dry-run` | migrate, verify and report, then roll back |
| | `--allow-remote` | required for a non-local database, **`--dry-run` included** (it runs the DDL and locks the table before rolling back) |

## Tests

```powershell
$env:PYTHONUTF8 = '1'; ..\..\backend\.venv\Scripts\python.exe -m pytest tests -q
```

The tests parse the saved pages in `tests/fixtures/` (a trekking bike, an MTB, two e-bikes) and run
the scraper upsert, the processor and the copy script on temporary SQLite files. They never touch
the database from `backend/.env`.

## Limits

- One shop only. Other shops need their own parser and `source` value.
- The size selector shows only the sizes the shop has for the displayed colour, so `Sizes` can be
  incomplete.
- `repository.get_bike_details` now matches brand and model on the normalised columns (TODO-041),
  so a discovered bike is found whatever casing the caller uses; the processor still stores the
  page's casing (or the casing already in `bike`).
- Until `backend/scripts/migrate_drop_bike_detail.py` has run on a database (details columns on `bike`,
  `bike_detail_component.bike_id`) the processor's save fails on it — run the migration first.
