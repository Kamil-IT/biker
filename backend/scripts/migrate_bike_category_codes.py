"""TODO-047: rewrite bike.category to the eight codes of app/bike_categories.py and lock the list.

Run AFTER scripts/migrate_bike_category.py (the column must exist) and AFTER
webscraper/centrumrowerowe/reclassify_ebikes.py (it gives each 'Electric' bike its type):

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_bike_category_codes.py --dry-run
    python scripts/migrate_bike_category_codes.py
    python scripts/migrate_bike_category_codes.py --electric-to-null   # leftover 'Electric' -> NULL
    python scripts/migrate_bike_category_codes.py --db path/to/copy.db
    python scripts/migrate_bike_category_codes.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

How, in ONE transaction (PostgreSQL under `LOCK TABLE bike IN SHARE ROW EXCLUSIVE MODE`):
every old value -> its code (`LEGACY_CATEGORIES`: Triathlon -> Road, Dirt/Street -> MTB,
Cyclocross -> Gravel, City / Cross / Hybrid/Commuter / Cruiser -> City/Cross/Hybrid,
Trekking -> Touring, Youth / Balance -> Kids), then on PostgreSQL
`ALTER TABLE bike ADD CONSTRAINT ck_bike_category CHECK (category IS NULL OR category IN (...))`.
SQLite cannot add a CHECK to an existing table: there the values are rewritten and the
constraint is "skipped" (a database created by init_db() has it already).

Refused (nothing written, exit code 1): a value that is neither a code nor an old value,
and 'Electric' / 'Electric cargo' rows unless --electric-to-null (then they become NULL —
the e-bike stays recognisable as electric through its 'Electric / Powertrain' components).
Verified before commit: same bike ids, every row holds the code its old value maps to, every
value is a code, the constraint exists (PostgreSQL). Any mismatch rolls back.

Idempotent: every value a code and the constraint present -> "already-migrated". No `bike`
table -> "absent". Also importable:
`migrate(url_or_path=None, dry_run=False, electric_to_null=False, verbose=True) -> dict`.
"""
import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

from sqlalchemy import bindparam, create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

from app.bike_categories import (  # noqa: E402
    BIKE_CATEGORIES, ELECTRIC_LEGACY, LEGACY_CATEGORIES, category_check_sql,
)
from app.models import DEFAULT_DB_PATH  # noqa: E402

