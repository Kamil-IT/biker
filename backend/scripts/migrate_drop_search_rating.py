"""Drop search_bike_rating_cache.rating — the old search match score (TODO-040).

The search result card now shows the bike's expert rating (from a cached
review) instead of the AI's match score, so `match_score` left the API and its
storage column goes too. `init_db()`'s create_all() never ALTERs an existing
table, so every pre-existing database needs this script once — BEFORE the new
backend is deployed on it: the new backend never writes `rating`, but the column
is NOT NULL, so its save_search would fail (rollback + WARNING) until the
column is gone. Conversely, once this has run, the OLD backend's save_search
fails the same way (it still writes `rating`) until the new one is deployed —
nothing is lost, the found bikes are just not stored for that window.

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/migrate_drop_search_rating.py --dry-run
    python scripts/migrate_drop_search_rating.py
    python scripts/migrate_drop_search_rating.py --db path/to/copy.db
    python scripts/migrate_drop_search_rating.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

How: `ALTER TABLE search_bike_rating_cache DROP COLUMN rating` on both
dialects (SQLite >= 3.35 supports it for a plain column like this one — no
index, key or constraint references it). PostgreSQL takes
`LOCK TABLE … SHARE ROW EXCLUSIVE` first so concurrent writes cannot skew the
verification. ONE transaction: every other column of every row (id,
search_cache_id, bike_id, explanation, accessories, display_order) is
snapshotted before and compared after; any difference rolls back and leaves the
database unchanged. `display_order` stays — it is the AI answer's order, not a
match score.

Idempotent: no `rating` column (or no table — init_db() creates it without the
column) = nothing to do. Also importable:
`migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`.

Exit code: 0 on success (or nothing to do), 1 on a failed verification/run.
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine, make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

from app.models import DEFAULT_DB_PATH  # noqa: E402

TABLE = "search_bike_rating_cache"
COLUMN = "rating"
KEPT = ("id", "search_cache_id", "bike_id", "explanation", "accessories", "display_order")
_SNAPSHOT = f"SELECT {', '.join(KEPT)} FROM {TABLE} ORDER BY id"


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def _engine(url: str) -> Engine:
    # AUTOCOMMIT hands transaction control to the explicit BEGIN/COMMIT below —
    # pysqlite otherwise commits implicitly around DDL, which would break atomicity.
    return create_engine(url, isolation_level="AUTOCOMMIT")


def _snapshot(conn) -> dict:
    return {r[0]: tuple(r) for r in conn.execute(text(_SNAPSHOT))}


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
        "status": "", "rows_before": 0, "rows_after": 0, "verified": False, "error": None,
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if not insp.has_table(TABLE):
            report["status"], report["verified"] = "absent", True
            say(f"{TABLE} does not exist — nothing to migrate; init_db() creates it without {COLUMN}")
            return report
        if COLUMN not in {c["name"] for c in insp.get_columns(TABLE)}:
            with engine.connect() as conn:
                report["rows_before"] = report["rows_after"] = conn.execute(
                    text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
            report["status"], report["verified"] = "already-migrated", True
            say(f"{TABLE}.{COLUMN} already dropped — nothing to do ({report['rows_after']} rows)")
            return report
        if dialect == "sqlite" and sqlite3.sqlite_version_info < (3, 35, 0):
            raise RuntimeError(f"SQLite {sqlite3.sqlite_version} has no DROP COLUMN (needs >= 3.35)")

        with engine.connect() as conn:
            conn.exec_driver_sql("BEGIN IMMEDIATE" if dialect == "sqlite" else "BEGIN")
            try:
                if dialect == "postgresql":
                    conn.exec_driver_sql(f"LOCK TABLE {TABLE} IN SHARE ROW EXCLUSIVE MODE")
                before = _snapshot(conn)
                report["rows_before"] = len(before)
                say(f"before: {len(before)} rows in {TABLE}, column {COLUMN} present")

                if dry_run:
                    conn.exec_driver_sql("ROLLBACK")
                    report["status"], report["rows_after"], report["verified"] = "dry-run", len(before), True
                    say(f"dry run: would drop {TABLE}.{COLUMN}, keeping all {len(before)} rows — nothing written")
                    return report

                conn.exec_driver_sql(f"ALTER TABLE {TABLE} DROP COLUMN {COLUMN}")
                after = _snapshot(conn)
                report["rows_after"] = len(after)
                if after != before:
                    missing = sorted(set(before) - set(after))[:10]
                    changed = sorted(i for i in set(before) & set(after) if before[i] != after[i])[:10]
                    raise RuntimeError(
                        f"verification failed: expected {len(before)} rows, got {len(after)}; "
                        f"missing ids {missing}, changed ids {changed}")
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
        report["status"], report["verified"] = "migrated", True
        say(f"after:  {report['rows_after']} rows, {COLUMN} dropped — every row kept "
            f"{', '.join(KEPT)}")
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
