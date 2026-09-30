# TODO-039 — Discovery listings table — test plan and results

Test basis: `backlog/TODO_039_DISCOVERY_LISTINGS_TABLE.md`. Tested 2026-09-30 on the worktree
`feature/discovery-listings` (uncommitted changes in `webscraper/centrumrowerowe/**`, `README.md`,
`CLAUDE.md`), local PostgreSQL `biker-pg`, the already running backend `:8003` and frontend `:5176`
(the backend is not changed by this task). Anthropic API credits were exhausted, so only DB-served paths
were exercised; `POST /v1/bike/review` answering 400 is expected and not part of this change.

## Scope

In: the new schema (`bike_discovery` + `bike_discovery_listing`), the migration of the TODO-036 layout,
the scraper's listing upsert, the processor's listing path, `copy_to_db.py` (unit level), and the parsed
bikes as seen through DB-first search and the details view.
Out: a second shop, merging near-duplicate bikes, the GCP migration (only on the user's explicit go).

## Traceability

| Requirement | Implemented in | Status | Covered by |
|---|---|---|---|
| `bike_discovery` = bike + processing state, `UNIQUE(company_norm, model_norm)`, index `(status, next_attempt_at)` | `db.py` `BikeDiscovery` | Implemented | unit tests, DB-01, DB-02, DB-05, DB-06, DB-10 |
| `bike_discovery_listing`, FK `ON DELETE CASCADE`, `UNIQUE(source, source_product_id)`, indexes `(discovery_id)`, `(source, last_seen_at)`, `fetched_at` / `fetch_error` | `db.py` `BikeDiscoveryListing` | Implemented | unit tests, DB-03 … DB-06 |
| No `processed_listing_id` on the bike | `db.py` | Implemented (absent) | DB-01 |
| Scraper: upsert listing by `(source, pid)`, refresh raw_name / details_link / price / last_seen_at / updated_at; bike found by norm identity or inserted `pending`; bike status / attempts / bike_id untouched | `scrape_rowery.py` `upsert`, `discovery_repo.py` | Implemented | unit tests, RUN-03 |
| Processor: listings newest `last_seen_at` first, parser per `source` (`PARSERS`), first that parses wins, per-listing `fetched_at` / `fetch_error`, `failed` only when every listing failed, `skipped` when every listing is 404/410; storing unchanged | `process_queue.py` `process_row`, `_fetch_and_parse`, `_mark_listing` | Implemented | unit tests, RUN-04, DB-14 |
| `copy_to_db.py`: both tables, bikes by norm identity, listings by `(source, pid)`, never downgrade | `copy_to_db.py` `read_source`, `upsert_row` | Implemented | unit tests |
| Migration script: listing per old row, norms filled, old columns + constraint dropped, new ones added; merge by best status; idempotent; `--dry-run`; target guard | `migrate_discovery_listings.py` | Implemented | unit tests (SQLite old layout + merge case), RUN-01, RUN-02 |
| Old layout refused by the other scripts (not requested, sensible guard) | `db.py` `has_old_layout`, `ensure_table`; `process_queue._table_exists`; `copy_to_db` | Extra | unit tests |
| Docs: `webscraper/centrumrowerowe/README.md`, "Bike discovery" in `README.md` / `CLAUDE.md` | docs | Implemented | review |

## Runs on local PostgreSQL

| ID | Step | Expected | Result |
|---|---|---|---|
| UNIT | `pytest webscraper/centrumrowerowe/tests` | green | Pass — 194 passed (re-run by QA: 194 passed, 28 s) |
| RUN-01 | `migrate_discovery_listings.py` (rehearsed on a PostgreSQL copy first, backup in database `biker_backup_037`) | 1310 listings, ≤ 1310 bikes, statuses and `bike_id` kept | Pass — old_rows=1310 bikes=1278 listings=1310 merged_groups=30 (men/women variants of one model name) bike_id_conflicts=0; 49 done / 1 skipped / 1228 pending, 50 `bike_id` kept |
| RUN-02 | migration again | "already migrated", nothing changed | Pass |
| RUN-03 | full `scrape_rowery.py` after the migration | 0 new bikes / listings, statuses untouched | Pass with a data note — products seen 1311, bikes inserted 7, listings inserted 7, listings updated 1304; the 7 are product ids new in the shop's catalogue since the TODO-036 scrape, not duplicates |
| RUN-04 | `process_queue.py --limit 5` | 5 done through the listing path | Pass — done=5 (Oxfeld WEE 12, Romet Wagant, Romet Wagant 0, Romet Wagant 1, GasGas TR1) |

## DB checks (read-only script)

| ID | Check | Result |
|---|---|---|
| DB-01 | `bike_discovery` has no shop columns, has `company_norm` / `model_norm` / `created_at` | Pass |
| DB-02 | `UNIQUE(company_norm, model_norm)`, old `UNIQUE(source, source_product_id)` gone from the bike table | Pass |
| DB-03 | `UNIQUE(source, source_product_id)` on the listing table | Pass |
| DB-04 | FKs `discovery_id → bike_discovery` CASCADE, `bike_id → bike` SET NULL | Pass |
| DB-05 | indexes `(status, next_attempt_at)`, `(discovery_id)`, `(source, last_seen_at)` | Pass |
| DB-06 | NOT NULL on the norms, `created_at`, `discovery_id`, `source`, `source_product_id`, `raw_name` | Pass |
| DB-07 | no listing without a bike | Pass — 1285 bikes, 1317 listings, 0 orphans |
| DB-08 | every bike has at least one listing | Pass |
| DB-09 | merged bikes hold 2–3 listings | Pass — 1255 × 1, 28 × 2, 2 × 3 (e.g. KROSS Trans 1.0 ← pd27813 + pd27808 "damski") |
| DB-10 | norms equal `strip().lower()` of company / model on every row | Pass |
| DB-11 | statuses 54 done / 1 skipped / 1230 pending, no in_progress / failed | Pass — 55 `bike_id` set |
| DB-12 | every listing `centrumrowerowe.pl`, no `?v_Id=` in `details_link` | Pass |
| DB-13 | no two discovery bikes linked to the same `bike` row | Pass |
| DB-14 | the 5 processed bikes: `done`, attempts 1, `bike_detail`, 8 photos, `/v1/bike/details` cache row, listing `fetched_at` set with no `fetch_error` | Pass (5 of 5) |

## Test cases (API + browser)

| ID | Case | Expected | Round 1 |
|---|---|---|---|
| TC-06 | `details-cache` + `POST /v1/bike/photos` for the 5 processed bikes | 200, description, ≥ 4 categories, 1–8 https photos | Pass (5 of 5) |
| TC-01 | `POST /v1/bike/search` brand `GasGas` | TR1 returned from the DB | Pass |
| TC-02 | search `Romet` + wheel `28"` | Wagant, Wagant 0, Wagant 1 returned from the DB | Pass |
| TC-03 | search `romet` + wheel `12"` | Wagant bikes not returned | Pass — no DB match, AI fallback answered 400 (credits), no Wagant |
| TC-10 | Browser: filters Marka `Romet`, Rozmiar kół `28"` | result cards incl. Wagant 0 / Wagant 1 | Pass |
| TC-10b | Browser: filter Marka `GasGas` | TR1 card | Pass |
| TC-11 | Browser: open GasGas TR1, description | Polish description shown | Pass |
| TC-12 | Browser: component tree | shop components shown (SR Suntour XCE28 …) | Pass |
| TC-13 | Browser: photos | photos render, read through `/v1/bike/photos` | Pass (9 loaded images) |
| TC-14 | Browser: `/v1/bike/details` and `/v1/bike/photos` | no failing call | Pass — only `/v1/bike/review` 400 (expected) |

**Result: 34 passed · 0 failed · 0 blocked** (UNIT, RUN-01 … RUN-04, DB-01 … DB-14 with DB-14 counted once,
TC-06 counted once, 10 API/browser cases).

## Observations (not defects of this task)

- `process_queue.py --source X` selects bikes with a listing from X but then tries **all** of the bike's
  listings, whatever their shop. Harmless with one shop; worth deciding before a second one.
- In a real run `--delay` applies between bikes, not between the listings of one bike (the dry run sleeps
  between every fetch). Only matters for merged bikes whose first listing fails.
- Pre-existing, not checked against the shop page: GasGas TR1 shows "Przerzutka przednia: Shimano Tourney
  RD-TY300, 3s" (a rear-derailleur model number under the front label — may be the shop's own data);
  `bike` holds both `GasGas` and `Gasgas` identities (casing).
