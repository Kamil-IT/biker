# TODO-028 — Test plan, round 1: SQLite → PostgreSQL data copy

**Test item:** `backend/scripts/copy_sqlite_to_postgres.py` (+ `endpoint_req_to_body_cache` Core table in `app/models.py`)
**Branch:** `feature/028-sqlite-to-postgres`
**Test basis:** `backlog/TODO_028_MIGRATE_SQLITE_TO_POSTGRES.md` — Scope bullet "New `copy_sqlite_to_postgres.py`" and
acceptance criterion "copies the current `cache.db`; row counts match per table".
**Out of scope this round:** backend running on Postgres (`DATABASE_URL` in `models.py`/`cache.py`/`store.py`/`repository.py`),
`test_search.py`, the UI. Those are later rounds.

## Traceability

| Req | Requirement | Implemented | Status |
|---|---|---|---|
| R1 | Schema on fresh Postgres from `create_all()` | `copy_sqlite_to_postgres.py` `main` → `Base.metadata.create_all(dst)`; cache table added to `models.py` | Implemented |
| R2 | Copies every table, FK order | `source_rows` / `copy_tables` iterate `Base.metadata.sorted_tables` | Implemented |
| R3 | Resets sequences (`setval`) | `reset_sequences` | Implemented |
| R4 | Refuses a non-empty target unless `--truncate` | `main` → `non_empty` check | Implemented |
| R5 | Prints row counts per table, source vs target | `verify` | Implemented |
| R6 | Data preserved (not dropped) | row insert + sha256 content check | Implemented |
| X1 | Orphan rows skipped and reported | `source_rows` | **Extra** — agreed with the user: 2 rows in `search_bike_rating_cache` point at deleted `search_cache` ids 156, 159 |
| X2 | Source opened read-only; single transaction; `--verify-only`; schema-drift guard | `sqlite_engine`, `main`, `check_schema` | Extra (safety) |

## Environment & data
- PostgreSQL 17.11 in Docker `biker-pg`, `postgresql+psycopg://biker:biker@localhost:5432/biker`; checked via `docker exec biker-pg psql`.
- Source: the worktree's `backend/cache.db` (committed snapshot). Oracle = SQLite queried directly with Python `sqlite3`, **not** the
  script's own verify.

## Test cases

| ID | Req | Pri | Condition / steps | Expected |
|---|---|---|---|---|
| TC01 | R2,R5 | P1 | `SELECT count(*)` per table in psql vs `sqlite3` count | Every table equal; `search_bike_rating_cache` = 201 − 2 = 199 |
| TC02 | R1 | P1 | `\dt` in psql | 10 tables = SQLite tables minus `sqlite_sequence` |
| TC03 | R1 | P1 | PK / FK (with `ON DELETE CASCADE`) / UNIQUE constraints from `information_schema` / `pg_constraint` vs SQLite DDL | Same set; `uq_bike_brand_model`, `uq_missing_bike_type`, `uq_offer_bike_url`, cache `UNIQUE(endpoint, request)` present |
| TC04 | R1 | P2 | Indexes (`pg_indexes`) vs SQLite `sqlite_master` indexes | Every SQLite index column covered (names may differ) |
| TC05 | R6 | P1 | Full independent row-by-row compare of every table (Python: sqlite3 vs psycopg, keyed by PK / unique key) | 0 differing rows, 0 missing, 0 extra (except the 2 orphans) |
| TC06 | R6 | P1 | Non-ASCII: rows containing chars > U+007F (e.g. `ü`, `ł`, `–`, `�`) byte-equal | Equal; counts of non-ASCII rows equal per table |
| TC07 | R6 | P2 | Datetime columns (`bike.created_at`, `bike_detail.updated_at`) — same instant; `search_cache.time_stored` text unchanged | Equal to the microsecond |
| TC08 | R6 | P2 | Float `search_bike_rating_cache.rating` and JSON-in-text `accessories` / `description` / cache `response` | Floats equal; JSON parses on both sides and is identical |
| TC09 | R6 | P2 | NULLs: `spec_key`/`spec_value`/`spec_order` NULL counts in `bike_detail_component` | Same NULL count |
| TC10 | R3 | P1 | Each serial sequence `last_value` ≥ MAX(id); `INSERT` of a new `bike` without id in a rolled-back transaction | New id = MAX(id)+1, no duplicate-key error |
| TC11 | R4 | P1 | Run script again with no flag on the filled target | Exit 1, message "Target is not empty … --truncate", counts unchanged |
| TC12 | R4 | P1 | Run with `--truncate` | Exit 0, all OK, counts identical to TC01 (no doubling) |
| TC13 | R5 | P2 | `--verify-only` | Exit 0, table printed, nothing written |
| TC14 | X1 | P2 | Orphan ids reported in output = SQLite `PRAGMA foreign_key_check` result | Exactly ids 156, 159; 2 rows |
| TC15 | X2 | P2 | Source unchanged: sha256 of `cache.db` before/after a run | Identical |
| TC16 | neg | P3 | `--target sqlite:///x.db`, unset target, `--source missing.db` | Exit 1 with a clear message, nothing written |
| TC17 | X2 | P3 | Atomicity: copy that fails mid-way (target with a conflicting pre-existing row + `--truncate` not used is TC11; here force a failure by injecting an over-long value into a scratch SQLite copy) | Exit ≠ 0, target left exactly as before |

