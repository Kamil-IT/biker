"""Create the equipment tables and add bike_detail_component.equipment_id (TODO-042).

`init_db()`'s create_all() creates missing tables but never ALTERs an existing
one, so every pre-existing database needs this script once, BEFORE the new
backend or searcher runs on it: the new ORM reads and writes
`bike_detail_component.equipment_id` (every bike details read fails without
it), and the searcher refuses to start without the column. The OLD backend
keeps working on a migrated database (the column is nullable, the new tables
are ignored).

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_equipment_tables.py --dry-run
    python scripts/migrate_equipment_tables.py
    python scripts/migrate_equipment_tables.py --db path/to/copy.db
    python scripts/migrate_equipment_tables.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

How, in ONE transaction: the tables `equipment`, `equipment_component`,
`equipment_detail_photos` are created from the ORM models (create_all,
checkfirst — an existing one is left alone; since TODO-044 the ORM has no
`equipment_detail` / `equipment_detail_component` any more, and a database whose
`equipment` still has the old layout, i.e. no `name` column, gets no table
here — `migrate_merge_equipment_detail.py` converts it), then
`bike_detail_component.equipment_id` is added only when missing — SQLite:
`ALTER TABLE … ADD COLUMN equipment_id INTEGER REFERENCES equipment(id) ON
DELETE SET NULL`; PostgreSQL: `ADD COLUMN` → FK `…_equipment_id_fkey` →
index, under `LOCK TABLE bike_detail_component IN SHARE ROW EXCLUSIVE MODE` —
and its index `ix_bike_detail_component_equipment_id` is created when missing.
The `bike_detail_component` row count is compared before and after (and every
new `equipment_id` must be NULL); a mismatch rolls back.

Order: run `scripts/migrate_drop_bike_detail.py` FIRST. This script refuses
("failed", exit 1, nothing written) a `bike_detail_component` still keyed on
`bike_detail_id` — on SQLite that migration rebuilds the table from a fixed
column list, so an `equipment_id` added before it would be dropped again
(PostgreSQL alters in place and keeps it). Should that have happened anyway,
running this script again re-adds the column and its index (the links are
gone; they come back with the next equipment search).

Idempotent: everything present = "already-migrated"; a missing piece (index,
PostgreSQL FK) is repaired on its own. No `bike_detail_component` table =
"absent" (init_db() creates everything). Also importable:
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

from app.models import DEFAULT_DB_PATH, Base  # noqa: E402 — also registers the equipment models

TABLE = "bike_detail_component"
COLUMN = "equipment_id"
INDEX = "ix_bike_detail_component_equipment_id"
FK = "bike_detail_component_equipment_id_fkey"
NEW_TABLES = ("equipment", "equipment_component", "equipment_detail_photos")


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below —
    # pysqlite otherwise commits implicitly around DDL, which would break atomicity.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _plan(insp, dialect: str) -> dict:
    """What is missing: tables to create, column / FK / index to add."""
    missing_tables = [t for t in NEW_TABLES if not insp.has_table(t)]
    if insp.has_table("equipment") and "name" not in {c["name"] for c in insp.get_columns("equipment")}:
        missing_tables = []  # the pre-TODO-044 layout: migrate_merge_equipment_detail.py owns the tables
    has_column = COLUMN in {c["name"] for c in insp.get_columns(TABLE)}
    has_index = any(ix["name"] == INDEX for ix in insp.get_indexes(TABLE))
    has_fk = any(
        fk["referred_table"] == "equipment" and fk["constrained_columns"] == [COLUMN]
        for fk in insp.get_foreign_keys(TABLE)
    )
    return {
        "tables": missing_tables,
        "column": not has_column,
        # SQLite adds the FK with the column; a column without it cannot be fixed by ALTER there.
        "fk": dialect == "postgresql" and has_column and not has_fk,
        "index": not has_index,
    }


def _describe(plan: dict) -> str:
    parts = [f"create {', '.join(plan['tables'])}"] if plan["tables"] else []
    if plan["column"]:
        parts.append(f"add {TABLE}.{COLUMN} (FK -> equipment.id ON DELETE SET NULL) + index")
    else:
        if plan["fk"]:
            parts.append(f"add the missing FK {FK}")
        if plan["index"]:
            parts.append(f"add the missing index {INDEX}")
    return "; ".join(parts)


def _apply(conn, plan: dict, dialect: str) -> None:
    tables = [Base.metadata.tables[t] for t in NEW_TABLES if t in plan["tables"]]
    if tables:
        Base.metadata.create_all(conn, tables=tables, checkfirst=True)
    if plan["column"]:
        if dialect == "postgresql":
            conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} INTEGER")
            conn.exec_driver_sql(
                f"ALTER TABLE {TABLE} ADD CONSTRAINT {FK} FOREIGN KEY ({COLUMN}) "
                "REFERENCES equipment (id) ON DELETE SET NULL")
        else:
            conn.exec_driver_sql(
                f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} INTEGER REFERENCES equipment (id) ON DELETE SET NULL")
    elif plan["fk"]:
        conn.exec_driver_sql(
            f"ALTER TABLE {TABLE} ADD CONSTRAINT {FK} FOREIGN KEY ({COLUMN}) "
            "REFERENCES equipment (id) ON DELETE SET NULL")
    if plan["column"] or plan["index"]:
        conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {INDEX} ON {TABLE} ({COLUMN})")


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
        "status": "", "rows_before": 0, "rows_after": 0, "tables_created": [], "column_added": False,
        "verified": False, "error": None,
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if not insp.has_table(TABLE):
            report["status"], report["verified"] = "absent", True
            say(f"{TABLE} does not exist — nothing to migrate; init_db() creates every table")
            return report
        if "bike_detail_id" in {c["name"] for c in insp.get_columns(TABLE)}:
            raise RuntimeError(
                f"{TABLE} is still keyed on bike_detail_id — run scripts/migrate_drop_bike_detail.py first")
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
        report["rows_before"] = report["rows_after"] = count
        plan = _plan(insp, dialect)
        if not (plan["tables"] or plan["column"] or plan["fk"] or plan["index"]):
            report["status"], report["verified"] = "already-migrated", True
            say(f"equipment tables and {TABLE}.{COLUMN} already exist — nothing to do ({count} rows)")
            return report
        if dry_run:
            report["status"], report["verified"] = "dry-run", True
            say(f"dry run: would {_describe(plan)}; {count} rows in {TABLE} — nothing written")
            return report

        say(f"before: {count} rows in {TABLE}; will {_describe(plan)}")
        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                if dialect == "postgresql":
                    conn.exec_driver_sql(f"LOCK TABLE {TABLE} IN SHARE ROW EXCLUSIVE MODE")
                before = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
                _apply(conn, plan, dialect)
                after = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
                linked = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE} WHERE {COLUMN} IS NOT NULL")).scalar_one()
                check = inspect(conn)
                still_missing = [t for t in plan["tables"] if not check.has_table(t)]
                report["rows_before"], report["rows_after"] = before, after
                if after != before or still_missing or (plan["column"] and linked):
                    raise RuntimeError(
                        f"verification failed: {before} rows before, {after} after, {linked} linked, "
                        f"tables still missing {still_missing}")
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["status"], report["verified"] = "migrated", True
        report["tables_created"], report["column_added"] = list(plan["tables"]), plan["column"]
        say(f"after:  {_describe(plan)} — done; {after} rows kept in {TABLE}")
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