TABLE, COLUMN, CONSTRAINT = "bike", "category", "ck_bike_category"


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _constraint_present(conn, dialect: str) -> bool:
    if dialect == "postgresql":
        return conn.execute(text(
            "SELECT 1 FROM pg_constraint WHERE conname = :n AND conrelid = 'bike'::regclass"),
            {"n": CONSTRAINT}).first() is not None
    sql = conn.execute(text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'bike'")).scalar()
    return CONSTRAINT in (sql or "")


def _target(value: Optional[str]) -> Optional[str]:
    """The value a row ends with (only called for codes, old values, Electric and NULL)."""
    if value is None or value in ELECTRIC_LEGACY:
        return None
    return value if value in BIKE_CATEGORIES else LEGACY_CATEGORIES[value]


def _rows(conn) -> dict[int, Optional[str]]:
    return {r[0]: r[1] for r in conn.execute(text(f"SELECT id, {COLUMN} FROM {TABLE}"))}


def _check(rows: dict, electric_to_null: bool) -> Optional[str]:
    """Why the rows cannot be migrated, or None."""
    counts = Counter(v for v in rows.values() if v is not None)
    unknown = {v: n for v, n in counts.items()
               if v not in BIKE_CATEGORIES and v not in LEGACY_CATEGORIES and v not in ELECTRIC_LEGACY}
    if unknown:
        return f"unknown category values {unknown} — map them in app/bike_categories.py LEGACY_CATEGORIES first"
    electric = {v: counts[v] for v in ELECTRIC_LEGACY if counts[v]}
    if electric and not electric_to_null:
        return (f"{sum(electric.values())} bikes still {electric} — run "
                "webscraper/centrumrowerowe/reclassify_ebikes.py first, or pass --electric-to-null")
    return None


def migrate(url_or_path=None, dry_run: bool = False, electric_to_null: bool = False, verbose: bool = True) -> dict:
    """Migrate one database; returns a report dict.

    `status` is one of: "migrated", "dry-run", "already-migrated", "absent", "failed".
    """
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    engine = _engine(url)
    dialect = engine.dialect.name
    report = {
        "database": make_url(url).render_as_string(hide_password=True), "dialect": dialect,
        "status": "", "bikes": 0, "before": {}, "after": {}, "renamed": {}, "electric_to_null": 0,
        "constraint": "", "verified": False, "error": None,
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if not insp.has_table(TABLE):
            report["status"], report["verified"] = "absent", True
            say(f"{TABLE} does not exist — nothing to migrate; init_db() creates it with {CONSTRAINT}")
            return report
        if COLUMN not in {c["name"] for c in insp.get_columns(TABLE)}:
            raise RuntimeError(f"{TABLE} has no {COLUMN} column — run scripts/migrate_bike_category.py first")

        with engine.connect() as conn:
            rows = _rows(conn)
            present = _constraint_present(conn, dialect)
        report["bikes"] = len(rows)
        report["before"] = dict(Counter(rows.values()).most_common())
        say(f"before: {len(rows)} bikes {report['before']}")
        problem = _check(rows, electric_to_null)
        if problem:
            raise RuntimeError(problem)
        pending = {i: v for i, v in rows.items() if _target(v) != v}
        needs_constraint = dialect == "postgresql" and not present
        if not pending and not needs_constraint:
            report["status"], report["verified"] = "already-migrated", True
            report["after"] = report["before"]
            report["constraint"] = "present" if present else "skipped"
            say(f"every value is a code, {CONSTRAINT} {report['constraint']} — nothing to do")
            return report
        renamed = Counter(v for v in pending.values() if v not in ELECTRIC_LEGACY)
        report["renamed"] = {f"{old} -> {LEGACY_CATEGORIES[old]}": n for old, n in renamed.items()}
        report["electric_to_null"] = sum(1 for v in pending.values() if v in ELECTRIC_LEGACY)
        if dry_run:
            report["status"], report["verified"] = "dry-run", True
            report["after"] = dict(Counter(_target(v) for v in rows.values()).most_common())
            report["constraint"] = "would add" if needs_constraint else ("present" if present else "skipped")
            say(f"dry run: would rename {report['renamed']}, Electric -> NULL {report['electric_to_null']}, "
                f"constraint {report['constraint']} — nothing written\n  after: {report['after']}")
            return report

        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                if dialect == "postgresql":
                    conn.exec_driver_sql(f"LOCK TABLE {TABLE} IN SHARE ROW EXCLUSIVE MODE")
                rows = _rows(conn)  # again, under the lock
                problem = _check(rows, electric_to_null)
                if problem:
                    raise RuntimeError(problem)
                for old, new in LEGACY_CATEGORIES.items():
                    conn.execute(text(f"UPDATE {TABLE} SET {COLUMN} = :new WHERE {COLUMN} = :old"),
                                 {"new": new, "old": old})
                if electric_to_null:
                    conn.execute(
                        text(f"UPDATE {TABLE} SET {COLUMN} = NULL WHERE {COLUMN} IN :old")
                        .bindparams(bindparam("old", expanding=True)),
                        {"old": list(ELECTRIC_LEGACY)})
                if dialect == "postgresql" and not _constraint_present(conn, dialect):
                    conn.exec_driver_sql(
                        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CONSTRAINT} CHECK ({category_check_sql(COLUMN)})")
                    report["constraint"] = "added"
                else:
                    report["constraint"] = "present" if _constraint_present(conn, dialect) else "skipped"
                after = _rows(conn)
                bad = [i for i, v in rows.items() if after.get(i) != _target(v)]
                strays = {v for v in after.values() if v is not None and v not in BIKE_CATEGORIES}
                if set(after) != set(rows) or bad or strays or (
                        dialect == "postgresql" and not _constraint_present(conn, dialect)):
                    raise RuntimeError(
                        f"verification failed: {len(rows)} bikes before, {len(after)} after, "
                        f"{len(bad)} rows differ, stray values {sorted(strays)}")
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["after"] = dict(Counter(after.values()).most_common())
        report["status"], report["verified"] = "migrated", True
        say(f"after:  {report['after']}\n  renamed {report['renamed']}, Electric -> NULL "
            f"{report['electric_to_null']}, constraint {report['constraint']}")
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
    ap.add_argument("--electric-to-null", action="store_true",
                    help="set leftover 'Electric' / 'Electric cargo' rows to NULL instead of refusing")
    args = ap.parse_args()
    if args.db is not None and not args.db.exists():
        print(f"SQLite file not found: {args.db}")
        return 1
    report = migrate(args.db or args.url, dry_run=args.dry_run, electric_to_null=args.electric_to_null)
    print("\nRESULT:", report["status"])
    return 0 if report["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
