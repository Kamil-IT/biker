# TODO-019 — Migrate Bike Details from Blob Cache to the ORM Tables

## Goal
Replace the JSON-blob `bike_details_cache` table with the normalised ORM tables
`bike_details` + `bike_detail_photos` (+ shared `bikes` identity), backfill the existing rows,
and **prove by assertion** that the ORM read path returns a byte-identical
`BikeDetailsResponse` to the blob read path before the old table is dropped.

Scope is **details only**. `search_cache` stays exactly as it is — see *Out of scope*.

## Current state

Two generations of persistence coexist in `backend/cache.db`:

| Layer | Tables | Written by | Live? |
|---|---|---|---|
| Blob (raw SQL) | `bike_details_cache` | `app/store.py` | **Yes** — 9 rows, read/written by `POST /v1/bike/details` and `GET /v1/bike/details-cache` |
| ORM (SQLAlchemy) | `bikes`, `bike_details`, `bike_detail_photos` | `app/repository.py` | **No** — `bike_details` and `bike_detail_photos` are empty |

`app/main.py` calls `init_db()` at startup (so the ORM tables exist) but imports its
details helpers from `app/store.py`. `app/repository.py` is imported only by
`scripts/test_db_models.py`. The migration described in `app/DB_MIGRATION.md` was never done.

The ORM shape is strictly better: photos are rows with `display_order` instead of a JSON array,
and details share the `bikes` identity row with offers and search results.

## Behaviour after this task
- `POST /v1/bike/details` writes via `repository.save_bike_details`, reads via `repository.get_bike_details`.
- `GET /v1/bike/details-cache` reads via `repository.get_bike_details`.
- The 9 existing blob rows are present in the new tables with their original age preserved.
- `bike_details_cache` is dropped; `save_bike_details` / `get_bike_details` are removed from `app/store.py`.
- Response payload is unchanged — this is a storage-layer swap, invisible to the frontend.

## Known behavioural differences to reconcile

These are real divergences between `store.py` and `repository.py`, not hypotheticals. Each must be
closed **before** the cutover, and each is a parity assertion:

1. **Key normalisation.** `store.save_bike_details` / `get_bike_details` key on `_norm(company)` /
   `_norm(model)` (`store.py:72` — strip + lowercase) but return the **caller's** original casing in
   the response. `repository.py:155-158` and `:201-204` use `filter_by(brand=company, model=model)`
   — exact, case-sensitive — and return `bike.brand` / `bike.model` as stored. Consequence today:
   a request for `"Trek"` / `"Marlin 5"` hits the blob cache but would **miss** the ORM.
   Decide and implement one of: normalise on write + lookup in `repository`, or add a normalised
   lookup column. Response must keep echoing the caller's casing.
2. **Case-split identity in `bikes`.** SQLite `UNIQUE(brand, model)` is case-sensitive, and `bikes`
   already holds title-case test rows (`Trek`/`Marlin 5`, `Canyon`/`Grizl CF 7`, `Canyon`/`Grizl`)
   while every blob row is lowercase (`trek`/`marlin 5`). A naive backfill creates **two** bike
   identities for the same bike. Resolve as part of (1); the 6 `bike_results` + 8 `accessories`
   rows attached to those `bikes` rows are test-script leftovers (one explanation literally reads
   `[UPDATED IN DB] Best value mountain bike!`) and can be deleted.