**Entry criteria:** container healthy (`pg_isready`), script ran once successfully. **Exit criteria:** all P1/P2 pass; any P3
failure reported to the user.

## Results

Executed 2026-09-24 against `backend/cache.db` → `biker-pg` (PostgreSQL 17.11). Oracle: raw `sqlite3` + raw `psycopg`
(scratchpad checker, no script code) and `psql` in the container.

**Round 1:** 16 passed · 1 failed (TC05) · 0 blocked. TC17 passed on data but crashed with a raw traceback → fixed
(`SQLAlchemyError` caught, one-line "Copy FAILED — rolled back, target unchanged").
**Round 2** (TC17 + regression TC01–TC14): 16 passed · 1 open (TC05, awaiting decision).

| ID | Result | Evidence |
|---|---|---|
| TC01 | Pass | all 10 tables equal; `search_bike_rating_cache` 201 → 199; 37 827 rows in total |
| TC02 | Pass | same 10 tables |
| TC03 | Pass | 9 PK, 7 FK all `ON DELETE CASCADE`, UNIQUE `(brand, model)`, `(bike_id, missing_type)`, `(bike_id, url)`, `(endpoint, request)` |
| TC04 | Pass | every SQLite index column indexed (names follow the model, e.g. `ix_bike_brand` instead of `ix_bikes_brand`) |
| TC05 | **Open** | 0 missing / 0 extra / 0 differing rows in 8 tables. 127 rows (`bike` 120, `bike_detail` 7) hold 254 SQLite timestamps written *with* `+00:00`; Postgres `timestamp` stores them without the offset. Instant identical in all 254 (0 mismatches after UTC conversion); the app already reads naive as UTC (`repository.py:197`) |
| TC06 | Pass | non-ASCII rows equal per table (e.g. 452 component rows, 135 cache rows) |
| TC07 | Pass | datetimes equal to the microsecond; `time_stored` text unchanged |
| TC08 | Pass | 199 floats equal; JSON in `accessories`, `description`, cache `response` identical after parsing |
| TC09 | Pass | 3 347 NULL spec rows on both sides |
| TC10 | Pass | every sequence at MAX(id)+1; probe insert got 671 after max 670, rolled back |
| TC11 | Pass | exit 1, "Target is not empty … --truncate" |
| TC12 | Pass | exit 0, 10 × OK, no doubling |
| TC13 | Pass | exit 0, nothing copied |
| TC14 | Pass | orphans = `search_cache_id` 156, 159 (rating rows 210, 221), same as `PRAGMA foreign_key_check` |
| TC15 | Pass | `cache.db` sha256 unchanged |
| TC16 | Pass | `sqlite:///` target, empty target, missing source → exit 1 with a message, no file created |
| TC17 | Pass (round 2) | text in an INTEGER column fails mid-copy → exit 1, clean message, Postgres row counts identical before/after |

