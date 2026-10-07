"""Add equipment.part_type / groupset / key_specs (TODO-046, the parts catalogue).

`init_db()`'s create_all() never ALTERs an existing table, so every pre-existing
database needs this script once, BEFORE the new backend or searcher runs on it:
the new ORM selects the three columns on every equipment read (a SELECT of a
missing column fails) and the searcher refuses to start without them. The OLD
backend and searcher keep working on a migrated database because the columns are
nullable (NULL = unknown / not researched).

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_equipment_part_search.py --dry-run
    python scripts/migrate_equipment_part_search.py
    python scripts/migrate_equipment_part_search.py --db path/to/copy.db
    python scripts/migrate_equipment_part_search.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

How, in ONE transaction: `ALTER TABLE equipment ADD COLUMN part_type VARCHAR(32)`,
`groupset VARCHAR(128)` and `key_specs TEXT` (both dialects, only the columns that
are missing), then the row count is compared before and after and every added
column must read NULL on every row (PostgreSQL under `LOCK TABLE ... SHARE ROW
EXCLUSIVE`); any mismatch rolls back (exit code 1). No backfill: the columns are
filled by POST /v1/parts/search/ai.

Idempotent: all three columns present = "already-migrated"; no `equipment` table
= "absent" (init_db() creates it with the columns). A table still on the
pre-TODO-044 layout (no `name` column) is refused - run
migrate_merge_equipment_detail.py first. Also importable:
`migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`
(`status`, `rows_before`, `rows_after`, `added`, `verified`, `error`).

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

TABLE = "equipment"
COLUMNS = (("part_type", "VARCHAR(32)"), ("groupset", "VARCHAR(128)"), ("key_specs", "TEXT"))


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
        "status": "", "rows_before": 0, "rows_after": 0, "added": [], "verified": False, "error": None,
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if not insp.has_table(TABLE):
            report["status"], report["verified"] = "absent", True
            say(f"{TABLE} does not exist - nothing to migrate; init_db() creates it with the new columns")
            return report
        columns = {c["name"] for c in insp.get_columns(TABLE)}
        if "name" not in columns:
            raise RuntimeError(f"{TABLE} is still on the pre-TODO-044 layout (no name column) - "
                               "run scripts/migrate_merge_equipment_detail.py first")
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
        report["rows_before"] = report["rows_after"] = count
        missing = [(name, ddl) for name, ddl in COLUMNS if name not in columns]
        if not missing:
            report["status"], report["verified"] = "already-migrated", True
            say(f"{TABLE} already has part_type / groupset / key_specs - nothing to do ({count} rows)")
            return report
        names = ", ".join(name for name, _ in missing)
        if dry_run:
            report["status"], report["verified"] = "dry-run", True
            say(f"dry run: would add {TABLE}.{{{names}}} (NULL) to {count} rows - nothing written")
            return report

        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                if dialect == "postgresql":
                    conn.exec_driver_sql(f"LOCK TABLE {TABLE} IN SHARE ROW EXCLUSIVE MODE")
                for name, ddl in missing:
                    conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN {name} {ddl}")
                after = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
                report["rows_after"] = after
                for name, _ in missing:
                    nulls = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE} WHERE {name} IS NULL")).scalar_one()
                    if nulls != count:
                        raise RuntimeError(f"verification failed: {nulls} of {count} rows have a NULL {name}")
                if after != count:
                    raise RuntimeError(f"verification failed: {count} rows before, {after} after")
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["status"], report["added"], report["verified"] = "migrated", [n for n, _ in missing], True
        say(f"after:  {TABLE}.{{{names}}} added, {after} rows kept (all NULL)")
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
