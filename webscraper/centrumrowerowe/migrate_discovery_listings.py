"""Split the TODO-036 `bike_discovery` table into the bike and its shop listings (TODO-039).

Every old row's shop columns (source, source_product_id, raw_name, details_link, price,
first_seen_at, last_seen_at) move into one `bike_discovery_listing` row linked to it; the
bike row gets company_norm / model_norm and loses those columns and UNIQUE(source,
source_product_id) in favour of UNIQUE(company_norm, model_norm). Rows that collapse to the
same normalised identity are merged: the one with the highest status (done > skipped >
failed > in_progress > pending, then the lowest id) survives and gets every listing; it keeps
its bike_id, or takes the first one a merged row had.

One transaction, verified before commit (one listing per old row, every listing linked, no
bike lost its bike_id), rolled back on any mismatch. Idempotent: an already migrated database
is reported and left alone. SQLite is rebuilt (it cannot drop a constraint); PostgreSQL is
altered in place under an ACCESS EXCLUSIVE lock.

    python migrate_discovery_listings.py --dry-run          # run everything, report, roll back
    python migrate_discovery_listings.py
    python migrate_discovery_listings.py --url postgresql+psycopg://biker@127.0.0.1:6543/biker --allow-remote
"""
import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402  (puts backend/ on sys.path, loads backend/.env)
from db import (  # noqa: E402
    DONE, FAILED, IN_PROGRESS, PENDING, SKIPPED, BikeDiscovery, BikeDiscoveryListing, models, norm,
)
from sqlalchemy import MetaData, Table, func, inspect, select  # noqa: E402

TABLE = BikeDiscovery.__tablename__
OLD_TABLE = "bike_discovery_old"  # SQLite: the old table while the new one is filled
STATUS_INDEX = "ix_bike_discovery_status_next_attempt"
MOVED_COLUMNS = ("source", "source_product_id", "raw_name", "details_link", "price", "first_seen_at", "last_seen_at")
STATUS_RANK = {DONE: 4, SKIPPED: 3, FAILED: 2, IN_PROGRESS: 1, PENDING: 0}

MIGRATED, DRY_RUN, ALREADY, NO_TABLE = "migrated", "dry run", "already migrated", "no table"


class MigrationError(Exception):
    """The moved data did not verify; the transaction was rolled back."""


