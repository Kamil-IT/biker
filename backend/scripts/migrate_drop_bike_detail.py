"""Drop the `bike_detail` table: its data moves onto `bike`, components re-keyed to the bike.

`bike_detail` held one row per bike (`description` = the JSON BikeDescription,
`short_description`, timestamps). Now `bike` carries `description` (Text,
nullable - NULL = the bike has no details) and `short_description` (Text NOT
NULL DEFAULT ''), and `bike_detail_component.bike_detail_id` becomes `bike_id`
(FK -> bike.id ON DELETE CASCADE, NOT NULL, indexed). The detail timestamps are
not carried over. `init_db()`'s create_all() never ALTERs an existing table, so
every pre-existing database needs this script once - AFTER
migrate_photos_bike_id.py (`bike_detail_photos` must already be keyed on
bike_id; migrate_short_description.py is optional, a missing column is read as
'') and BEFORE the new backend / searcher run on it. The new searcher refuses
to start on an unmigrated database; the OLD backend breaks on a migrated one.

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_drop_bike_detail.py --dry-run
    python scripts/migrate_drop_bike_detail.py
    python scripts/migrate_drop_bike_detail.py --db path/to/copy.db
    python scripts/migrate_drop_bike_detail.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

How (ONE transaction on both dialects, any failure or failed verification rolls
back and leaves the database unchanged):
  1. add bike.description / bike.short_description when missing;
  2. copy each bike_detail row's description / short_description onto its bike
     (short_description '' when bike_detail has no such column);
  3. re-key bike_detail_component: SQLite rebuilds the table, PostgreSQL does
     ADD COLUMN bike_id -> UPDATE ... FROM bike_detail -> NOT NULL + FK + index
     -> DROP COLUMN bike_detail_id. PostgreSQL takes `LOCK TABLE ... SHARE ROW
     EXCLUSIVE` on bike, bike_detail and bike_detail_component first;
  4. DROP TABLE bike_detail.
Component rows whose bike_detail row (or that row's bike) is missing cannot be
re-keyed: they are listed, copied whole into `bike_detail_component_orphans`
in the same transaction and left out of the migrated table - never dropped
silently. Verified before commit: every bike that had a detail row has the same
description / short_description, and every component row kept its id, bike and
content.

Idempotent: with bike_detail gone, bike's two columns present and the
component table keyed on bike_id with NOT NULL + CASCADE FK + index, the result
is `already-migrated`; a missing piece is repaired. A database without a `bike`
table is left to init_db(). Also importable:
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

COMP = "bike_detail_component"
ORPHANS = "bike_detail_component_orphans"
DETAIL = "bike_detail"
INDEX = "ix_bike_detail_component_bike_id"
FK_NAME = "bike_detail_component_bike_id_fkey"  # the name create_all gives it on PostgreSQL
CONTENT = (
    "category", "subcategory", "component_order", "element_name", "element_description",
    "element_order", "spec_key", "spec_value", "spec_order",
)
_CONTENT_P = ", ".join(f"p.{c}" for c in CONTENT)
_CONTENT_SQL = ", ".join(CONTENT)

_COMP_SNAPSHOT = {
    "detail": f"""
        SELECT p.id, p.bike_detail_id, NULL AS bike_id, b.id AS new_bike_id, {_CONTENT_P}
        FROM {COMP} p
        LEFT JOIN {DETAIL} d ON d.id = p.bike_detail_id
        LEFT JOIN bike b ON b.id = d.bike_id
        ORDER BY p.id""",
    "bike": f"""
        SELECT p.id, NULL AS bike_detail_id, p.bike_id, b.id AS new_bike_id, {_CONTENT_P}
        FROM {COMP} p
        LEFT JOIN bike b ON b.id = p.bike_id
        ORDER BY p.id""",
}

# Same DDL create_all emits for BikeDetailComponent (table-level FOREIGN KEY clause).
_SQLITE_NEW_TABLE = f"""CREATE TABLE {COMP}_new (
    id INTEGER NOT NULL,
    bike_id INTEGER NOT NULL,
    category VARCHAR(255) NOT NULL,
    subcategory VARCHAR(255) NOT NULL,
    component_order INTEGER NOT NULL,
    element_name VARCHAR(512) NOT NULL,
    element_description TEXT NOT NULL,
    element_order INTEGER NOT NULL,
    spec_key VARCHAR(255),
    spec_value VARCHAR(1024),
    spec_order INTEGER,
    PRIMARY KEY (id),
    FOREIGN KEY(bike_id) REFERENCES bike (id) ON DELETE CASCADE
)"""
_SQLITE_COPY = {
    "detail": f"""INSERT INTO {COMP}_new (id, bike_id, {_CONTENT_SQL})
        SELECT p.id, b.id, {_CONTENT_P}
        FROM {COMP} p
        JOIN {DETAIL} d ON d.id = p.bike_detail_id
        JOIN bike b ON b.id = d.bike_id""",
    "bike": f"""INSERT INTO {COMP}_new (id, bike_id, {_CONTENT_SQL})
        SELECT p.id, b.id, {_CONTENT_P}
        FROM {COMP} p
        JOIN bike b ON b.id = p.bike_id""",
}
_INDEXED = ("bike_id", "category", "subcategory", "element_name", "spec_key")


def _sqlite_comp_steps(mode: str) -> list[str]:
    return [
        _SQLITE_NEW_TABLE,
        _SQLITE_COPY[mode],
        f"DROP TABLE {COMP}",
        f"ALTER TABLE {COMP}_new RENAME TO {COMP}",
    ] + [f"CREATE INDEX ix_{COMP}_{c} ON {COMP} ({c})" for c in _INDEXED]


def _pg_comp_steps(mode: str) -> list[str]:
    if mode == "detail":
        rekey = [
            f"ALTER TABLE {COMP} ADD COLUMN IF NOT EXISTS bike_id INTEGER",
            f"""UPDATE {COMP} p SET bike_id = b.id
                FROM {DETAIL} d JOIN bike b ON b.id = d.bike_id
                WHERE d.id = p.bike_detail_id""",
        ]
    else:
        rekey = [f"DELETE FROM {COMP} p WHERE NOT EXISTS (SELECT 1 FROM bike b WHERE b.id = p.bike_id)"]
    tail = [f"ALTER TABLE {COMP} DROP COLUMN bike_detail_id"] if mode == "detail" else []
    return rekey + [
        f"DELETE FROM {COMP} WHERE bike_id IS NULL",  # the orphans, copied to ORPHANS beforehand
        f"ALTER TABLE {COMP} ALTER COLUMN bike_id SET NOT NULL",
        f"ALTER TABLE {COMP} DROP CONSTRAINT IF EXISTS {FK_NAME}",
        f"""ALTER TABLE {COMP} ADD CONSTRAINT {FK_NAME}
            FOREIGN KEY (bike_id) REFERENCES bike (id) ON DELETE CASCADE""",
        f"CREATE INDEX IF NOT EXISTS {INDEX} ON {COMP} (bike_id)",
    ] + tail


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below -
    # pysqlite otherwise commits implicitly around DDL, which would break atomicity.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _schema_gaps(engine, insp) -> list[str]:
    """What a bike_id-keyed component table still lacks: NOT NULL, the CASCADE FK to bike, the index."""
    gaps = []
    col = next(c for c in insp.get_columns(COMP) if c["name"] == "bike_id")
    if col.get("nullable", True):
        gaps.append("bike_id is nullable")
    if engine.dialect.name == "sqlite":
        with engine.connect() as conn:
            fk_ok = any(
                r[2] == "bike" and r[3] == "bike_id" and r[6].upper() == "CASCADE"
                for r in conn.exec_driver_sql(f"PRAGMA foreign_key_list({COMP})")
            )
    else:
        fk_ok = any(
            fk["constrained_columns"] == ["bike_id"] and fk["referred_table"] == "bike"
            and (fk.get("options") or {}).get("ondelete", "").upper() == "CASCADE"
            for fk in insp.get_foreign_keys(COMP)
        )
    if not fk_ok:
        gaps.append("no FK bike_id -> bike.id ON DELETE CASCADE")
    if not any(ix["column_names"] == ["bike_id"] for ix in insp.get_indexes(COMP)):
        gaps.append("no index on bike_id")
    return gaps


def _save_orphans(conn, orphans) -> None:
    """Copy the component rows that cannot be re-keyed into ORPHANS (same transaction)."""
    conn.exec_driver_sql(f"""CREATE TABLE IF NOT EXISTS {ORPHANS} (
        id INTEGER NOT NULL PRIMARY KEY,
        bike_detail_id INTEGER,
        bike_id INTEGER,
        category VARCHAR(255),
        subcategory VARCHAR(255),
        component_order INTEGER,
        element_name VARCHAR(512),
        element_description TEXT,
        element_order INTEGER,
        spec_key VARCHAR(255),
        spec_value VARCHAR(1024),
        spec_order INTEGER
    )""")
    keys = ("id", "bike_detail_id", "bike_id") + CONTENT
    conn.execute(
        text(f"""INSERT INTO {ORPHANS} ({', '.join(keys)})
                 VALUES ({', '.join(':' + k for k in keys)})
                 ON CONFLICT (id) DO NOTHING"""),
        [{k: r[k] for k in keys} for r in orphans],
    )


def migrate(url_or_path=None, dry_run: bool = False, verbose: bool = True) -> dict:
    """Migrate one database; returns a report dict (see the keys below).

    `status` is one of: "migrated", "repaired", "dry-run", "already-migrated",
    "absent", "failed". `orphans` lists the component rows that could not be
    re-keyed as {id, bike_detail_id, bike_id, element_name}; they are kept in
    bike_detail_component_orphans.
    """
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    engine = _engine(url)
    dialect = engine.dialect.name
    report = {
        "database": make_url(url).render_as_string(hide_password=True), "dialect": dialect,
        "status": "", "details_before": 0, "details_after": 0,
        "rows_before": 0, "rows_after": 0, "orphans": [], "verified": False, "gaps": [], "error": None,
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if not insp.has_table("bike"):
            report["status"], report["verified"] = "absent", True
            say("bike does not exist - nothing to migrate; init_db() creates the new layout")
            return report

        bike_cols = {c["name"] for c in insp.get_columns("bike")}
        has_detail = insp.has_table(DETAIL)
        has_comp = insp.has_table(COMP)
        detail_cols = {c["name"] for c in insp.get_columns(DETAIL)} if has_detail else set()
        comp_mode = None  # None = nothing to do for the component table
        if has_comp:
            cols = {c["name"] for c in insp.get_columns(COMP)}
            if "bike_detail_id" in cols:
                if not has_detail:
                    raise RuntimeError(f"{COMP} has bike_detail_id but {DETAIL} is missing - unknown schema")
                comp_mode = "detail"
            elif "bike_id" in cols:
                report["gaps"] = _schema_gaps(engine, insp)
                if report["gaps"]:
                    comp_mode = "bike"
            else:
                raise RuntimeError(f"{COMP} has neither bike_detail_id nor bike_id - unknown schema {sorted(cols)}")
        if has_detail and insp.has_table("bike_detail_photos"):
            if "bike_detail_id" in {c["name"] for c in insp.get_columns("bike_detail_photos")}:
                raise RuntimeError("bike_detail_photos is still keyed on bike_detail_id - "
                                   "run scripts/migrate_photos_bike_id.py first")

        need_cols = [c for c in ("description", "short_description") if c not in bike_cols]
        if not (need_cols or has_detail or comp_mode):
            with engine.connect() as conn:
                if "description" in bike_cols:
                    report["details_before"] = report["details_after"] = conn.execute(
                        text("SELECT COUNT(*) FROM bike WHERE description IS NOT NULL")).scalar_one()
                if has_comp:
                    report["rows_before"] = report["rows_after"] = conn.execute(
                        text(f"SELECT COUNT(*) FROM {COMP}")).scalar_one()
            report["status"], report["verified"] = "already-migrated", True
            say(f"already migrated: {DETAIL} gone, bike has description/short_description, {COMP} keyed on "
                f"bike_id with NOT NULL + FK + index ({report['details_after']} bikes with details, "
                f"{report['rows_after']} component rows) - nothing to do")
            return report
        if comp_mode == "bike":
            say(f"{COMP} keyed on bike_id but incomplete: {'; '.join(report['gaps'])} - repairing")

        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                if dialect == "postgresql":
                    tables = ["bike"] + ([DETAIL] if has_detail else []) + ([COMP] if has_comp else [])
                    conn.exec_driver_sql(f"LOCK TABLE {', '.join(tables)} IN SHARE ROW EXCLUSIVE MODE")

                # -- snapshots -------------------------------------------------
                expected_details = {}
                if has_detail:
                    sd = "d.short_description" if "short_description" in detail_cols else "''"
                    expected_details = {
                        r.bike_id: (r.description, r.sd or "")
                        for r in conn.execute(text(
                            f"SELECT d.bike_id, d.description, {sd} AS sd FROM {DETAIL} d "
                            "JOIN bike b ON b.id = d.bike_id"))
                    }
                    report["details_before"] = len(expected_details)
                expected, orphans = {}, []
                if comp_mode:
                    snapshot = conn.execute(text(_COMP_SNAPSHOT[comp_mode])).mappings().all()
                    report["rows_before"] = len(snapshot)
                    orphans = [r for r in snapshot if r["new_bike_id"] is None]
                    report["orphans"] = [
                        {k: r[k] for k in ("id", "bike_detail_id", "bike_id", "element_name")} for r in orphans
                    ]
                    expected = {
                        r["id"]: (r["new_bike_id"],) + tuple(r[c] for c in CONTENT)
                        for r in snapshot if r["new_bike_id"] is not None
                    }
                elif has_comp:
                    report["rows_before"] = conn.execute(text(f"SELECT COUNT(*) FROM {COMP}")).scalar_one()
                say(f"before: {len(expected_details)} bike_detail rows, {report['rows_before']} component rows, "
                    f"{len(orphans)} orphan component rows")
                for o in report["orphans"]:
                    say(f"  orphan (no detail row / bike) - moved to {ORPHANS}: id={o['id']} "
                        f"bike_detail_id={o['bike_detail_id']} bike_id={o['bike_id']} element={o['element_name']}")

                if dry_run:
                    conn.exec_driver_sql("ROLLBACK")
                    report["status"], report["rows_after"] = "dry-run", len(expected) or report["rows_before"]
                    report["details_after"], report["verified"] = len(expected_details), True
                    say(f"dry run: would add {need_cols or 'no'} bike columns, copy {len(expected_details)} details "
                        f"onto their bikes, re-key {len(expected)} component rows (mode={comp_mode}), move "
                        f"{len(orphans)} orphans to {ORPHANS}, drop {DETAIL if has_detail else '(nothing)'} - "
                        "nothing written")
                    return report

                # -- migrate ---------------------------------------------------
                if "description" in need_cols:
                    conn.exec_driver_sql("ALTER TABLE bike ADD COLUMN description TEXT")
                if "short_description" in need_cols:
                    conn.exec_driver_sql("ALTER TABLE bike ADD COLUMN short_description TEXT NOT NULL DEFAULT ''")
                if has_detail:
                    sd = "d.short_description" if "short_description" in detail_cols else "''"
                    conn.exec_driver_sql(f"""UPDATE bike SET
                        description = (SELECT d.description FROM {DETAIL} d WHERE d.bike_id = bike.id),
                        short_description = COALESCE((SELECT {sd} FROM {DETAIL} d WHERE d.bike_id = bike.id), '')
                        WHERE EXISTS (SELECT 1 FROM {DETAIL} d WHERE d.bike_id = bike.id)""")
                if orphans:
                    _save_orphans(conn, orphans)
                if comp_mode:
                    for sql in (_sqlite_comp_steps(comp_mode) if dialect == "sqlite" else _pg_comp_steps(comp_mode)):
                        conn.exec_driver_sql(sql)
                if has_detail:
                    conn.exec_driver_sql(f"DROP TABLE {DETAIL}")

                # -- verify ----------------------------------------------------
                after_details = {
                    r.id: (r.description, r.short_description)
                    for r in conn.execute(text("SELECT id, description, short_description FROM bike"))
                    if r.id in expected_details
                }
                if after_details != expected_details:
                    bad = sorted(i for i in expected_details if after_details.get(i) != expected_details[i])[:10]
                    raise RuntimeError(f"verification failed: description/short_description differ for bike ids {bad}")
                report["details_after"] = len(after_details)
                if comp_mode:
                    keys = ", ".join(("id", "bike_id") + CONTENT)
                    after = {
                        r[0]: tuple(r[1:])
                        for r in conn.execute(text(f"SELECT {keys} FROM {COMP}"))
                    }
                    report["rows_after"] = len(after)
                    if after != expected:
                        missing = sorted(set(expected) - set(after))[:10]
                        changed = sorted(i for i in set(expected) & set(after) if expected[i] != after[i])[:10]
                        raise RuntimeError(
                            f"verification failed: expected {len(expected)} component rows, got {len(after)}; "
                            f"missing ids {missing}, changed ids {changed}")
                    if orphans:
                        kept = conn.execute(text(
                            f"SELECT COUNT(*) FROM {ORPHANS} WHERE id IN ({','.join(str(o['id']) for o in orphans)})"
                        )).scalar_one()
                        if kept != len(orphans):
                            raise RuntimeError(f"verification failed: {kept} of {len(orphans)} orphans in {ORPHANS}")
                elif has_comp:
                    report["rows_after"] = conn.execute(text(f"SELECT COUNT(*) FROM {COMP}")).scalar_one()
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["status"] = "migrated" if (has_detail or comp_mode == "detail") else "repaired"
        report["verified"] = True
        say(f"after:  {report['details_after']} details on bike, {report['rows_after']} component rows, "
            f"{len(report['orphans'])} orphans kept in {ORPHANS}, {DETAIL} dropped - descriptions and "
            "component rows verified identical")
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