3. **TTL source.** Blob computes freshness from `time_stored + ttl` (`store.py:66`). ORM computes it
   from `updated_at + ttl_seconds` (`repository.py:217-221`), and `updated_at` carries
   `onupdate=now`, so re-saving an unchanged row silently refreshes its TTL. Confirm that's intended
   (it matches the blob's upsert, which also rewrites `time_stored`) and make the backfill set
   `updated_at` from the blob's `time_stored` so migrated rows keep their real age.
4. **Empty photos.** `specialized`/`allez sprint` has `photos = "[]"`. Zero `bike_detail_photos` rows
   must deserialise back to `photos: []`, never `None`.
5. **Non-ASCII keys.** `riese & müller`/`nevo4 gt` must survive the backfill and round-trip intact.

## Scope

### Backend
- `app/repository.py` — fix key normalisation (item 1); keep the existing
  `save_bike_details` / `get_bike_details` signatures so `main.py` swaps by import only.
- `app/main.py` — import the two details helpers from `.repository` instead of `.store`.
- `scripts/migrate_bike_details.py` (new, one-off) — copy all `bike_details_cache` rows into
  `bikes` + `bike_details` + `bike_detail_photos`, preserving `time_stored` → `updated_at`,
  `ttl` → `ttl_seconds`, and photo array index → `display_order`. Idempotent (safe to re-run).
  Clean up the case-split `bikes` duplicates and the test-script `bike_results` / `accessories` rows.
- `app/store.py` — remove `save_bike_details`, `get_bike_details`, and the
  `bike_details_cache` DDL + index from `init_store()`. Leave everything search-related untouched.
- `DROP TABLE bike_details_cache` — after the parity test passes, in the migration script.
- `app/DB_MIGRATION.md` — mark the details half done; note search is still pending.
- `backend/README.md` — update the `/v1/bike/details` and `/v1/bike/details-cache` cache notes.
- `CLAUDE.md` — update the `app/store.py` and `app/repository.py` rows in the backend layer table.

### Parity assertion (the point of this task)
- `scripts/test_details_parity.py` (new pytest) — for each of the 9 known `(company, model)` pairs,
  read the same bike through the blob path and the ORM path and assert the two
  `BikeDetailsResponse` objects are equal **field for field**:
  - `company`, `model` — including the caller-casing echo (item 1)
  - `description` — full `BikeDescription` equality, not just text
  - `components` — full tree equality including nested `SpecItem` ordering
  - `photos` — same URLs **in the same order** (item 4)
  - a stale row (`time_stored` forced past `ttl`) returns `None` from both paths
  Run against a **copy** of `cache.db` in the scratchpad so the test can force staleness without
  touching real data. This test is deleted together with the blob path once green — it exists to
  gate the cutover.
- `scripts/test_search.py` — add the endpoint-level smoke test required by CLAUDE.md:
  `POST /v1/bike/details` twice for the same bike, assert HTTP 200 both times and byte-identical
  JSON on the second (cache-hit) call.

### Frontend
None. Payload shape is unchanged.

## Out of scope
- **`search_cache` → `bike_results`.** `BikeResult` has no `query` column, and
  `repository.get_search_by_query` (`repository.py:70-72`) has an **empty `.filter()`** — it returns
  every row in the table regardless of query. Migrating search needs a schema change and a real fix;
  it is its own task.
- **TODO-009's DB-first search branch.** `find_bike_by_brand_model` and `find_offer_prices` stay in
  `store.py` and keep reading the raw `cache` table. `find_offer_prices` has no ORM equivalent
  (`bike_offers` is empty and nothing populates it).
- **TODO-017.** That task changes the details *payload* shape; this one changes only where it is
  stored. If TODO-017 lands first, the parity test asserts the new shape instead — no conflict.
- Redundant-index cleanup on `search_cache` (`UNIQUE(query)` + `idx_search_cache_query`).

## Acceptance criteria
- [ ] `repository.get_bike_details` hits for `"Trek"`/`"Marlin 5"` and `"trek"`/`"marlin 5"` alike,
      and echoes back the caller's casing.
- [ ] `scripts/migrate_bike_details.py` moves all 9 rows; re-running it changes nothing.
- [ ] `bike_details` has 9 rows, `bike_detail_photos` has the photo rows in original order, and
      `specialized`/`allez sprint` reads back `photos: []`.
- [ ] `scripts/test_details_parity.py` passes for all 9 bikes plus the staleness case.
- [ ] `main.py` imports details helpers from `.repository`; `store.py` no longer defines them.
- [ ] `bike_details_cache` is dropped and no code references it.
- [ ] `scripts/test_search.py` details smoke test returns HTTP 200 twice with identical JSON.
- [ ] `backend/README.md`, `CLAUDE.md`, `app/DB_MIGRATION.md` updated.
