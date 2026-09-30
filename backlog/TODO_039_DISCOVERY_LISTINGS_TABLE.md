# TODO-039 — Split `bike_discovery` into the bike and its shop listings

## Confirmed intent (interview 2026-09-30)

- `bike_discovery` (TODO-036) mixes two things: the bike being discovered and the shop data it was
  found in. The user wants **`bike_discovery` to hold only the bike and its processing state**, and
  everything that comes from a shop (centrumrowerowe.pl today, more shops later) in a separate table
  `bike_discovery_listing`, **one bike → many listings**.
- No `processed_listing_id` on the bike (explicitly dropped): the bike does not record which listing
  produced its data.
- Everything stays local in `webscraper/centrumrowerowe/`; the backend is not modified.
  Both databases that hold the queue today (local `biker-pg` and the GCP Cloud SQL copy, 1310 rows
  each) are migrated by a script, without re-scraping.

## Tables

`bike_discovery` — the bike and its processing:

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `company` / `model` | str(255), not null | casing from the product page (the worker corrects the listing's) |
| `company_norm` / `model_norm` | str(255), not null | `strip().lower()`; `UNIQUE(company_norm, model_norm)` — the bike's identity across shops |
| `bike_type` | str(64), nullable | |
| `bike_id` | int FK → `bike.id` ON DELETE SET NULL, nullable | set once the bike exists in `bike` |
| `status` | str(16), not null, default `pending` | `pending` / `in_progress` / `done` / `skipped` / `failed` |
| `attempts`, `last_error`, `locked_at`, `next_attempt_at` | as in TODO-036 | lease 15 min, backoff 1 h / 6 h, 3 attempts |
| `created_at`, `updated_at` | datetime | |

Index `(status, next_attempt_at)`.

`bike_discovery_listing` — one product in one shop:

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `discovery_id` | int FK → `bike_discovery.id` ON DELETE CASCADE, not null | |
| `source` | str(50), not null | `centrumrowerowe.pl` |
| `source_product_id` | str(64), not null | `pd27404`; `UNIQUE(source, source_product_id)` |
| `raw_name` | str(512), not null | name as listed |
| `details_link` | str(2048), nullable | product URL without `?v_Id=` |
| `price` | str(100), nullable | lowest price among the variants |
| `first_seen_at`, `last_seen_at`, `updated_at` | datetime | |
| `fetched_at`, `fetch_error` | datetime / text, nullable | last attempt to fetch this page |

Indexes `(discovery_id)`, `(source, last_seen_at)`.

## Behaviour

- **Scraper**: per product, upsert the listing by `(source, source_product_id)` (refresh `raw_name`,
  `details_link`, `price`, `last_seen_at`, `updated_at`). Find the bike by `(company_norm,
  model_norm)` from `name_split`; missing → insert `bike_discovery` as `pending`; existing → link the
  listing and **leave the bike's status, attempts and bike_id untouched**. A listing never changes
  bike from one scrape to the next unless it was unlinked.
- **Processor**: claims bikes (unchanged claim/lease/backoff logic). For a claimed bike it walks the
  bike's listings newest `last_seen_at` first, using the parser registered for the listing's `source`
  (only `centrumrowerowe.pl` for now); the first listing that fetches and parses wins. A listing's
  fetch/parse error goes to that listing's `fetched_at`/`fetch_error`; the bike gets `failed` +
  `last_error` only when every listing failed. 404/410 on every listing → `skipped`.
  Storing (details, photos, cache entry, stored-casing rules) is unchanged.
- **`copy_to_db.py`**: copies both tables; bikes matched by `(company_norm, model_norm)`, listings by
  `(source, source_product_id)`; never-downgrade rule unchanged.
- **Migration script** `migrate_discovery_listings.py`: creates `bike_discovery_listing`, moves the
  shop columns of every existing `bike_discovery` row into one listing linked to it, fills
  `company_norm`/`model_norm`, drops the moved columns and the old unique constraint, adds the new
  ones. Idempotent (re-run = no-op), `--dry-run`, same DB-target guard (`--allow-remote`). Rows
  that collapse to the same `(company_norm, model_norm)` are merged: the bike row with the "highest"
  status (`done` > `skipped` > `failed` > `in_progress` > `pending`) survives, all listings attach to it.
- Known limit, accepted: identity by normalised name means two shops naming the same bike
  differently produce two `bike_discovery` rows; merging is a later concern.

## Files (`webscraper/centrumrowerowe/`)

`db.py` (both models), `scrape_rowery.py`, `process_queue.py`, `bike_store.py`, `copy_to_db.py`,
new `migrate_discovery_listings.py`, tests for all of it, `README.md` here + the "Bike discovery"
sections of `README.md` / `CLAUDE.md`.

## Success criteria

- `pytest webscraper/centrumrowerowe/tests` green, including migration tests on a SQLite copy of the
  old layout and a merge case.
- Migration run on local `biker-pg`: 1310 listings, ≤ 1310 bikes, statuses preserved (49 done,
  1 skipped), `bike_id` preserved; a second run changes nothing.
- Re-scrape after migration: 0 new bikes, 0 new listings, statuses untouched.
- `process_queue.py --limit 5` → 5 done through the listing path.
- Migration + scrape repeated on GCP only on the user's explicit go.

## Out of scope

A second shop's scraper/parser, merging near-duplicate bikes, any backend change.
