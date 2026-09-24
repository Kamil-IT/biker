"""One-off copy of the SQLite cache database into PostgreSQL (TODO-028).

Creates the schema on the target from the ORM metadata in app/models.py
(`create_all`), then copies every table row-for-row in foreign-key order,
resets the PostgreSQL id sequences, and verifies the copy per table: row
count plus a content checksum computed over both databases.

    # target defaults to $DATABASE_URL
    python scripts/copy_sqlite_to_postgres.py
    python scripts/copy_sqlite_to_postgres.py --source ../cache.db \
        --target postgresql+psycopg://biker:biker@localhost:5432/biker
    python scripts/copy_sqlite_to_postgres.py --truncate   # wipe a non-empty target first
    python scripts/copy_sqlite_to_postgres.py --verify-only

Orphans: SQLite ran for a while without `PRAGMA foreign_keys=ON`, so a child
row can point at a parent that no longer exists. PostgreSQL enforces every FK,
so such rows are skipped and listed — they were unreachable anyway.
Verification compares the target against the source *minus* those orphans.

The whole copy runs in one transaction: a failure leaves the target unchanged.
Idempotent: refuses to write into a target that already holds rows unless
`--truncate` is passed. The source SQLite file is opened read-only.

Exit code: 0 when every table matches, 1 on any mismatch or refused run.
"""
import argparse
import hashlib
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import Integer, String, create_engine, func, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

from app.models import Base  # noqa: E402

DEFAULT_SOURCE = BACKEND_DIR / "cache.db"
BATCH_SIZE = 1000
# SQLite bookkeeping tables — never copied.
SKIP_SOURCE_TABLES = {"sqlite_sequence"}

# {table name: (rows to copy, orphan rows dropped)}
SourceData = dict[str, tuple[list[dict], int]]


def sqlite_engine(path: Path) -> Engine:
    # mode=ro: the source is data paid for with Anthropic tokens — never write to it.
    uri = f"file:{path.as_posix()}?mode=ro"
    return create_engine("sqlite://", creator=lambda: sqlite3.connect(uri, uri=True))


def check_schema(src: Engine) -> list[str]:
    """Problems that would lose data: source tables/columns the ORM does not know."""
    problems = []
    insp = inspect(src)
    known = Base.metadata.tables
    for name in insp.get_table_names():
        if name in SKIP_SOURCE_TABLES:
            continue
        if name not in known:
            problems.append(f"source table '{name}' has no model in app/models.py — it would not be copied")
            continue
        missing = {c["name"] for c in insp.get_columns(name)} - set(known[name].columns.keys())
        if missing:
            problems.append(f"{name}: source columns {sorted(missing)} have no model column")
    return problems


def check_values(table, rows: list[dict]) -> list[str]:
    """Values PostgreSQL would reject but SQLite silently accepted."""
    problems = []
    for col in table.columns:
        limit = col.type.length if isinstance(col.type, String) else None
        for row in rows:
            v = row[col.name]
            if not isinstance(v, str):
                continue
            if "\x00" in v:
                problems.append(f"{table.name}.{col.name}: NUL byte in value (PostgreSQL rejects it)")
            if limit is not None and len(v) > limit:
                problems.append(f"{table.name}.{col.name}: value of {len(v)} chars exceeds {limit}")
    return problems[:20]


def read_rows(engine: Engine, table) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(select(table))]


def source_rows(src: Engine) -> SourceData:
    """Every ORM table's source rows, in FK order, with orphan rows filtered out."""
    insp = inspect(src)
    kept: dict[str, list[dict]] = {}
    data: SourceData = {}
    for table in Base.metadata.sorted_tables:  # parents before children
        rows = read_rows(src, table) if insp.has_table(table.name) else []
        before = len(rows)
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent == table.name or parent not in kept:
                continue
            valid = {r[fk.column.name] for r in kept[parent]}
            col = fk.parent.name
            orphan_ids = sorted({r[col] for r in rows if r[col] is not None and r[col] not in valid})
            if orphan_ids:
                rows = [r for r in rows if r[col] is None or r[col] in valid]
                print(f"  {table.name}: skipping orphan rows — {col} {orphan_ids} missing from {parent}")
        kept[table.name] = rows
        data[table.name] = (rows, before - len(rows))
    return data


def _canon(v) -> str:
    if v is None:
        return "\x1fNULL"
    if isinstance(v, datetime):
        return v.replace(tzinfo=None).isoformat()
    if isinstance(v, float):
        return repr(v)
    return f"{type(v).__name__}:{v}"