---

# Round 2 — whole app on PostgreSQL (UI + API), cached cases only

**Change set:** `app/models.py` (engine from `DATABASE_URL`, `configure_db`, `dialect_insert`, SQLite pragmas),
`app/cache.py` (no `sqlite3`; Core table + shared engine), `app/store.py` (ORM sessions), `app/repository.py`
(dialect upsert), `app/main.py` (startup order), `scripts/test_search.py` (DB helpers over the engine),
`frontend/vite.config.ts` (`BIKER_API_URL` proxy override).
**Setup:** frontend `:5174` → backend `:8001` (`DATABASE_URL` = `biker-pg`); a second backend `:8002` on a scratch copy
of `cache.db` (`DATABASE_URL=sqlite:///…`) as the SQLite reference. Only requests already in the cache were used.
**AI calls in both backend logs: 0.**

| ID | Case | Result | Evidence |
|---|---|---|---|
| UI01 | Home page loads | Pass | `ui01_home.png` |
| UI02 | Type "romet wagant 3" → parse (cached) fills Filters, no search yet | Pass | parse 200; Marka `ROMET`, Model `Wagant 3` |
| UI03 | Second submit → search from Postgres | Pass | search 200 in 0.2 s; `search_cache store` written to PG |
| UI04 | Open Romet Wagant 3 → all 6 detail requests | Pass | details/review/offer/ceneo/decathlon/used all 200 (cache hits); `bike_details stored` to PG |
| UI05 | Details page content | Pass (oracle corrected, parity) | Overview, Used + New offers (OLX 700 zł; Allegro/Decathlon/Ceneo), review 7/10 + 4 sources, full component tree. 0 photos + one "Poproś o dane" button: the cached response itself has `photos: []`, identical in `cache.db` — correct TODO-027 behaviour, not a regression |
| UI06 | Back to results | Pass | |
| UI07 | No console errors | Pass (pre-existing warning) | React duplicate key `Romet-Wagant 3`: the cached search response holds Wagant 3 four times, byte-identical in SQLite → known `TODO_ISSUE_015_DUPLICATE_SEARCH_RESULTS`, not TODO-028 |
| UI08 | No failing `/v1` response | Pass | |
| API01 | `/v1/bike/missing` on PG, twice | Pass | counter 1 → 2, one row; probe row deleted afterwards |
| API02 | `/missing` unknown bike | Pass | `{bike_id: null, counter: 0}`, nothing written |
| API03 | `GET search-cache?brand=romet` | Pass | 200, 3 bikes |
| API04 | `GET details-cache` exact casing / other casing | Pass (parity) | 200 exact; 404 for `ROMET`/`wagant 3` on **both** DBs — `get_bike_details` matches brand/model exactly (pre-existing; CLAUDE.md's "casing does not matter" is out of date) |
| API05 | `search-cache` unknown query | Pass | 404 |
| API06 | `/missing` upsert in SQLite mode | Pass | counter 1 → 2, one row |
| DB01 | FK consistency after hit-path rewrites | Pass | 0 orphan components / ratings, 1 detail row for Romet Wagant 3 |
| PAR | Same 14 requests to PG and SQLite backends | Pass | 14/14 identical status + body |

**Not run (cost guard):** full `scripts/test_search.py` — its AI-fallback cases call Anthropic on purpose. Its DB helpers
now run over the engine on either database.
**Open:** `scripts/test_e2e_ui_db.py` still opens `cache.db` with `sqlite3` (backup + destructive delete) — SQLite-only.
