"""Rename the `bike_detail_component` table to `bike_component`.

The component spec tree has been keyed on `bike.id` since `bike_detail` was
dropped (scripts/migrate_drop_bike_detail.py), so the old name no longer
describes it. The ORM (backend + searcher) now maps `bike_component`;
`init_db()`'s create_all() never renames an existing table, so every
pre-existing database needs this script once - AFTER migrate_drop_bike_detail.py
and migrate_equipment_tables.py (both still address the old name) and BEFORE
the new backend / searcher run on it. The new searcher refuses to
start on an unmigrated database; the OLD backend breaks on a migrated one (it
still queries `bike_detail_component`).

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_rename_bike_component.py --dry-run
    python scripts/migrate_rename_bike_component.py
    python scripts/migrate_rename_bike_component.py --db path/to/copy.db
    python scripts/migrate_rename_bike_component.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

How (ONE transaction on both dialects, any failure or failed verification rolls
back and leaves the database unchanged):
  1. ALTER TABLE bike_detail_component RENAME TO bike_component (PostgreSQL
     takes `LOCK TABLE ... ACCESS EXCLUSIVE` implicitly);
  2. rename what create_all would have named after the table: the indexes
     (`ix_bike_detail_component_*` -> `ix_bike_component_*`; SQLite drops and
     recreates them, PostgreSQL `ALTER INDEX ... RENAME`), and on PostgreSQL the
     primary-key / foreign-key constraints (bike_id, equipment_id) and the id
     sequence;
  3. rename `bike_detail_component_orphans` (left by the previous migration)
     to `bike_component_orphans` when it exists.
Verified before commit: every row (every column) reads back identical from the
renamed table.

An empty `bike_detail_component` next to a populated `bike_component` (an OLD
backend's create_all recreated it) is dropped; an empty `bike_component` next
to a populated `bike_detail_component` (the NEW backend started too early) is
dropped and the rename goes ahead. Both populated -> refused.

Idempotent: with `bike_component` in place and nothing left under the old
names the result is `already-migrated`; leftover old names are repaired. A
database without either table is left to init_db(). Also importable:
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

OLD = "bike_detail_component"
NEW = "bike_component"
OLD_ORPHANS = f"{OLD}_orphans"
NEW_ORPHANS = f"{NEW}_orphans"
# (old name, new name) of what create_all names after the table on PostgreSQL
_PG_CONSTRAINTS = (
    (f"{OLD}_pkey", f"{NEW}_pkey"),
    (f"{OLD}_bike_id_fkey", f"{NEW}_bike_id_fkey"),
    (f"{OLD}_equipment_id_fkey", f"{NEW}_equipment_id_fkey"),  # TODO-042
)
_PG_SEQUENCE = (f"{OLD}_id_seq", f"{NEW}_id_seq")


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below -
    # pysqlite otherwise commits implicitly around DDL, which would break atomicity.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _leftovers(conn, table: str) -> list[dict]:
    """Objects of `table` still carrying the old name: {kind, old, new, columns}."""
    insp = inspect(conn)
    found = []
    for ix in insp.get_indexes(table):
        name = ix["name"] or ""
        if name.startswith(f"ix_{OLD}_"):
            found.append({"kind": "index", "old": name, "new": f"ix_{NEW}_" + name[len(f"ix_{OLD}_"):],
                          "columns": list(ix["column_names"])})
    if conn.dialect.name == "postgresql":
        names = {insp.get_pk_constraint(table).get("name")} | {fk.get("name") for fk in insp.get_foreign_keys(table)}
        for old, new in _PG_CONSTRAINTS:
            if old in names:
                found.append({"kind": "constraint", "old": old, "new": new, "columns": []})
        if conn.execute(text("SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = :n"),
                        {"n": _PG_SEQUENCE[0]}).first():
            found.append({"kind": "sequence", "old": _PG_SEQUENCE[0], "new": _PG_SEQUENCE[1], "columns": []})
    if insp.has_table(OLD_ORPHANS):
        found.append({"kind": "table", "old": OLD_ORPHANS, "new": NEW_ORPHANS, "columns": []})
    return found


def _rename_sql(conn, item: dict) -> list[str]:
    pg = conn.dialect.name == "postgresql"
    if item["kind"] == "index":
        if pg:
            return [f"ALTER INDEX {item['old']} RENAME TO {item['new']}"]
        return [f"DROP INDEX {item['old']}",
                f"CREATE INDEX {item['new']} ON {NEW} ({', '.join(item['columns'])})"]
    if item["kind"] == "constraint":
        return [f"ALTER TABLE {NEW} RENAME CONSTRAINT {item['old']} TO {item['new']}"]
    if item["kind"] == "sequence":
        return [f"ALTER SEQUENCE {item['old']} RENAME TO {item['new']}"]
    return [f"ALTER TABLE {item['old']} RENAME TO {item['new']}"]


def _rows(conn, table: str) -> dict:
    """Every row of `table`, keyed on id, with every column (whatever the layout: equipment_id included)."""
    columns = sorted(c["name"] for c in inspect(conn).get_columns(table))
    columns.remove("id")
    sql = f"SELECT id, {', '.join(columns)} FROM {table}"
    return {r[0]: tuple(r[1:]) for r in conn.execute(text(sql))}


def migrate(url_or_path=None, dry_run: bool = False, verbose: bool = True) -> dict:
    """Migrate one database; returns a report dict (see the keys below).

    `status` is one of: "migrated", "repaired", "dry-run", "already-migrated",
    "absent", "failed". `renamed` lists every object renamed as "kind old -> new".
    """
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    engine = _engine(url)
    dialect = engine.dialect.name
    report = {
        "database": make_url(url).render_as_string(hide_password=True), "dialect": dialect,
        "status": "", "rows_before": 0, "rows_after": 0, "renamed": [], "verified": False, "error": None,
    }
    say(f"database: {report['database']}")
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                insp = inspect(conn)
                has_old, has_new = insp.has_table(OLD), insp.has_table(NEW)
                if not (has_old or has_new):
                    conn.exec_driver_sql("ROLLBACK")
                    report["status"], report["verified"] = "absent", True
                    say(f"neither {OLD} nor {NEW} exists - nothing to migrate; init_db() creates {NEW}")
                    return report
                if dialect == "postgresql":
                    tables = [t for t, present in ((OLD, has_old), (NEW, has_new)) if present]
                    conn.exec_driver_sql(f"LOCK TABLE {', '.join(tables)} IN ACCESS EXCLUSIVE MODE")

                drop_empty = None  # the empty duplicate a too-early / too-late service created
                if has_old and has_new:
                    n_old = conn.execute(text(f"SELECT COUNT(*) FROM {OLD}")).scalar_one()
                    n_new = conn.execute(text(f"SELECT COUNT(*) FROM {NEW}")).scalar_one()
                    if n_old == 0:
                        drop_empty, has_old = OLD, False
                    elif n_new == 0:
                        drop_empty, has_new = NEW, False
                    else:
                        raise RuntimeError(f"both {OLD} ({n_old} rows) and {NEW} ({n_new} rows) hold data - "
                                           "refusing to guess; merge or drop one by hand")
                    say(f"both tables exist, {drop_empty} is empty - dropping it")

                source = OLD if has_old else NEW
                expected = _rows(conn, source)
                report["rows_before"] = len(expected)
                plan = [{"kind": "table", "old": OLD, "new": NEW, "columns": []}] if has_old else []
                # leftovers are read off the source table now (index names survive a rename on both dialects)
                plan += _leftovers(conn, source)
                if drop_empty:
                    plan.insert(0, {"kind": "drop", "old": drop_empty, "new": "", "columns": []})
                say(f"before: {len(expected)} rows in {source}; "
                    f"{len(plan)} object(s) to change: "
                    + (", ".join(f"{p['kind']} {p['old']}" + (f" -> {p['new']}" if p['new'] else "") for p in plan) or "none"))

                if not plan:
                    conn.exec_driver_sql("ROLLBACK")
                    report["status"], report["rows_after"], report["verified"] = "already-migrated", len(expected), True
                    say(f"already migrated: {NEW} in place, nothing left under the old name ({len(expected)} rows) - nothing to do")
                    return report
                if dry_run:
                    conn.exec_driver_sql("ROLLBACK")
                    report["status"], report["rows_after"], report["verified"] = "dry-run", len(expected), True
                    say("dry run: nothing written")
                    return report

                # -- migrate ---------------------------------------------------
                for item in plan:
                    sqls = [f"DROP TABLE {item['old']}"] if item["kind"] == "drop" else _rename_sql(conn, item)
                    for sql in sqls:
                        conn.exec_driver_sql(sql)
                    report["renamed"].append(f"{item['kind']} {item['old']}" + (f" -> {item['new']}" if item["new"] else ""))

                # -- verify ----------------------------------------------------
                insp = inspect(conn)
                if insp.has_table(OLD) or not insp.has_table(NEW):
                    raise RuntimeError(f"verification failed: {OLD} still present or {NEW} missing after the rename")
                after = _rows(conn, NEW)
                report["rows_after"] = len(after)
                if after != expected:
                    missing = sorted(set(expected) - set(after))[:10]
                    changed = sorted(i for i in set(expected) & set(after) if expected[i] != after[i])[:10]
                    raise RuntimeError(f"verification failed: expected {len(expected)} rows, got {len(after)}; "
                                       f"missing ids {missing}, changed ids {changed}")
                left = _leftovers(conn, NEW)
                if left:
                    raise RuntimeError(f"verification failed: still under the old name: "
                                       + ", ".join(f"{l['kind']} {l['old']}" for l in left))
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["status"] = "migrated" if has_old else "repaired"
        report["verified"] = True
        say(f"after:  {report['rows_after']} rows in {NEW}, verified identical; renamed: "
            + "; ".join(report["renamed"]))
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