def plan(rows: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Old rows → (new bike rows, listing rows, stats). Pure, no database.

    stats: "survivor" (old id → surviving id), "merged_groups" (identities with > 1 row),
    "bike_id_conflicts" (merged groups whose rows pointed at different bikes).
    """
    groups = defaultdict(list)
    for row in sorted(rows, key=lambda r: r["id"]):
        groups[(norm(row["company"]), norm(row["model"]))].append(row)
    bikes, listings = [], []
    stats = {"survivor": {}, "merged_groups": 0, "bike_id_conflicts": 0}
    for (company_norm, model_norm), members in groups.items():
        ranked = sorted(members, key=lambda r: (-STATUS_RANK.get(r["status"], -1), r["id"]))
        head = ranked[0]
        bike_ids = {m["bike_id"] for m in members if m["bike_id"] is not None}
        stats["merged_groups"] += len(members) > 1
        stats["bike_id_conflicts"] += len(bike_ids) > 1
        bikes.append({
            "id": head["id"], "company": head["company"], "model": head["model"],
            "company_norm": company_norm, "model_norm": model_norm,
            "bike_type": next((m["bike_type"] for m in ranked if m["bike_type"]), None),
            "bike_id": next((m["bike_id"] for m in ranked if m["bike_id"] is not None), None),
            "status": head["status"], "attempts": head["attempts"], "last_error": head["last_error"],
            "locked_at": head["locked_at"], "next_attempt_at": head["next_attempt_at"],
            "created_at": min(m["first_seen_at"] for m in members), "updated_at": head["updated_at"],
        })
        for m in members:
            stats["survivor"][m["id"]] = head["id"]
            listings.append((m["id"], {"discovery_id": head["id"], **{c: m[c] for c in MOVED_COLUMNS},
                                       "updated_at": m["updated_at"], "fetched_at": None, "fetch_error": None}))
    listings.sort(key=lambda pair: pair[0])  # listing ids follow the old row ids
    return bikes, [listing for _, listing in listings], stats


def _rebuild_sqlite(conn) -> None:
    """SQLite cannot drop a constraint: move the old table aside and create the new one."""
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} RENAME TO {OLD_TABLE}")
    conn.exec_driver_sql(f"DROP INDEX IF EXISTS {STATUS_INDEX}")  # renamed along; the new table recreates it
    BikeDiscovery.__table__.create(conn)


def _alter_postgres(conn) -> None:
    """Drop the moved columns and the old unique constraint, add the identity columns; rows emptied."""
    for uc in inspect(conn).get_unique_constraints(TABLE):
        if set(uc["column_names"]) & set(MOVED_COLUMNS):
            conn.exec_driver_sql(f'ALTER TABLE {TABLE} DROP CONSTRAINT "{uc["name"]}"')
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} " + ", ".join(f"DROP COLUMN {c}" for c in MOVED_COLUMNS))
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD COLUMN company_norm VARCHAR({db.NORM_LEN}), "
                         f"ADD COLUMN model_norm VARCHAR({db.NORM_LEN}), "
                         "ADD COLUMN created_at TIMESTAMP WITHOUT TIME ZONE")
    conn.exec_driver_sql(f"DELETE FROM {TABLE}")  # refilled with the merged rows, ids kept


def _constrain_postgres(conn) -> None:
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} ALTER COLUMN company_norm SET NOT NULL, "
                         "ALTER COLUMN model_norm SET NOT NULL, ALTER COLUMN created_at SET NOT NULL")
    conn.exec_driver_sql(f"ALTER TABLE {TABLE} ADD CONSTRAINT uq_bike_discovery_identity "
                         "UNIQUE (company_norm, model_norm)")
    conn.exec_driver_sql(f"CREATE INDEX IF NOT EXISTS {STATUS_INDEX} ON {TABLE} (status, next_attempt_at)")


def _verify(conn, rows: list[dict], bikes: list[dict], stats: dict) -> None:
    bike_t, listing_t = BikeDiscovery.__table__, BikeDiscoveryListing.__table__
    n_listings = conn.execute(select(func.count()).select_from(listing_t)).scalar()
    if n_listings != len(rows):
        raise MigrationError(f"{n_listings} listings for {len(rows)} old rows")
    n_bikes = conn.execute(select(func.count()).select_from(bike_t)).scalar()
    if n_bikes != len(bikes):
        raise MigrationError(f"{n_bikes} bike rows, expected {len(bikes)}")
    orphans = conn.execute(select(func.count()).select_from(listing_t).where(
        listing_t.c.discovery_id.not_in(select(bike_t.c.id)))).scalar()
    if orphans:
        raise MigrationError(f"{orphans} listings are not linked to a bike row")
    new_rows = {i: (bike_id, status) for i, bike_id, status in
                conn.execute(select(bike_t.c.id, bike_t.c.bike_id, bike_t.c.status)).all()}
    lost = [r["id"] for r in rows if r["bike_id"] is not None and new_rows[stats["survivor"][r["id"]]][0] is None]
    if lost:
        raise MigrationError(f"old rows {lost[:10]} would lose their bike_id")
    rank = lambda status: STATUS_RANK.get(status, -1)  # noqa: E731
    downgraded = [r["id"] for r in rows if rank(new_rows[stats["survivor"][r["id"]]][1]) < rank(r["status"])]
    if downgraded:
        raise MigrationError(f"old rows {downgraded[:10]} would lose their status")
    # Per-status counts, derived from the old rows independently of plan(): each identity keeps its best status.
    groups = defaultdict(list)
    for r in rows:
        groups[(norm(r["company"]), norm(r["model"]))].append(r["status"])
    expected = Counter(max(statuses, key=rank) for statuses in groups.values())
    actual = Counter(status for _, status in new_rows.values())
    if actual != expected:
        raise MigrationError(f"statuses after the merge {dict(actual)} differ from the expected {dict(expected)}")


def migrate(dry_run: bool = False, verbose: bool = True) -> dict:
    """Migrate the backend's current database; returns a summary dict ("status" + counts).

    Raises MigrationError (rolled back) when the moved data does not verify.
    """
    say = print if verbose else (lambda *a, **k: None)
    engine = models.get_engine()
    insp = inspect(engine)
    if not insp.has_table(TABLE):
        say(f"{TABLE} does not exist — nothing to migrate")
        return {"status": NO_TABLE}
    if not db.has_old_layout(engine):
        say(f"{TABLE} is already migrated — nothing to do")
        return {"status": ALREADY}
    sqlite = engine.dialect.name == "sqlite"
    with engine.connect() as conn:
        # Locked before the rows are read, so no write can land between the read and the rebuild.
        if sqlite:  # pysqlite would run the DDL outside the transaction (autocommit) otherwise
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            if not sqlite:  # fail fast rather than queue every reader behind a stuck session
                conn.exec_driver_sql("SET LOCAL lock_timeout = '10s'")
                conn.exec_driver_sql(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE")
            if not db.has_old_layout(conn):  # another run migrated it while we waited for the lock
                conn.rollback()
                say(f"{TABLE} is already migrated — nothing to do")
                return {"status": ALREADY}
            old = Table(TABLE, MetaData(), autoload_with=conn)
            rows = [dict(r._mapping) for r in conn.execute(select(old).order_by(old.c.id))]
            if inspect(conn).has_table(BikeDiscoveryListing.__tablename__):
                if conn.execute(select(func.count()).select_from(BikeDiscoveryListing.__table__)).scalar():
                    raise MigrationError("bike_discovery_listing already holds rows next to the old layout")
                # Empty: dropped and recreated below — if kept, SQLite's rename would repoint its FK
                # at bike_discovery_old.
                BikeDiscoveryListing.__table__.drop(conn)
            bikes, listings, stats = plan(rows)
            if sqlite:
                _rebuild_sqlite(conn)
            else:
                _alter_postgres(conn)
            if bikes:
                conn.execute(BikeDiscovery.__table__.insert(), bikes)
            if sqlite:
                conn.exec_driver_sql(f"DROP TABLE {OLD_TABLE}")
            else:
                _constrain_postgres(conn)
            BikeDiscoveryListing.__table__.create(conn, checkfirst=True)
            if listings:
                conn.execute(BikeDiscoveryListing.__table__.insert(), listings)
            _verify(conn, rows, bikes, stats)
            if dry_run:
                conn.rollback()
            else:
                conn.commit()
        except BaseException:
            conn.rollback()
            raise
    summary = {
        "status": DRY_RUN if dry_run else MIGRATED, "old_rows": len(rows), "bikes": len(bikes),
        "listings": len(listings), "merged_groups": stats["merged_groups"],
        "merged_rows": len(rows) - len(bikes), "bike_id_conflicts": stats["bike_id_conflicts"],
    }
    say(("dry run, rolled back: " if dry_run else "migrated: ")
        + " ".join(f"{k}={v}" for k, v in summary.items() if k != "status"))
    if stats["bike_id_conflicts"]:
        say(f"WARNING: {stats['bike_id_conflicts']} merged groups pointed at different bikes; "
            "each survivor kept the bike_id of its highest-status row")
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default=None, help="SQLAlchemy URL to migrate (default: DATABASE_URL from backend/.env; "
                                                "password may come from PGPASSFILE / PGPASSWORD)")
    ap.add_argument("--dry-run", action="store_true", help="migrate, verify and report, then roll back")
    ap.add_argument("--allow-remote", action="store_true", help="required for a non-local database, dry run too")
    args = ap.parse_args(argv)
    if args.url:
        models.configure_db(args.url)
    # Unlike the other scripts a dry run is guarded too: it runs the DDL (and takes the table lock) before rolling back.
    print(f"target: {db.check_target(allow_remote=args.allow_remote)}")
    try:
        migrate(dry_run=args.dry_run)
    except MigrationError as exc:
        print(f"ERROR: {exc} — rolled back, nothing changed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
