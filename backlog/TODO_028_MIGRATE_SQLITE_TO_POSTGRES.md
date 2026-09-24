# TODO-028 — Backend: move the database from SQLite to PostgreSQL

**Notion:** [14. Przenieś bazę z SQLite na PostgreSQL](https://app.notion.com/p/3e5bd10a98bf8167a58cc4d73311b5d5) — tick **Zrobione** there once the PR is merged

## Goal
The backend runs against SQLite (`backend/cache.db`). Cloud Run has an ephemeral filesystem, so production needs
PostgreSQL (Cloud SQL, TODO-030). The code must work against Postgres, selected by one environment variable, and the data
already in `cache.db` must be copied over — it was paid for with Anthropic tokens.

First of three deployment tasks: TODO-028 (Postgres) → TODO-029 (Docker) → TODO-030 (GCP deploy).

## Decisions (agreed 2026-09-24)
1. **`DATABASE_URL`** env var selects the database (SQLAlchemy URL, e.g.
   `postgresql+psycopg://biker:biker@localhost:5432/biker`). When unset, fall back to the current SQLite file so local
   dev, `test_details_parity.py` and `migrate_bike_details.py` keep working.
2. **One access path**: everything goes through the SQLAlchemy engine in `models.py`. No raw `sqlite3` connection left.
3. **Existing data is migrated**, not dropped. There is a one-off copy script from `cache.db` to Postgres.
4. **Schema** on a fresh Postgres comes from `init_db()` / `create_all()`. Alembic is out of scope.

## Scope
**Backend**
- `backend/app/models.py`: build the engine from `DATABASE_URL` (fallback `sqlite:///{DEFAULT_DB_PATH}`); `configure_db()`
  accepts a URL as well as a path. Pool settings suitable for Postgres (`pool_pre_ping=True`).
- `backend/app/cache.py`: replace the raw `sqlite3.connect` + `PRAGMA`s with the shared engine. The `cache` table becomes
  an ORM model or a Core table. `get_cached`/`set_cached` keep their signatures.
- `backend/app/store.py`: the 3 `get_conn()` call sites move to the engine/session.
- `backend/app/repository.py:533`: the upsert in `record_missing_request` uses `sqlalchemy.dialects.sqlite.insert`.
  Pick the dialect insert from `engine.dialect.name` (`postgresql` / `sqlite`); both support `on_conflict_do_update`.
- Check other SQLite-only behaviour: `PRAGMA foreign_keys` (Postgres enforces FKs anyway), `ON DELETE CASCADE`,
  datetime/TTL arithmetic, `UNIQUE` + upsert, text vs JSON columns, case-sensitive comparisons (`brand_norm` is
  normalised in Python, so no change expected).
- `backend/requirements.txt`: add `psycopg[binary]`.
- `backend/.env.example`: document `DATABASE_URL`.
- New `backend/scripts/copy_sqlite_to_postgres.py`: reads every table from `cache.db` and inserts it into the
  `DATABASE_URL` database in FK order, then resets the Postgres sequences (`setval`). Idempotent: refuses to run on a
  non-empty target unless `--truncate` is passed. Prints row counts per table, source vs target.
- Local Postgres for development: a one-line `docker run postgres:17` in `backend/README.md` (the full compose file is
  TODO-029).

**Docs**: `backend/README.md` (setup, `DATABASE_URL`, copy script), `backend/app/DB_MIGRATION.md`, `README.md`,
`CLAUDE.md` (Backend Setup, architecture table rows for `cache.py` / `models.py` / `repository.py`).

## Out of scope
- Dockerfile / docker-compose (TODO-029)
- Cloud SQL, Cloud Run and any GCP work (TODO-030)
- Alembic migrations
- Elasticsearch

## Acceptance criteria
- [ ] With `DATABASE_URL` pointing at a local Postgres, the backend starts, creates all tables, and every endpoint
      in `scripts/test_search.py` passes.
- [ ] Without `DATABASE_URL` the backend still runs on `cache.db` exactly as before.
- [ ] No `import sqlite3` / `sqlite:///` string left outside the SQLite fallback and the copy script.
- [ ] `POST /v1/bike/missing` upsert works on both databases (counter 1 → 2, one row).
- [ ] `copy_sqlite_to_postgres.py` copies the current `cache.db`; row counts match per table; a repeat search for a
      cached query is served from Postgres with no AI call.
- [ ] `test_details_parity.py` still passes.
- [ ] Docs updated (see Scope).
- [ ] After the PR is merged to `main`: tick **Zrobione** on the Notion task [14. Przenieś bazę z SQLite na PostgreSQL](https://app.notion.com/p/3e5bd10a98bf8167a58cc4d73311b5d5).