def fingerprint(rows: list[dict], columns: list[str]) -> str:
    """sha256 over every row — independent of physical row order."""
    lines = sorted("\x1e".join(_canon(row[c]) for c in columns) for row in rows)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def target_row_counts(dst: Engine) -> dict[str, int]:
    with dst.connect() as conn:
        return {
            t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
            for t in Base.metadata.sorted_tables
        }


def copy_tables(conn, data: SourceData) -> None:
    problems = []
    for table in Base.metadata.sorted_tables:
        problems += check_values(table, data[table.name][0])
    if problems:
        raise SystemExit("Refusing to copy — PostgreSQL would reject these values:\n  " + "\n  ".join(problems))
    for table in Base.metadata.sorted_tables:  # parents before children
        rows = data[table.name][0]
        for i in range(0, len(rows), BATCH_SIZE):
            conn.execute(table.insert(), rows[i : i + BATCH_SIZE])
        print(f"  {table.name:32} {len(rows):>7} rows copied")


def reset_sequences(conn) -> None:
    """Explicit ids were inserted, so each SERIAL sequence must move past MAX(id)."""
    for table in Base.metadata.sorted_tables:
        pk = list(table.primary_key.columns)
        if len(pk) != 1 or not isinstance(pk[0].type, Integer):
            continue
        col = pk[0].name
        conn.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence(:t, :c), "
                f"COALESCE((SELECT MAX({col}) FROM {table.name}), 1), "
                f"(SELECT MAX({col}) FROM {table.name}) IS NOT NULL)"
            ),
            {"t": table.name, "c": col},
        )


def verify(data: SourceData, dst: Engine) -> bool:
    print(f"\n  {'table':32} {'sqlite':>8} {'orphans':>8} {'postgres':>9}  content")
    ok = True
    for table in Base.metadata.sorted_tables:
        rows, orphans = data[table.name]
        cols = list(table.columns.keys())
        target = read_rows(dst, table)
        same = len(rows) == len(target) and fingerprint(rows, cols) == fingerprint(target, cols)
        ok &= same
        print(f"  {table.name:32} {len(rows) + orphans:>8} {orphans:>8} {len(target):>9}  {'OK' if same else 'MISMATCH'}")
    return ok


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console: keep the dashes readable
    load_dotenv(BACKEND_DIR / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="SQLite file (default: backend/cache.db)")
    ap.add_argument("--target", default=os.getenv("DATABASE_URL"), help="PostgreSQL URL (default: $DATABASE_URL)")
    ap.add_argument("--truncate", action="store_true", help="empty a non-empty target before copying")
    ap.add_argument("--verify-only", action="store_true", help="only compare source and target, copy nothing")
    args = ap.parse_args()

    if not args.source.is_file():
        print(f"Source SQLite file not found: {args.source}")
        return 1
    if not args.target or not args.target.startswith("postgresql"):
        print("Target must be a PostgreSQL URL — pass --target or set DATABASE_URL, e.g.\n"
              "  postgresql+psycopg://biker:biker@localhost:5432/biker")
        return 1

    src = sqlite_engine(args.source)
    dst = create_engine(args.target, pool_pre_ping=True)
    print(f"source: {args.source}")
    print(f"target: {dst.url.render_as_string(hide_password=True)}")

    problems = check_schema(src)
    if problems:
        print("Refusing to copy — schema drift:\n  " + "\n  ".join(problems))
        return 1
    print("\nreading source:")
    data = source_rows(src)

    if not args.verify_only:
        Base.metadata.create_all(dst)
        non_empty = {t: n for t, n in target_row_counts(dst).items() if n}
        if non_empty and not args.truncate:
            print(f"Target is not empty {non_empty} — re-run with --truncate to replace its contents.")
            return 1
        print("\ncopying:")
        try:
            with dst.begin() as conn:  # one transaction: all or nothing
                if non_empty:
                    names = ", ".join(t.name for t in Base.metadata.sorted_tables)
                    conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
                    print("  target truncated")
                copy_tables(conn, data)
                reset_sequences(conn)
        except SQLAlchemyError as exc:
            reason = str(getattr(exc, "orig", None) or exc).splitlines()[0]
            print(f"\nCopy FAILED — rolled back, target unchanged.\n  {reason}")
            return 1

    ok = verify(data, dst)
    print("\nRESULT:", "all tables match" if ok else "MISMATCH — see table above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
