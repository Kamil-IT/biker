"""Add bike.category (VARCHAR(32), nullable, no default; NULL = unknown) and backfill it.

`init_db()`'s create_all() never ALTERs an existing table, so every pre-existing
database needs this script once, BEFORE the new backend or searcher runs on it:
the new ORM selects and inserts `bike.category` and the searcher refuses to start
without it. The OLD backend keeps working on a migrated database (nullable column).

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_bike_category.py --dry-run
    python scripts/migrate_bike_category.py
    python scripts/migrate_bike_category.py --db path/to/copy.db
    python scripts/migrate_bike_category.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

How, in ONE transaction: `ALTER TABLE bike ADD COLUMN category VARCHAR(32)` (both
dialects), then a backfill: every bike linked from a `bike_discovery` row
(`bike_discovery.bike_id = bike.id`) with a non-empty `bike_type` gets
`category_from_discovery(bike_type)` (Polish shop type -> English category, lookup
`strip().lower()` in Python); only where `category IS NULL`. Unmapped types are
reported and leave the bike NULL. No `bike_discovery` table = no backfill. Verified
before commit: same bike ids, every planned value reads back. Any mismatch rolls
back (exit code 1). PostgreSQL runs under `LOCK TABLE bike IN SHARE ROW EXCLUSIVE MODE`.

Idempotent: a present column = only the backfill of still-NULL rows runs
("already-migrated" when it fills nothing, "backfilled" when it fills some). No `bike`
table = "absent". Also importable:
`migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`.

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

TABLE = "bike"
COLUMN = "category"

_FALLBACK_MAP = {
    "mtb": "MTB", "gravel": "Gravel", "szosowy": "Road", "przełajowy": "Cyclocross",
    "trekkingowy": "Trekking", "crossowy": "Cross", "miejski": "City", "dziecięcy": "Kids",
    "młodzieżowy": "Youth", "biegowy": "Balance", "jeździk dziecięcy": "Balance",
    "triathlonowy": "Triathlon", "składak": "Folding", "bmx": "BMX", "elektryczny": "Electric",
    "elektryczny cargo": "Electric cargo",
}
try:
    from app.bike_categories import category_from_discovery  # noqa: E402
except ImportError:  # backend module not available: same mapping, local copy
    def category_from_discovery(bike_type):
        return _FALLBACK_MAP.get((bike_type or "").strip().lower())


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _plan(conn, has_col: bool) -> tuple[dict[int, str], dict[str, int]]:
    """(bike_id -> category) for bikes to fill, and unmapped discovery types with their row counts."""
    fill: dict[int, str] = {}
    unmapped: dict[str, int] = {}
    where = f"AND b.{COLUMN} IS NULL" if has_col else ""
    rows = conn.execute(text(
        "SELECT d.bike_id, d.bike_type FROM bike_discovery d JOIN bike b ON b.id = d.bike_id "
        f"WHERE d.bike_id IS NOT NULL AND d.bike_type IS NOT NULL AND TRIM(d.bike_type) <> '' {where} "
        "ORDER BY d.id")).fetchall()
    for bike_id, bike_type in rows:
        if bike_id in fill:
            continue
        cat = category_from_discovery(bike_type)
        if cat:
            fill[bike_id] = cat
        else:
            key = bike_type.strip()
            unmapped[key] = unmapped.get(key, 0) + 1
    return fill, unmapped


def migrate(url_or_path=None, dry_run: bool = False, verbose: bool = True) -> dict:
    """Migrate one database; returns a report dict.

    `status` is one of: "migrated", "backfilled", "dry-run", "already-migrated", "absent", "failed".
    """
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    engine = _engine(url)
    dialect = engine.dialect.name
    report = {
        "database": make_url(url).render_as_string(hide_password=True), "dialect": dialect,
        "status": "", "bikes_before": 0, "bikes_after": 0, "filled": 0, "unmapped": {},
        "verified": False, "error": None,
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if not insp.has_table(TABLE):
            report["status"], report["verified"] = "absent", True
            say(f"{TABLE} does not exist — nothing to migrate; init_db() creates it with {COLUMN}")
            return report
        has_column = COLUMN in {c["name"] for c in insp.get_columns(TABLE)}
        has_disc = insp.has_table("bike_discovery")
        with engine.connect() as conn:
            ids_before = {r[0] for r in conn.execute(text(f"SELECT id FROM {TABLE}"))}
            fill, unmapped = _plan(conn, has_column) if has_disc else ({}, {})
        count = len(ids_before)
        report["bikes_before"] = report["bikes_after"] = count
        report["unmapped"] = unmapped
        if unmapped:
            say(f"unmapped discovery types (bike stays NULL): {unmapped}")
        if has_column and not fill:
            report["status"], report["verified"] = "already-migrated", True
            say(f"{TABLE}.{COLUMN} exists and nothing to backfill ({count} bikes)")
            return report
        if dry_run:
            report["status"], report["verified"] = "dry-run", True
            report["filled"] = len(fill)
            prefix = "" if has_column else f"add {TABLE}.{COLUMN} and "
            say(f"dry run: would {prefix}fill {len(fill)} of {count} bikes — nothing written")
            return report

        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                if dialect == "postgresql":
                    conn.exec_driver_sql(f"LOCK TABLE {TABLE} IN SHARE ROW EXCLUSIVE MODE")
                if not has_column:
                    conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} VARCHAR(32)")
                if fill:
                    conn.execute(
                        text(f"UPDATE {TABLE} SET {COLUMN} = :c WHERE id = :id AND {COLUMN} IS NULL"),
                        [{"id": i, "c": c} for i, c in fill.items()])
                ids_after = {r[0] for r in conn.execute(text(f"SELECT id FROM {TABLE}"))}
                stored = {r[0]: r[1] for r in conn.execute(
                    text(f"SELECT id, {COLUMN} FROM {TABLE} WHERE {COLUMN} IS NOT NULL"))}
                report["bikes_after"] = len(ids_after)
                bad = sum(1 for i, c in fill.items() if stored.get(i) != c)
                if ids_after != ids_before or bad:
                    raise RuntimeError(
                        f"verification failed: {count} bikes before, {len(ids_after)} after, "
                        f"{bad} backfilled rows differ")
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["filled"] = len(fill)
        report["status"], report["verified"] = ("backfilled" if has_column else "migrated"), True
        say(f"after:  {TABLE}.{COLUMN} {'present' if has_column else 'added'}, {count} bikes kept, "
            f"{len(fill)} filled, {count - len(stored)} NULL")
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
