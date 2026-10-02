"""Add bike_component.is_linkable and backfill it with the regex heuristic (ISSUE-016).

`init_db()`'s create_all() never ALTERs an existing table, so every pre-existing
database needs this script once, BEFORE the new backend or searcher runs on it:
the new ORM reads and writes `bike_component.is_linkable` (a SELECT of the
missing column fails) and the searcher refuses to start without it. The OLD
backend keeps working on a migrated database because the column has a server
default (TRUE = the old "every name is a link" behaviour).

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_component_linkable.py --dry-run     # distribution + samples, nothing written
    python scripts/migrate_component_linkable.py
    python scripts/migrate_component_linkable.py --reclassify  # re-run the heuristic on a migrated database
    python scripts/migrate_component_linkable.py --db path/to/copy.db
    python scripts/migrate_component_linkable.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

How, in ONE transaction: `ALTER TABLE bike_component ADD COLUMN is_linkable
BOOLEAN NOT NULL DEFAULT TRUE` (both dialects), then every row is classified with
`app.linkable.is_linkable(element_name, subcategory)` — the same heuristic the
discovery scraper uses — and the rows that come out False are updated. Verified
before commit: the row count is unchanged and the stored flags equal the
computed ones; any mismatch rolls back (exit code 1). PostgreSQL runs under
`LOCK TABLE … IN SHARE ROW EXCLUSIVE MODE`.

Idempotent: a present column = "already-migrated" (the rows are NOT reclassified,
so flags written by the searcher's model are kept); `--reclassify` re-runs the
heuristic over every row of a migrated database — only for tuning the regexes,
it overwrites the model's decisions. Run it AFTER `migrate_rename_bike_component.py`
(a database still on `bike_detail_component` is refused). No `bike_component` table = "absent"
(init_db() creates it with the column). Also importable:
`migrate(url_or_path=None, dry_run=False, reclassify=False, verbose=True) -> dict`.

Exit code: 0 on success (or nothing to do), 1 on a failed run.
"""
import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

from app.linkable import is_linkable  # noqa: E402
from app.models import DEFAULT_DB_PATH  # noqa: E402

TABLE = "bike_component"
COLUMN = "is_linkable"
SAMPLE = 15


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _classify(conn) -> tuple[dict[int, bool], Counter, Counter]:
    """(id → flag) for every row, plus the distinct names that came out True / False (weighted by rows)."""
    flags: dict[int, bool] = {}
    names_true: Counter = Counter()
    names_false: Counter = Counter()
    for row_id, subcategory, name in conn.execute(text(f"SELECT id, subcategory, element_name FROM {TABLE}")):
        flag = is_linkable(name or "", subcategory or "")
        flags[row_id] = flag
        (names_true if flag else names_false)[f"{subcategory} | {name}"] += 1
    return flags, names_true, names_false


def _say_distribution(say, flags, names_true, names_false) -> None:
    total = len(flags)
    n_true = sum(1 for f in flags.values() if f)
    say(f"rows: {total}  linkable: {n_true}  not linkable: {total - n_true}")
    for label, counter in (("TRUE (link)", names_true), ("FALSE (no link)", names_false)):
        say(f"  most frequent {label}:")
        for key, n in counter.most_common(SAMPLE):
            say(f"    {n:5d}  {key}")


def migrate(url_or_path=None, dry_run: bool = False, reclassify: bool = False, verbose: bool = True) -> dict:
    """Migrate one database; returns a report dict.

    `status` is one of: "migrated", "reclassified", "dry-run", "already-migrated", "absent", "failed".
    """
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    engine = _engine(url)
    dialect = engine.dialect.name
    report = {
        "database": make_url(url).render_as_string(hide_password=True), "dialect": dialect,
        "status": "", "rows_before": 0, "rows_after": 0, "linkable": 0, "not_linkable": 0,
        "verified": False, "error": None,
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if insp.has_table("bike_detail_component") and not insp.has_table(TABLE):
            raise RuntimeError(
                "the database still has bike_detail_component — run scripts/migrate_rename_bike_component.py first")
        if not insp.has_table(TABLE):
            report["status"], report["verified"] = "absent", True
            say(f"{TABLE} does not exist — nothing to migrate; init_db() creates it with {COLUMN}")
            return report
        has_column = COLUMN in {c["name"] for c in insp.get_columns(TABLE)}
        with engine.connect() as conn:
            count = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
            flags, names_true, names_false = _classify(conn)
        report["rows_before"] = report["rows_after"] = count
        report["linkable"] = sum(1 for f in flags.values() if f)
        report["not_linkable"] = count - report["linkable"]
        if has_column and not reclassify:
            report["status"], report["verified"] = "already-migrated", True
            say(f"{TABLE}.{COLUMN} already exists — nothing to do ({count} rows; --reclassify re-runs the heuristic)")
            return report
        _say_distribution(say, flags, names_true, names_false)
        if dry_run:
            report["status"], report["verified"] = "dry-run", True
            action = "reclassify" if has_column else f"add {TABLE}.{COLUMN} (BOOLEAN NOT NULL DEFAULT TRUE) and classify"
            say(f"dry run: would {action} {count} rows — nothing written")
            return report

        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                if dialect == "postgresql":
                    conn.exec_driver_sql(f"LOCK TABLE {TABLE} IN SHARE ROW EXCLUSIVE MODE")
                if not has_column:
                    conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} BOOLEAN NOT NULL DEFAULT TRUE")
                else:
                    conn.exec_driver_sql(f"UPDATE {TABLE} SET {COLUMN} = TRUE")
                false_ids = [row_id for row_id, flag in flags.items() if not flag]
                if false_ids:
                    conn.execute(
                        text(f"UPDATE {TABLE} SET {COLUMN} = FALSE WHERE id = :id"),
                        [{"id": row_id} for row_id in false_ids],
                    )
                after = conn.execute(text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
                stored = {
                    row_id: bool(flag)
                    for row_id, flag in conn.execute(text(f"SELECT id, {COLUMN} FROM {TABLE}"))
                }
                report["rows_after"] = after
                if after != count or stored != flags:
                    mismatched = sum(1 for k, v in flags.items() if stored.get(k) is not v)
                    raise RuntimeError(
                        f"verification failed: {count} rows before, {after} after, {mismatched} flags differ")
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["status"], report["verified"] = ("reclassified" if has_column else "migrated"), True
        say(f"after:  {TABLE}.{COLUMN} {'reclassified' if has_column else 'added'}, {after} rows kept, "
            f"{report['linkable']} linkable / {report['not_linkable']} not")
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
    ap.add_argument("--reclassify", action="store_true",
                    help="re-run the heuristic over every row of an already migrated database")
    args = ap.parse_args()
    if args.db is not None and not args.db.exists():
        print(f"SQLite file not found: {args.db}")
        return 1
    report = migrate(args.db or args.url, dry_run=args.dry_run, reclassify=args.reclassify)
    print("\nRESULT:", report["status"])
    return 0 if report["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
