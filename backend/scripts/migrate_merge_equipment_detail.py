"""Merge `equipment_detail` into `equipment` and rename `equipment_detail_component` to `equipment_component` (TODO-044).

Before: `equipment` (identity: category + company_norm + model_norm, UNIQUE
`uq_equipment_identity`) had a one-to-one `equipment_detail` row (description,
short_description, timestamps) and `equipment_detail_component` keyed on
`equipment_detail_id`. After:

  * `equipment` gains `description` (Text, nullable - NULL = the item has no
    details, like `bike.description`), `short_description` (Text NOT NULL
    DEFAULT ''), `updated_at`, and the lookup identity `name` / `name_norm`
    (the element name from a bike's spec tree, the only source of an equipment
    row; backfilled from model - or "company model" for a row that has a
    company - with the Python normalisation, never SQL lower()). The unique
    constraint becomes `uq_equipment_name` (category, name_norm);
    `uq_equipment_identity` is dropped. `company` / `model` stay: they are now
    the researched brand and model, filled by the next details search.
  * `equipment_component` = the flat columns of `equipment_detail_component`
    keyed on `equipment_id` (FK -> equipment.id ON DELETE CASCADE, NOT NULL,
    indexed), every row keeping its id.
  * `equipment_detail` and `equipment_detail_component` are dropped.
    `equipment_detail_photos` and `bike_component.equipment_id` are untouched.

`init_db()`'s create_all() never ALTERs an existing table, so every
pre-existing database needs this script once - AFTER migrate_equipment_tables.py,
migrate_drop_bike_detail.py and migrate_rename_bike_component.py - and BEFORE
the new backend / searcher run on it. The new searcher refuses to start on an
unmigrated database; the OLD backend breaks on a migrated one (and its
create_all() recreates the empty `equipment_detail*` tables - rerun this script,
it drops them: `repaired`).

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_merge_equipment_detail.py --dry-run
    python scripts/migrate_merge_equipment_detail.py
    python scripts/migrate_merge_equipment_detail.py --db path/to/copy.db
    python scripts/migrate_merge_equipment_detail.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

How (ONE transaction on both dialects, any failure or failed verification rolls
back and leaves the database unchanged): SQLite rebuilds `equipment`,
PostgreSQL alters it in place under `LOCK TABLE equipment, equipment_detail,
equipment_detail_component IN SHARE ROW EXCLUSIVE MODE`; then `equipment_component`
is created from the ORM model, filled with INSERT ... SELECT (PostgreSQL: the id
sequence is reset), and the two old tables are dropped. Component rows whose
detail row (or its equipment) is missing cannot be re-keyed: they are listed,
copied whole into `equipment_component_orphans` in the same transaction and
left out of the new table - never dropped silently. Verified before commit:
every equipment row keeps its columns and has the description / short
description of its old detail row (NULL / '' without one), and every component
row kept its id, equipment and content.

Refused (exit 1, nothing written): `bike_detail_component` not yet renamed to
`bike_component`; two rows that would share (category, name_norm); an
`equipment_component` / `equipment_detail*` table that holds rows although it
should be empty or gone.

Idempotent: `equipment` has `name` and the old tables are gone = `already-migrated`;
leftover empty old tables, or a missing `equipment_component`, are repaired
(`repaired`). A database without `equipment` is left to init_db() (`absent`).
Also importable: `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`.

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

from app.equipment_models import EquipmentComponent  # noqa: E402
from app.models import DEFAULT_DB_PATH, Base, norm  # noqa: E402

EQUIP = "equipment"
DETAIL = "equipment_detail"
OLD_COMP = "equipment_detail_component"
NEW_COMP = "equipment_component"
ORPHANS = "equipment_component_orphans"
OLD_UNIQUE = "uq_equipment_identity"
NEW_UNIQUE = "uq_equipment_name"
CONTENT = (
    "category", "subcategory", "component_order", "element_name", "element_description",
    "element_order", "spec_key", "spec_value", "spec_order",
)
_CONTENT_P = ", ".join(f"p.{c}" for c in CONTENT)
_CONTENT_SQL = ", ".join(CONTENT)
# What an equipment row must read back as after the merge (id -> this tuple).
_EQ_FIELDS = ("category", "name", "name_norm", "company", "model", "company_norm", "model_norm",
              "description", "short_description")

_NEW_EQUIPMENT_SQLITE = f"""CREATE TABLE {EQUIP}_new (
    id INTEGER NOT NULL,
    category VARCHAR(32) NOT NULL,
    name VARCHAR(512) NOT NULL,
    name_norm VARCHAR(512) NOT NULL,
    company VARCHAR(255) NOT NULL,
    model VARCHAR(512) NOT NULL,
    company_norm VARCHAR(255) NOT NULL,
    model_norm VARCHAR(512) NOT NULL,
    description TEXT,
    short_description TEXT DEFAULT '' NOT NULL,
    created_at DATETIME,
    updated_at DATETIME,
    PRIMARY KEY (id),
    CONSTRAINT {NEW_UNIQUE} UNIQUE (category, name_norm)
)"""


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below -
    # pysqlite otherwise commits implicitly around DDL, which would break atomicity.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def _name_for(company: str, model: str) -> str:
    """The lookup name of an old row: the model, or "company model" when it has a company."""
    company, model = (company or "").strip(), (model or "").strip()
    return f"{company} {model}" if company else model


def _expected(rows, details: dict) -> dict:
    """id -> the tuple of _EQ_FIELDS the merged row must hold; raises on a (category, name_norm) collision."""
    out, seen = {}, {}
    for r in rows:
        name = _name_for(r["company"], r["model"])
        key = (r["category"], norm(name))
        if key in seen:
            raise RuntimeError(
                f"equipment ids {seen[key]} and {r['id']} would share (category, name_norm) = {key!r} - "
                "resolve the duplicate by hand first")
        seen[key] = r["id"]
        desc, short = details.get(r["id"], (None, ""))
        out[r["id"]] = (r["category"], name, norm(name), r["company"], r["model"], r["company_norm"],
                        r["model_norm"], desc, short or "")
    return out


def _save_orphans(conn, orphans) -> None:
    """Copy the component rows that cannot be re-keyed into ORPHANS (same transaction)."""
    conn.exec_driver_sql(f"""CREATE TABLE IF NOT EXISTS {ORPHANS} (
        id INTEGER NOT NULL PRIMARY KEY,
        equipment_detail_id INTEGER,
        equipment_id INTEGER,
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
    keys = ("id", "equipment_detail_id", "equipment_id") + CONTENT
    conn.execute(
        text(f"""INSERT INTO {ORPHANS} ({', '.join(keys)})
                 VALUES ({', '.join(':' + k for k in keys)})
                 ON CONFLICT (id) DO NOTHING"""),
        [{k: r[k] for k in keys} for r in orphans],
    )


def _rebuild_equipment_sqlite(conn, rows, expected: dict) -> None:
    """SQLite cannot swap a table-level UNIQUE in place: build equipment_new, copy, drop, rename."""
    conn.exec_driver_sql(_NEW_EQUIPMENT_SQLITE)
    if rows:  # an empty executemany raises "A value is required for bind parameter"
        conn.execute(text(
            f"""INSERT INTO {EQUIP}_new (id, category, name, name_norm, company, model, company_norm, model_norm,
                    description, short_description, created_at, updated_at)
                VALUES (:id, :category, :name, :name_norm, :company, :model, :company_norm, :model_norm,
                    :description, :short_description, :created_at, :updated_at)"""),
            [{**{k: r[k] for k in ("id", "company", "model", "company_norm", "model_norm", "created_at")},
              "updated_at": r["updated_at"], **dict(zip(_EQ_FIELDS, expected[r["id"]]))} for r in rows],
        )
    conn.exec_driver_sql(f"DROP TABLE {EQUIP}")
    conn.exec_driver_sql(f"ALTER TABLE {EQUIP}_new RENAME TO {EQUIP}")


def _alter_equipment_pg(conn, rows, expected: dict, has_detail: bool) -> None:
    for col, ddl in (("name", "VARCHAR(512)"), ("name_norm", "VARCHAR(512)"), ("description", "TEXT"),
                     ("short_description", "TEXT NOT NULL DEFAULT ''"), ("updated_at", "TIMESTAMP")):
        conn.exec_driver_sql(f"ALTER TABLE {EQUIP} ADD COLUMN IF NOT EXISTS {col} {ddl}")
    if has_detail:
        conn.exec_driver_sql(f"""UPDATE {EQUIP} e SET description = d.description,
            short_description = COALESCE(d.short_description, ''), updated_at = d.updated_at
            FROM {DETAIL} d WHERE d.equipment_id = e.id""")
    conn.exec_driver_sql(f"UPDATE {EQUIP} SET updated_at = created_at WHERE updated_at IS NULL")
    if expected:
        conn.execute(text(f"UPDATE {EQUIP} SET name = :name, name_norm = :name_norm WHERE id = :id"),
                     [{"id": i, "name": v[1], "name_norm": v[2]} for i, v in expected.items()])
    conn.exec_driver_sql(f"ALTER TABLE {EQUIP} ALTER COLUMN name SET NOT NULL")
    conn.exec_driver_sql(f"ALTER TABLE {EQUIP} ALTER COLUMN name_norm SET NOT NULL")
    conn.exec_driver_sql(f"ALTER TABLE {EQUIP} DROP CONSTRAINT IF EXISTS {OLD_UNIQUE}")
    conn.exec_driver_sql(f"ALTER TABLE {EQUIP} ADD CONSTRAINT {NEW_UNIQUE} UNIQUE (category, name_norm)")


def _snapshot(conn, has_detail: bool, has_old_comp: bool):
    """(equipment rows, id -> (description, short_description), component rows with their new equipment id)."""
    updated = "COALESCE(d.updated_at, e.created_at)" if has_detail else "e.created_at"
    rows = conn.execute(text(
        f"""SELECT e.id, e.category, e.company, e.model, e.company_norm, e.model_norm, e.created_at,
                   {updated} AS updated_at
            FROM {EQUIP} e {f'LEFT JOIN {DETAIL} d ON d.equipment_id = e.id' if has_detail else ''}
            ORDER BY e.id""")).mappings().all()
    details = {}
    if has_detail:
        details = {r.equipment_id: (r.description, r.short_description or "") for r in conn.execute(text(
            f"SELECT d.equipment_id, d.description, d.short_description FROM {DETAIL} d "
            f"JOIN {EQUIP} e ON e.id = d.equipment_id"))}
        lost = _count(conn, DETAIL) - len(details)
        if lost:
            raise RuntimeError(f"{lost} {DETAIL} rows point at no equipment row - clean them up first")
    comps = []
    if has_old_comp:
        comps = conn.execute(text(
            f"""SELECT p.id, p.equipment_detail_id, NULL AS equipment_id, e.id AS new_equipment_id, {_CONTENT_P}
                FROM {OLD_COMP} p
                LEFT JOIN {DETAIL} d ON d.id = p.equipment_detail_id
                LEFT JOIN {EQUIP} e ON e.id = d.equipment_id
                ORDER BY p.id""")).mappings().all()
    return rows, details, comps


def _other_counts(conn, insp) -> tuple[int, int]:
    """(photo rows, bike_component rows linked to equipment) - must not change."""
    photos = _count(conn, "equipment_detail_photos") if insp.has_table("equipment_detail_photos") else 0
    linked = 0
    if insp.has_table("bike_component"):
        linked = conn.execute(text("SELECT COUNT(*) FROM bike_component WHERE equipment_id IS NOT NULL")).scalar_one()
    return photos, linked


def _repair(engine, insp, report, say, dry_run: bool, has_detail: bool, has_old_comp: bool, has_new_comp: bool) -> dict:
    """The equipment table is already merged: drop empty leftovers of the old code, create a missing equipment_component."""
    leftovers = [t for t, present in ((OLD_COMP, has_old_comp), (DETAIL, has_detail)) if present]
    with engine.connect() as conn:
        for t in leftovers:
            if _count(conn, t):
                raise RuntimeError(f"{t} still has rows although {EQUIP} is already merged - not dropping it, "
                                   "inspect it by hand")
        report["equipment_before"] = report["equipment_after"] = _count(conn, EQUIP)
        if has_new_comp:
            report["rows_before"] = report["rows_after"] = _count(conn, NEW_COMP)
    if not leftovers and has_new_comp:
        report["status"], report["verified"] = "already-migrated", True
        say(f"already migrated: {EQUIP} has name, {DETAIL} / {OLD_COMP} gone, {NEW_COMP} present "
            f"({report['equipment_after']} equipment rows, {report['rows_after']} component rows) - nothing to do")
        return report
    todo = [f"drop the empty {t}" for t in leftovers] + ([] if has_new_comp else [f"create {NEW_COMP}"])
    if dry_run:
        report["status"], report["verified"] = "dry-run", True
        say(f"dry run: {EQUIP} is merged; would " + ", ".join(todo) + " - nothing written")
        return report
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN IMMEDIATE" if engine.dialect.name == "sqlite" else "BEGIN")
        try:
            for t in leftovers:
                conn.exec_driver_sql(f"DROP TABLE {t}")
            if not has_new_comp:
                Base.metadata.create_all(conn, tables=[EquipmentComponent.__table__], checkfirst=True)
            conn.exec_driver_sql("COMMIT")
        except BaseException:
            conn.exec_driver_sql("ROLLBACK")
            raise
    report["status"], report["verified"] = "repaired", True
    say("repaired: " + ", ".join(todo))
    return report


def migrate(url_or_path=None, dry_run: bool = False, verbose: bool = True) -> dict:
    """Migrate one database; returns a report dict (see the keys below).

    `status` is one of: "migrated", "repaired", "dry-run", "already-migrated",
    "absent", "failed". `orphans` lists the component rows that could not be
    re-keyed as {id, equipment_detail_id, equipment_id, element_name}; they are
    kept in equipment_component_orphans.
    """
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    engine = _engine(url)
    dialect = engine.dialect.name
    report = {
        "database": make_url(url).render_as_string(hide_password=True), "dialect": dialect,
        "status": "", "equipment_before": 0, "equipment_after": 0, "details_before": 0,
        "rows_before": 0, "rows_after": 0, "orphans": [], "verified": False, "error": None,
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if not insp.has_table(EQUIP):
            report["status"], report["verified"] = "absent", True
            say(f"{EQUIP} does not exist - nothing to migrate; init_db() creates the new layout")
            return report
        if insp.has_table("bike_detail_component") and not insp.has_table("bike_component"):
            raise RuntimeError("bike_detail_component is not renamed yet - run "
                               "scripts/migrate_rename_bike_component.py first")
        has_detail, has_old_comp, has_new_comp = (insp.has_table(t) for t in (DETAIL, OLD_COMP, NEW_COMP))
        if "name" in {c["name"] for c in insp.get_columns(EQUIP)}:
            return _repair(engine, insp, report, say, dry_run, has_detail, has_old_comp, has_new_comp)
        if has_old_comp and not has_detail:
            raise RuntimeError(f"{OLD_COMP} exists but {DETAIL} is missing - unknown schema")
        if has_old_comp and "equipment_detail_id" not in {c["name"] for c in insp.get_columns(OLD_COMP)}:
            raise RuntimeError(f"{OLD_COMP} is not keyed on equipment_detail_id - unknown schema")
        if has_new_comp and "equipment_id" not in {c["name"] for c in insp.get_columns(NEW_COMP)}:
            raise RuntimeError(f"{NEW_COMP} exists without equipment_id - unknown schema")

        with engine.connect() as conn:
            if dialect == "sqlite":
                conn.exec_driver_sql("PRAGMA foreign_keys=OFF")  # no-op inside a transaction, so before BEGIN
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                if dialect == "postgresql":
                    tables = [EQUIP] + [t for t, present in ((DETAIL, has_detail), (OLD_COMP, has_old_comp)) if present]
                    conn.exec_driver_sql(f"LOCK TABLE {', '.join(tables)} IN SHARE ROW EXCLUSIVE MODE")
                if has_new_comp and _count(conn, NEW_COMP):
                    raise RuntimeError(f"{NEW_COMP} already holds rows although {EQUIP} is not merged - unknown state")

                # -- snapshots -------------------------------------------------
                rows, details, comps = _snapshot(conn, has_detail, has_old_comp)
                expected = _expected(rows, details)
                orphans = [r for r in comps if r["new_equipment_id"] is None]
                expected_comp = {
                    r["id"]: (r["new_equipment_id"],) + tuple(r[c] for c in CONTENT)
                    for r in comps if r["new_equipment_id"] is not None
                }
                other_before = _other_counts(conn, insp)
                report.update(
                    equipment_before=len(rows), details_before=len(details), rows_before=len(comps),
                    orphans=[{k: r[k] for k in ("id", "equipment_detail_id", "equipment_id", "element_name")}
                             for r in orphans])
                say(f"before: {len(rows)} equipment rows, {len(details)} detail rows, {len(comps)} component rows, "
                    f"{len(orphans)} orphan component rows")
                for o in report["orphans"]:
                    say(f"  orphan (no detail row / equipment) - moved to {ORPHANS}: id={o['id']} "
                        f"equipment_detail_id={o['equipment_detail_id']} element={o['element_name']}")

                if dry_run:
                    conn.exec_driver_sql("ROLLBACK")
                    report.update(status="dry-run", equipment_after=len(rows), rows_after=len(expected_comp),
                                  verified=True)
                    say(f"dry run: would merge {len(details)} details into {len(rows)} equipment rows (name backfilled), "
                        f"re-key {len(expected_comp)} component rows into {NEW_COMP}, move {len(orphans)} orphans to "
                        f"{ORPHANS}, drop {DETAIL} and {OLD_COMP} - nothing written")
                    return report

                # -- migrate ---------------------------------------------------
                if has_new_comp:
                    conn.exec_driver_sql(f"DROP TABLE {NEW_COMP}")  # an empty one the new backend created too early
                if dialect == "sqlite":
                    _rebuild_equipment_sqlite(conn, rows, expected)
                else:
                    _alter_equipment_pg(conn, rows, expected, has_detail)
                Base.metadata.create_all(conn, tables=[EquipmentComponent.__table__], checkfirst=True)
                if orphans:
                    _save_orphans(conn, orphans)
                if has_old_comp:
                    conn.exec_driver_sql(f"""INSERT INTO {NEW_COMP} (id, equipment_id, {_CONTENT_SQL})
                        SELECT p.id, e.id, {_CONTENT_P}
                        FROM {OLD_COMP} p
                        JOIN {DETAIL} d ON d.id = p.equipment_detail_id
                        JOIN {EQUIP} e ON e.id = d.equipment_id""")
                    if dialect == "postgresql":
                        conn.exec_driver_sql(
                            f"SELECT setval(pg_get_serial_sequence('{NEW_COMP}', 'id'), "
                            f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {NEW_COMP}")
                    conn.exec_driver_sql(f"DROP TABLE {OLD_COMP}")
                if has_detail:
                    conn.exec_driver_sql(f"DROP TABLE {DETAIL}")

                # -- verify ----------------------------------------------------
                after = {
                    r.id: tuple(getattr(r, f) for f in _EQ_FIELDS)
                    for r in conn.execute(text(f"SELECT id, {', '.join(_EQ_FIELDS)} FROM {EQUIP}"))
                }
                if after != expected:
                    bad = sorted(i for i in set(expected) | set(after) if after.get(i) != expected.get(i))[:10]
                    raise RuntimeError(f"verification failed: equipment rows differ for ids {bad}")
                keys = ", ".join(("id", "equipment_id") + CONTENT)
                comps_after = {r[0]: tuple(r[1:]) for r in conn.execute(text(f"SELECT {keys} FROM {NEW_COMP}"))}
                if comps_after != expected_comp:
                    missing = sorted(set(expected_comp) - set(comps_after))[:10]
                    changed = sorted(i for i in set(expected_comp) & set(comps_after)
                                     if expected_comp[i] != comps_after[i])[:10]
                    raise RuntimeError(
                        f"verification failed: expected {len(expected_comp)} component rows, got {len(comps_after)}; "
                        f"missing ids {missing}, changed ids {changed}")
                if orphans:
                    kept = conn.execute(text(
                        f"SELECT COUNT(*) FROM {ORPHANS} WHERE id IN ({','.join(str(o['id']) for o in orphans)})"
                    )).scalar_one()
                    if kept != len(orphans):
                        raise RuntimeError(f"verification failed: {kept} of {len(orphans)} orphans in {ORPHANS}")
                if _other_counts(conn, insp) != other_before:
                    raise RuntimeError("verification failed: photo / bike_component link counts changed")
                report["equipment_after"], report["rows_after"] = len(after), len(comps_after)
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["status"], report["verified"] = "migrated", True
        say(f"after:  {report['equipment_after']} equipment rows (descriptions merged from {report['details_before']} "
            f"details), {report['rows_after']} rows in {NEW_COMP}, {len(report['orphans'])} orphans kept in "
            f"{ORPHANS}, {DETAIL} and {OLD_COMP} dropped - verified identical")
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
