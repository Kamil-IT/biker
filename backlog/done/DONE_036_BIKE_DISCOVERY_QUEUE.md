# TODO-036 — Bike discovery queue (centrumrowerowe.pl → bike + bike_detail)

## Confirmed intent (interview 2026-09-29)

- **Outcome:** the catalogue fills itself from a shop listing instead of from user searches. A scraper
  finds bikes on centrumrowerowe.pl and queues them; a local processor fetches each product page,
  parses it **without AI** and stores full data in `bike` + `bike_detail` (+ photos, components), so
  those bikes show up in DB-first search and in the details view without an Anthropic call.
- **Everything local, in `webscraper/centrumrowerowe/`.** No GCP, no Cloud Run job, no new endpoint,
  no searcher route. Decided 2026-09-29 (first answer was a Cloud Run Job, changed the same day).
  Backend code (`backend/app/**`) is **not** modified; the scripts import it.
- **One queue row per (shop, product):** `UNIQUE(source, source_product_id)`, e.g.
  `("centrumrowerowe.pl", "pd27404")`. The ~2044 listing rows are colour/size variants; they collapse
  to one row per `pd…` ID. De-duplication across shops / against existing bikes happens when a row is
  processed (normalised brand + model), not in the table.
- **Worker = page parser, no AI at all.** No `/v1/bike/details`, no `claude -p`, no fallback. A page
  that cannot be parsed → `failed` (with `last_error`), retried with backoff, then left for a human.
- **Scraper writes straight to the DB** (upsert). `--csv` keeps the current `rowery.csv` output.
- **Out of scope:** other shops, AI fallback, deployment/scheduling, reviews and offers for the found
  bikes, any UI change, writing to the prod Cloud SQL (only on an explicit decision by the user).

## Files (all new, in `webscraper/centrumrowerowe/`)

| file | responsibility |
|---|---|
| `db.py` | puts `backend/` on `sys.path`, loads `backend/.env`, re-uses `app.models` (engine, `Base`, `Bike`, `dialect_insert`) and `app.repository`; defines `BikeDiscovery` on the backend's `Base`; `ensure_table()` = `BikeDiscovery.__table__.create(checkfirst=True)` |
| `scrape_rowery.py` | existing scraper; after collecting, upserts into `bike_discovery` (default) and/or writes `rowery.csv` (`--csv`); `--dry-run` prints counts only |
| `name_split.py` | heuristic `"Rower trekkingowy ROMET Wagant 3"` → `bike_type="trekkingowy"`, `company="ROMET"`, `model="Wagant 3"` (type prefix = leading lower-case words after `Rower`; brand = the following run of upper-case tokens) |
| `product_parser.py` | pure function `parse_product(html, url) -> ParsedBike` — no network, testable on saved HTML |
| `process_queue.py` | dispatcher + worker in one process: claims a batch, fetches + parses each page, saves, updates status |
| `tests/` | pytest on saved fixture pages (`tests/fixtures/*.html`, ≥ 3: trekking, MTB, e-bike) + `name_split` cases |

## Table `bike_discovery`

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `source` | str(50), not null | `"centrumrowerowe.pl"` |
| `source_product_id` | str(64), not null | `pd27404` from the URL |
| `raw_name` | str(512), not null | name as listed |
| `company` / `model` | str(255), not null | from `name_split` (the worker corrects them from the product page) |
| `bike_type` | str(64), nullable | `trekkingowy`, `górski`, … |
| `details_link` | str(2048), nullable | product URL **without** `?v_Id=` |
| `price` | str(100), nullable | lowest price seen among the product's variants in this scrape |
| `status` | str(16), not null, default `pending` | `pending` / `in_progress` / `done` / `failed` / `skipped` |
| `attempts` | int, not null, default 0 | |
| `last_error` | text, nullable | |
| `locked_at` | datetime, nullable | lease; a row `in_progress` with `locked_at` older than 15 min is claimable again |
| `next_attempt_at` | datetime, nullable | backoff: 1 h, 6 h, 24 h; after 3 attempts stays `failed` |
| `bike_id` | int FK → `bike.id` ON DELETE SET NULL, nullable | set once the bike exists in `bike` |
| `first_seen_at` / `last_seen_at` / `updated_at` | datetime | |

`UNIQUE(source, source_product_id)`, index on `(status, next_attempt_at)`.
No `is_inserted` column: `bike_id IS NOT NULL` = the bike is in `bike`; `status = 'done'` = it has
full `bike_detail` data. Different states on purpose.

