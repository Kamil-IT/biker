"""Add bike_detail_photos.bg_color (the photo's edge colour for the results tile).

`init_db()`'s create_all() never ALTERs an existing table, so every pre-existing
database needs this script once, BEFORE the new backend or searcher runs on it:
the new ORM selects and inserts `bike_detail_photos.bg_color` (a SELECT of the
missing column fails) and the searcher refuses to start without it. The OLD
backend and searcher keep working on a migrated database because the column is
nullable (NULL = not computed / transparent / unknown).

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_photo_bg_color.py --dry-run
    python scripts/migrate_photo_bg_color.py
    python scripts/migrate_photo_bg_color.py --db path/to/copy.db
    python scripts/migrate_photo_bg_color.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

How, in ONE transaction: `ALTER TABLE bike_detail_photos ADD COLUMN bg_color
VARCHAR(7)` (both dialects, only when the column is missing), the row count is
compared before and after (PostgreSQL under `LOCK TABLE ... SHARE ROW EXCLUSIVE`);
any mismatch rolls back (exit code 1). The existing rows get NULL - fill them
with scripts/backfill_photo_bg_color.py.

Idempotent: a present column = "already-migrated"; no `bike_detail_photos` table
= "absent" (init_db() creates it with the column). A table still keyed on
`bike_detail_id` is refused - run migrate_photos_bike_id.py first. Also
importable: `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`
(`status`, `rows_before`, `rows_after`, `verified`, `error`).

Exit code: 0 on success (or nothing to do), 1 on a failed run.
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

TABLE = "bike_detail_photos"
COLUMN = "bg_color"


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def migrate(url_or_path=None, dry_run: bool = False, verbose: bool = True) -> dict:
    """Migrate one database; returns a report dict.

    `status` is one of: "migrated", "dry-run", "already-migrated", "absent", "failed".
    """
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    engine = _engine(url)
    dialect = engine.dialect.name
    report = {
        "database": make_url(url).render_as_string(hide_password=True), "dialect": dialect,
        "status": "", "rows_before": 0, "rows_after": 0, "verified": False, "error": None,
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if not insp.has_table(TABLE):
            report["status"], report["verified"] = "absent", True
            say(f"{TABLE} does not exist - nothing to migrate; init_db() creates it with {COLUMN}")
            return report
        columns = {c["name"] for c in insp.get_columns(TABLE)}
        if "bike_id" not in columns:
            raise RuntimeError(f"{TABLE} is still keyed on bike_detail_id - run scripts/migrate_photos_bike_id.py first")
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
        report["rows_before"] = report["rows_after"] = count
        if COLUMN in columns:
            report["status"], report["verified"] = "already-migrated", True
            say(f"{TABLE}.{COLUMN} already exists - nothing to do ({count} rows)")
            return report
        if dry_run:
            report["status"], report["verified"] = "dry-run", True
            say(f"dry run: would add {TABLE}.{COLUMN} VARCHAR(7) NULL to {count} rows - nothing written")
            return report

        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                if dialect == "postgresql":
                    conn.exec_driver_sql(f"LOCK TABLE {TABLE} IN SHARE ROW EXCLUSIVE MODE")
                conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} VARCHAR(7)")
                after = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
                report["rows_after"] = after
                nulls = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE} WHERE {COLUMN} IS NULL")).scalar_one()
                if after != count or nulls != count:
                    raise RuntimeError(
                        f"verification failed: {count} rows before, {after} after, {nulls} with a NULL {COLUMN}")
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["status"], report["verified"] = "migrated", True
        say(f"after:  {TABLE}.{COLUMN} added, {after} rows kept (all NULL - run scripts/backfill_photo_bg_color.py)")
        return report
    except Exception as exc:  # noqa: BLE001 - reported, exit code 1
        report["status"], report["error"] = "failed", str(exc)
        say(f"FAILED - rolled back, database unchanged.\n  {exc}")
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
