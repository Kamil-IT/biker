"""Drop search_cache + search_bike_rating_cache — the write-only per-search tables (TODO-043).

Nothing has read them since the cache-read endpoints went (TODO-024/025) and
since TODO-041 their payload columns were written as "" / "[]". The new
backend's `store.save_search` only makes sure the found bikes exist in `bike`,
so the tables can go. `init_db()`'s create_all() never DROPs, so every
pre-existing database needs this script once.

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_drop_search_tables.py --dry-run
    python scripts/migrate_drop_search_tables.py
    python scripts/migrate_drop_search_tables.py --db path/to/copy.db
    python scripts/migrate_drop_search_tables.py --url postgresql+psycopg://biker@127.0.0.1:6543/biker

How: `DROP TABLE search_bike_rating_cache` (the child — it FKs to
search_cache and bike) then `DROP TABLE search_cache`, ONE transaction on both
dialects (PostgreSQL DDL is transactional; pysqlite runs under BEGIN IMMEDIATE
with autocommit handed over). The `bike` table is counted before and after and
any change rolls the drop back — the FK is the only link, and dropping the
child never cascades into the parent, so the count must be identical.

Deploy order: the OLD backend keeps writing both tables, so on a database where
they are already gone its `save_search` fails (rollback + WARNING, the search
answer is still returned, nothing stored is lost). The NEW backend never touches
the tables, so it runs fine on an unmigrated database (they just sit there until
this script runs). Production order therefore: (1) deploy the new backend,
(2) run this on Cloud SQL — no window in which anything fails.

Idempotent: neither table present = "already-migrated". One of them present
(a half-dropped database) is still migrated. Also importable:
`migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`.

Exit code: 0 on success (or nothing to do), 1 on a failed verification/run.
"""
import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

from app.models import DEFAULT_DB_PATH  # noqa: E402

# Child first: search_bike_rating_cache FKs to search_cache (and to bike).
TABLES = ("search_bike_rating_cache", "search_cache")
GUARD = "bike"


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below —
    # pysqlite otherwise commits implicitly around DDL, which would break atomicity.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def migrate(url_or_path=None, dry_run: bool = False, verbose: bool = True) -> dict:
    """Migrate one database; returns a report dict.

    `status` is one of: "migrated", "dry-run", "already-migrated", "failed".
    `dropped` maps each table removed (or that would be, on a dry run) to its
    row count; `bikes_before` / `bikes_after` are the `bike` row counts.
    """
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    engine = _engine(url)
    dialect = engine.dialect.name
    report = {
        "database": make_url(url).render_as_string(hide_password=True), "dialect": dialect,
        "status": "", "dropped": {}, "bikes_before": 0, "bikes_after": 0, "verified": False, "error": None,
    }
    say(f"database: {report['database']}")
    try:
        existing = set(inspect(engine).get_table_names())
        present = [t for t in TABLES if t in existing]
        if not present:
            report["status"], report["verified"] = "already-migrated", True
            say(f"{' / '.join(TABLES)} already gone — nothing to do")
            return report
        if GUARD not in existing:
            raise RuntimeError(f"table {GUARD} is missing — this is not a biker database")

        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                report["bikes_before"] = _count(conn, GUARD)
                report["dropped"] = {t: _count(conn, t) for t in present}
                say(f"before: {GUARD}={report['bikes_before']} rows; "
                    + ", ".join(f"{t}={n} rows" for t, n in report["dropped"].items()))

                if dry_run:
                    conn.exec_driver_sql("ROLLBACK")
                    report["status"], report["bikes_after"], report["verified"] = (
                        "dry-run", report["bikes_before"], True)
                    say(f"dry run: would DROP TABLE {', '.join(present)} — nothing written")
                    return report

                for t in present:
                    conn.exec_driver_sql(f"DROP TABLE {t}")
                report["bikes_after"] = _count(conn, GUARD)
                left = set(inspect(conn).get_table_names()) & set(TABLES)
                if report["bikes_after"] != report["bikes_before"] or left:
                    raise RuntimeError(
                        f"verification failed: {GUARD} rows {report['bikes_before']} -> {report['bikes_after']}, "
                        f"tables still present: {sorted(left)}")
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["status"], report["verified"] = "migrated", True
        say(f"after:  dropped {', '.join(present)}; {GUARD} still {report['bikes_after']} rows")
        return report
    except Exception as exc:  # noqa: BLE001 — reported, exit code 1
        report["status"], report["error"] = "failed", str(exc)
        say(f"FAILED — rolled back, database unchanged.\n  {exc}")
        return report
    finally:
        engine.dispose()


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = ap.add_mutually_exclusive_group()
    target.add_argument("--db", type=Path, help="SQLite file to migrate")
    target.add_argument("--url", help="SQLAlchemy URL (default: $DATABASE_URL, else backend/cache.db)")
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()
    if args.db is not None and not args.db.exists():
        print(f"SQLite file not found: {args.db}")
        return 1
    report = migrate(args.db or args.url, dry_run=args.dry_run)
    print("\nRESULT:", report["status"])
    return 0 if report["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