## Scraper upsert rules

- Group listing rows by `pd…` ID; one upsert per product (`dialect_insert` + `ON CONFLICT (source,
  source_product_id) DO UPDATE`).
- On conflict update only `raw_name`, `company`, `model`, `bike_type`, `details_link`, `price`,
  `last_seen_at`, `updated_at`. **Never** touch `status`, `attempts`, `bike_id` — a re-scrape must not
  re-queue done rows.
- Report: products seen, inserted, updated.

## Processor (`process_queue.py`)

- `--limit N` (default 20), `--delay 1.0` s between page fetches, `--source`, `--retry-failed`,
  `--dry-run` (parse and print, write nothing).
- Claim: rows with `status IN ('pending','failed')` and `next_attempt_at` null or due, or stale
  `in_progress`; PostgreSQL `SELECT … FOR UPDATE SKIP LOCKED`, SQLite a plain update (single process).
  Set `in_progress`, `locked_at`, `attempts += 1`.
- Per row:
  1. Fetch `details_link` (httpx, the scraper's User-Agent, timeout 20 s). 404 → `skipped` (product gone).
  2. `parse_product`. Brand casing from JSON-LD `Product.brand` (e.g. `Romet`, not `ROMET`).
  3. Look up the bike by **Python-normalised** brand + model (`repository._find_bike_id`). If it has a
     `bike_detail` newer than the details TTL (30 d) → `skipped`, `bike_id` set, nothing overwritten
     (AI- or earlier-parsed data wins).
  4. Otherwise `repository.save_bike_details(brand, model, BikeDetailsResponse)` — **passing the stored
     casing of an existing bike**, because `save_bike_details` matches `brand`/`model` exactly and would
     otherwise mint a duplicate `bike` row. Set `bike_id`, `status = done`, clear `last_error`.
  5. Any exception → `failed`, `last_error` (≤ 1000 chars), `next_attempt_at` by backoff. One bad page
     never stops the batch.
- Final summary: done / skipped / failed counts.

## Parser → `BikeDetailsResponse`

Data sources on the page (checked on `rower-trekkingowy-romet-wagant-3-pd27404`, 2026-09-29):

- JSON-LD `Product`: `name`, `brand`, `description`, `image`, `category`, `sku`.
- The **Specyfikacja** table: section headings (`Informacje`, `Rama`, `Napęd`, `Hamulce`, …) followed by
  key/value rows (`Rozmiar ramy | 19"`, `Przerzutka tylna | Shimano Acera RD-M3020, 7s`, …).

Mapping:

- `description`: `BikeDescription` with the shop's Polish marketing text (JSON-LD `description`, else
  the description section), trimmed to the first ~5 sentences; no citations.
- `photos`: JSON-LD `image` (+ gallery images if present), absolute URLs, de-duplicated, ≤ 8.
- `components`: Polish table sections/keys mapped to the backend's **English** categories
  (`Frame`, `Drivetrain`, `Brakes`, `Wheels`, `Cockpit`, `Saddle & Seatpost`, `Lighting`, `Accessories`,
  `Electric / Powertrain`) and spec keys through one explicit dictionary in `product_parser.py`;
  unknown keys go to `Accessories` rather than being dropped. Values stay as the shop wrote them.
- **DB-first search must match these bikes**: wheel size under key `Wheel size` (or `Size` in `Wheels`),
  frame sizes under `Frame`/`Frame` key `Sizes` — **all** sizes of the product (from the variant
  selector / the listing's variants), not only the variant on the page; e-bikes get an
  `Electric / Powertrain` category (motor, battery rows), non-e-bikes must not.

## Success criteria

- `pytest webscraper/centrumrowerowe/tests` green.
- On the local PostgreSQL (`biker-pg`): the scraper creates ~1300 queue rows; a second run inserts 0
  and leaves statuses untouched.
- `process_queue.py --limit 20` → ≥ 18 `done`; for 3 of them `GET /v1/bike/details-cache` returns
  description, photos and components, and `POST /v1/bike/search {"brand": …, "wheel_size": …}` finds
  them with zero AI calls.
- A bike already in `bike` with fresh details → `skipped`, its data unchanged, no duplicate `bike` row.

## Docs

- `README.md` and `CLAUDE.md`: a short "Bike discovery (local)" section — what the three scripts do,
  the table, how to run. `backend/README.md` is untouched (no endpoint).
