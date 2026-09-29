"""Re-key bike_detail_photos from bike_detail_id to bike_id (photos searcher).

Photos used to hang off the details row (`bike_detail_id` → bike_detail.id);
now they belong to the bike itself (`bike_id` → bike.id, ON DELETE CASCADE,
NOT NULL, indexed), so a details re-save or delete no longer touches them and
a bike can have photos without details. The table keeps its name. `init_db()`'s
create_all() never ALTERs an existing table, so every pre-existing database
needs this script once — BEFORE the new backend / searcher are deployed on it.
Until then POST /v1/bike/photos answers `[]` and logs an ERROR naming this
script, and the searcher refuses to start.

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_photos_bike_id.py --dry-run
    python scripts/migrate_photos_bike_id.py
    python scripts/migrate_photos_bike_id.py --db path/to/copy.db
    python scripts/migrate_photos_bike_id.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker_photos

How:
  - SQLite cannot drop a FK column in place, so the table is rebuilt:
    CREATE bike_detail_photos_new → INSERT … SELECT through bike_detail →
    DROP the old table → RENAME → CREATE INDEX.
  - PostgreSQL is altered in place under `LOCK TABLE … SHARE ROW EXCLUSIVE`
    (so concurrent writes cannot skew the verification): ADD COLUMN bike_id →
    UPDATE … FROM bike_detail → SET NOT NULL + FK + index → DROP COLUMN
    bike_detail_id (its FK and index go with it). The id sequence is untouched.
  Both run in ONE transaction (DDL is transactional on both dialects): any
  failure, or a failed verification, rolls back and leaves the DB unchanged.

Every photo row keeps its id, url and display_order, and its new bike_id is
the bike its old details row belonged to — verified row by row before commit.
Rows whose details row (or that row's bike) is missing cannot be re-keyed:
they are listed, copied into `bike_detail_photos_orphans` (id, bike_detail_id,
bike_id, url, display_order) in the same transaction, and left out of the
migrated table — never dropped silently.

Idempotent: a table already keyed on bike_id is checked — NOT NULL, the FK to
bike (ON DELETE CASCADE) and the bike_id index — and only a missing piece is
repaired (same rebuild / ALTER path, rows pointing at no bike go to the orphans
table). An absent table is left to init_db(), which creates it with the new
schema. Also importable:
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

TABLE = "bike_detail_photos"
ORPHANS = "bike_detail_photos_orphans"
INDEX = "ix_bike_detail_photos_bike_id"
FK_NAME = "bike_detail_photos_bike_id_fkey"  # the name create_all gives it on PostgreSQL

# Rows joined to the bike they will belong to; new_bike_id is NULL for an orphan.
# "detail": the old schema, re-keyed through bike_detail. "bike": already keyed
# on bike_id but missing its FK / NOT NULL / index — repaired in place.
_SNAPSHOT_SQL = {
    "detail": f"""
        SELECT p.id, p.bike_detail_id, NULL AS bike_id, p.url, p.display_order, b.id AS new_bike_id
        FROM {TABLE} p
        LEFT JOIN bike_detail d ON d.id = p.bike_detail_id
        LEFT JOIN bike b ON b.id = d.bike_id
        ORDER BY p.id""",
    "bike": f"""
        SELECT p.id, NULL AS bike_detail_id, p.bike_id, p.url, p.display_order, b.id AS new_bike_id
        FROM {TABLE} p
        LEFT JOIN bike b ON b.id = p.bike_id
        ORDER BY p.id""",
}

# Same DDL create_all emits for BikeDetailPhoto (table-level FOREIGN KEY clause).
_SQLITE_NEW_TABLE = f"""CREATE TABLE {TABLE}_new (
    id INTEGER NOT NULL,
    bike_id INTEGER NOT NULL,
    url VARCHAR(2048) NOT NULL,
    display_order INTEGER,
    PRIMARY KEY (id),
    FOREIGN KEY(bike_id) REFERENCES bike (id) ON DELETE CASCADE
)"""
_SQLITE_COPY = {
    "detail": f"""INSERT INTO {TABLE}_new (id, bike_id, url, display_order)
        SELECT p.id, b.id, p.url, p.display_order
        FROM {TABLE} p
        JOIN bike_detail d ON d.id = p.bike_detail_id
        JOIN bike b ON b.id = d.bike_id""",
    "bike": f"""INSERT INTO {TABLE}_new (id, bike_id, url, display_order)
        SELECT p.id, b.id, p.url, p.display_order
        FROM {TABLE} p
        JOIN bike b ON b.id = p.bike_id""",
}


def _sqlite_steps(mode: str) -> list[str]:
    return [
        _SQLITE_NEW_TABLE,
        _SQLITE_COPY[mode],
        f"DROP TABLE {TABLE}",
        f"ALTER TABLE {TABLE}_new RENAME TO {TABLE}",
        f"CREATE INDEX {INDEX} ON {TABLE} (bike_id)",
    ]


def _pg_steps(mode: str) -> list[str]:
    if mode == "detail":
        rekey = [
            f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS bike_id INTEGER",
            f"""UPDATE {TABLE} p SET bike_id = b.id
                FROM bike_detail d JOIN bike b ON b.id = d.bike_id
                WHERE d.id = p.bike_detail_id""",
        ]
    else:
        # DELETE rather than SET NULL: the column may already be NOT NULL.
        rekey = [f"DELETE FROM {TABLE} p WHERE NOT EXISTS (SELECT 1 FROM bike b WHERE b.id = p.bike_id)"]
    tail = [f"ALTER TABLE {TABLE} DROP COLUMN bike_detail_id"] if mode == "detail" else []
    return rekey + [
        f"DELETE FROM {TABLE} WHERE bike_id IS NULL",  # the orphans, copied to ORPHANS beforehand
        f"ALTER TABLE {TABLE} ALTER COLUMN bike_id SET NOT NULL",
        f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {FK_NAME}",
        f"""ALTER TABLE {TABLE} ADD CONSTRAINT {FK_NAME}
            FOREIGN KEY (bike_id) REFERENCES bike (id) ON DELETE CASCADE""",
        f"CREATE INDEX IF NOT EXISTS {INDEX} ON {TABLE} (bike_id)",
    ] + tail


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below —
    # pysqlite otherwise commits implicitly around DDL, which would break atomicity.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _schema_gaps(engine, insp) -> list[str]:
    """What a bike_id-keyed table still lacks: NOT NULL, the CASCADE FK to bike, the bike_id index."""
    gaps = []
    col = next(c for c in insp.get_columns(TABLE) if c["name"] == "bike_id")
    if col.get("nullable", True):
        gaps.append("bike_id is nullable")
    if engine.dialect.name == "sqlite":
        # SQLAlchemy only reflects ON DELETE from table-level FK clauses; the
        # pragma sees column-level ones too. Columns: id, seq, table, from, to, on_update, on_delete, match.
        with engine.connect() as conn:
            fk_ok = any(
                r[2] == "bike" and r[3] == "bike_id" and r[6].upper() == "CASCADE"
                for r in conn.exec_driver_sql(f"PRAGMA foreign_key_list({TABLE})")
            )
    else:
        fk_ok = any(
            fk["constrained_columns"] == ["bike_id"] and fk["referred_table"] == "bike"
            and (fk.get("options") or {}).get("ondelete", "").upper() == "CASCADE"
            for fk in insp.get_foreign_keys(TABLE)
        )
    if not fk_ok:
        gaps.append("no FK bike_id → bike.id ON DELETE CASCADE")
    if not any(ix["column_names"] == ["bike_id"] for ix in insp.get_indexes(TABLE)):
        gaps.append("no index on bike_id")
    return gaps


def _save_orphans(conn, orphans) -> None:
    """Copy the rows that cannot be re-keyed into ORPHANS (same transaction)."""
    conn.exec_driver_sql(f"""CREATE TABLE IF NOT EXISTS {ORPHANS} (
        id INTEGER NOT NULL PRIMARY KEY,
        bike_detail_id INTEGER,
        bike_id INTEGER,
        url VARCHAR(2048) NOT NULL,
        display_order INTEGER
    )""")
    conn.execute(
        text(f"""INSERT INTO {ORPHANS} (id, bike_detail_id, bike_id, url, display_order)
                 VALUES (:id, :bike_detail_id, :bike_id, :url, :display_order)
                 ON CONFLICT (id) DO NOTHING"""),
        [{k: r[k] for k in ("id", "bike_detail_id", "bike_id", "url", "display_order")} for r in orphans],
    )


def migrate(url_or_path=None, dry_run: bool = False, verbose: bool = True) -> dict:
    """Migrate one database; returns a report dict (see the keys below).

    `status` is one of: "migrated", "repaired", "dry-run", "already-migrated",
    "absent", "failed". `orphans` lists the rows that could not be re-keyed as
    {id, bike_detail_id, bike_id, url}; they are kept in bike_detail_photos_orphans.
    """
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    engine = _engine(url)
    dialect = engine.dialect.name
    report = {
        "database": make_url(url).render_as_string(hide_password=True), "dialect": dialect,
        "status": "", "rows_before": 0, "rows_after": 0, "orphans": [], "bikes_with_photos": 0,
        "verified": False, "gaps": [], "error": None,
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if not insp.has_table(TABLE):
            report["status"], report["verified"] = "absent", True
            say(f"{TABLE} does not exist — nothing to migrate; init_db() creates it with the new schema")
            return report

        cols = {c["name"] for c in insp.get_columns(TABLE)}
        if "bike_detail_id" in cols:
            mode = "detail"
        elif "bike_id" in cols:
            report["gaps"] = _schema_gaps(engine, insp)
            if not report["gaps"]:
                with engine.connect() as conn:
                    report["rows_before"] = report["rows_after"] = conn.execute(
                        text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
                    report["bikes_with_photos"] = conn.execute(
                        text(f"SELECT COUNT(DISTINCT bike_id) FROM {TABLE}")).scalar_one()
                report["status"], report["verified"] = "already-migrated", True
                say(f"{TABLE} already keyed on bike_id, NOT NULL + FK + index present — nothing to do "
                    f"({report['rows_after']} rows, {report['bikes_with_photos']} bikes)")
                return report
            mode = "bike"
            say(f"{TABLE} keyed on bike_id but incomplete: {'; '.join(report['gaps'])} — repairing")
        else:
            raise RuntimeError(f"{TABLE} has neither bike_detail_id nor bike_id — unknown schema {sorted(cols)}")

        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                if dialect == "postgresql":
                    parent = "bike_detail" if mode == "detail" else "bike"
                    conn.exec_driver_sql(f"LOCK TABLE {TABLE}, {parent} IN SHARE ROW EXCLUSIVE MODE")
                snapshot = conn.execute(text(_SNAPSHOT_SQL[mode])).mappings().all()
                report["rows_before"] = len(snapshot)
                orphans = [r for r in snapshot if r["new_bike_id"] is None]
                report["orphans"] = [
                    {k: r[k] for k in ("id", "bike_detail_id", "bike_id", "url")} for r in orphans
                ]
                expected = {
                    r["id"]: (r["new_bike_id"], r["url"], r["display_order"])
                    for r in snapshot if r["new_bike_id"] is not None
                }
                report["bikes_with_photos"] = len({v[0] for v in expected.values()})
                say(f"before: {len(snapshot)} photo rows, {report['bikes_with_photos']} bikes, "
                    f"{len(orphans)} orphan rows")
                for o in report["orphans"]:
                    say(f"  orphan (no details row / bike) — moved to {ORPHANS}: id={o['id']} "
                        f"bike_detail_id={o['bike_detail_id']} bike_id={o['bike_id']} url={o['url']}")

                if dry_run:
                    conn.exec_driver_sql("ROLLBACK")
                    report["status"], report["rows_after"] = "dry-run", len(expected)
                    report["verified"] = True
                    say(f"dry run: would re-key {len(expected)} rows and move {len(orphans)} orphans "
                        f"to {ORPHANS} — nothing written")
                    return report

                if orphans:
                    _save_orphans(conn, orphans)
                for sql in (_sqlite_steps(mode) if dialect == "sqlite" else _pg_steps(mode)):
                    conn.exec_driver_sql(sql)

                after = {
                    r.id: (r.bike_id, r.url, r.display_order)
                    for r in conn.execute(text(f"SELECT id, bike_id, url, display_order FROM {TABLE}"))
                }
                report["rows_after"] = len(after)
                if after != expected:
                    missing = sorted(set(expected) - set(after))[:10]
                    changed = sorted(i for i in set(expected) & set(after) if expected[i] != after[i])[:10]
                    raise RuntimeError(
                        f"verification failed: expected {len(expected)} rows, got {len(after)}; "
                        f"missing ids {missing}, changed ids {changed}")
                if orphans:
                    kept = conn.execute(text(
                        f"SELECT COUNT(*) FROM {ORPHANS} WHERE id IN ({','.join(str(o['id']) for o in orphans)})"
                    )).scalar_one()
                    if kept != len(orphans):
                        raise RuntimeError(f"verification failed: {kept} of {len(orphans)} orphans in {ORPHANS}")
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["status"], report["verified"] = ("migrated" if mode == "detail" else "repaired"), True
        say(f"after:  {report['rows_after']} photo rows, {report['bikes_with_photos']} bikes, "
            f"{len(report['orphans'])} orphans kept in {ORPHANS} — every row kept its id, url and "
            f"display_order and points at its bike")
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
