"""One-off migration: the JSON-blob caches → the normalised ORM tables.

Two legacy blob tables move here:

- `bike_details_cache` → `bikes` + `bike_details` + `bike_detail_photos`,
  preserving each row's real age (`time_stored` → `updated_at`/`created_at`,
  `ttl` → `ttl_seconds`) and photo ordering (array index → `display_order`).
- `search_cache` → `searches` + `bike_results` + `accessories`, preserving age
  (`time_stored` → `created_at`) and the score-weighted rank the JSON array
  carried implicitly (array index → `position`). Bikes become references to
  `bikes` rather than embedded copies.

Also brings `bikes` up to the current schema: adds the `brand_norm`/`model_norm`
lookup columns, backfills them for EVERY existing row, merges any pre-existing
case-split pairs into one identity, and applies the unique index over them.

Cleans up what the old test scripts left behind: every `bike_results` /
`accessories` row, plus any `bikes` row nothing references.

Idempotent: a bike that already has a `bike_details` row is left alone, so
re-running is a no-op. Pass force=True / --force to rebuild existing rows.

Importable entry point:

    migrate(db_path=None, drop_blob_table=False, force=False, verbose=True) -> dict

`db_path=None` uses backend/cache.db; an explicit path is honoured by BOTH the
raw-sqlite blob reads and the SQLAlchemy writes (via `models.configure_db`),
and the previous engine is restored afterwards. Dropping the legacy tables is
opt-in from both entry points — `drop_blob_table=True` here, `--drop-legacy` on
the CLI — because the parity tests read the blob path and cannot be re-run once
it is gone.

Returned dict keys: bikes · details, photos, skipped, legacy_rows ·
searches, results, searches_skipped, legacy_searches · norm_backfilled,
merged_bikes, merged_names · casing_repaired, placeholders_left ·
bike_results_deleted, accessories_deleted, orphan_bikes_deleted, orphan_names ·
blob_tables_dropped (a LIST of dropped table names, not a bool).

CLI (from backend/):
    python scripts/migrate_bike_details.py                # keeps the blob tables
    python scripts/migrate_bike_details.py --drop-legacy  # and drops them
    python scripts/migrate_bike_details.py --db /tmp/copy.db --force
"""
import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import models, repository  # noqa: E402
from app.models import (  # noqa: E402
    Accessory,
    Bike,
    BikeDetails,
    BikeDetailPhoto,
    BikeOffer,
    BikeResult,
    Search,
    norm,
)


def _to_naive_utc(iso_ts: str) -> datetime:
    """Blob timestamps are tz-aware ISO strings; the ORM columns are naive UTC."""
    dt = datetime.fromisoformat(iso_ts)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _ensure_norm_columns(raw: sqlite3.Connection) -> int:
    """Add brand_norm/model_norm to `bikes` if absent and backfill every row.

    Backfills in Python, not SQL — SQLite's `lower()` is ASCII-only and would
    leave `Riese & MÜller` mismatched against the Python-normalised lookup key
    the application compares against. Returns the number of rows written.
    """
    cols = {r[1] for r in raw.execute("PRAGMA table_info(bikes)")}
    if "brand_norm" not in cols:
        raw.execute("ALTER TABLE bikes ADD COLUMN brand_norm TEXT NOT NULL DEFAULT ''")
    if "model_norm" not in cols:
        raw.execute("ALTER TABLE bikes ADD COLUMN model_norm TEXT NOT NULL DEFAULT ''")

    fixed = 0
    rows = raw.execute("SELECT id, brand, model, brand_norm, model_norm FROM bikes").fetchall()
    for bike_id, brand, model, brand_norm, model_norm in rows:
        want = (norm(brand), norm(model))
        if (brand_norm, model_norm) != want:
            raw.execute(
                "UPDATE bikes SET brand_norm = ?, model_norm = ? WHERE id = ?",
                (*want, bike_id),
            )
            fixed += 1
    raw.commit()
    return fixed


def _merge_case_split_bikes(raw: sqlite3.Connection) -> list[str]:
    """Collapse `bikes` rows that share a normalised identity into one.

    The oldest row wins (lowest id); everything referencing a loser is repointed
    at the survivor. Only rows whose FULL normalised (brand, model) pair matches
    are merged — `Canyon/Grizl CF 7` and `Canyon/Grizl` normalise differently and
    are left alone as the genuinely distinct models they are.
    """
    groups: dict[tuple[str, str], list[int]] = {}
    for bike_id, brand_norm, model_norm in raw.execute(
        "SELECT id, brand_norm, model_norm FROM bikes ORDER BY id"
    ):
        groups.setdefault((brand_norm, model_norm), []).append(bike_id)

    merged: list[str] = []
    for (brand_norm, model_norm), ids in groups.items():
        if len(ids) < 2:
            continue
        keep, losers = ids[0], ids[1:]
        for loser in losers:
            # A bike has at most one details row (bike_id is UNIQUE), so if the
            # survivor already has one the loser's is the redundant copy.
            if raw.execute("SELECT 1 FROM bike_details WHERE bike_id = ?", (keep,)).fetchone():
                raw.execute("DELETE FROM bike_details WHERE bike_id = ?", (loser,))
            else:
                raw.execute("UPDATE bike_details SET bike_id = ? WHERE bike_id = ?", (keep, loser))
            raw.execute("UPDATE bike_results SET bike_id = ? WHERE bike_id = ?", (keep, loser))
            raw.execute("UPDATE bike_offers SET bike_id = ? WHERE bike_id = ?", (keep, loser))
            raw.execute("DELETE FROM bikes WHERE id = ?", (loser,))
            merged.append(f"{brand_norm}/{model_norm} (id {loser} -> {keep})")
    raw.commit()
    return merged


def _apply_norm_unique_index(raw: sqlite3.Connection) -> None:
    raw.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_bike_brand_model_norm "
        "ON bikes(brand_norm, model_norm)"
    )
    raw.commit()


def _legacy_rows(raw: sqlite3.Connection) -> list[tuple]:
    exists = raw.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='bike_details_cache'"
    ).fetchone()
    if not exists:
        return []
    return raw.execute(
        "SELECT company, model, description, components, photos, time_stored, ttl "
        "FROM bike_details_cache ORDER BY id"
    ).fetchall()


def _copy_blob_rows(db_path: Path, force: bool) -> dict:
    raw = sqlite3.connect(str(db_path))
    rows = _legacy_rows(raw)
    raw.close()

    session = models.get_session()
    stats = {"legacy_rows": len(rows), "details": 0, "skipped": 0, "photos": 0}
    stamp: dict[int, datetime] = {}

    try:
        for company, model, description, components, photos, time_stored, ttl in rows:
            bike = repository._get_or_create_bike(session, company, model)

            existing = session.query(BikeDetails).filter_by(bike_id=bike.id).first()
            if existing is not None:
                if not force:
                    stats["skipped"] += 1
                    continue
                session.delete(existing)
                session.flush()

            stored_at = _to_naive_utc(time_stored)
            details = BikeDetails(
                bike_id=bike.id,
                description=description,
                components=components,
                created_at=stored_at,
                updated_at=stored_at,
                ttl_seconds=ttl,
            )
            session.add(details)
            session.flush()
            stamp[details.id] = stored_at

            for idx, url in enumerate(json.loads(photos)):
                session.add(BikeDetailPhoto(
                    bike_details_id=details.id,
                    url=url,
                    display_order=idx,
                ))
                stats["photos"] += 1

            stats["details"] += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # `BikeDetails.updated_at` carries onupdate=now, so anything that dirties the
    # row later would silently refresh the migrated age. Re-assert it in raw SQL
    # and prove it stuck before reporting success.
    if stamp:
        raw = sqlite3.connect(str(db_path))
        for details_id, stored_at in stamp.items():
            ts = stored_at.isoformat(sep=" ")
            raw.execute(
                "UPDATE bike_details SET created_at = ?, updated_at = ? WHERE id = ?",
                (ts, ts, details_id),
            )
        raw.commit()
        raw.close()

        session = models.get_session()
        try:
            for details_id, stored_at in stamp.items():
                got = session.get(BikeDetails, details_id).updated_at
                assert got == stored_at, (
                    f"updated_at not preserved for bike_details id={details_id}: "
                    f"stored {got!r}, expected {stored_at!r}"
                )
        finally:
            session.close()

    return stats


def _ensure_result_columns(raw: sqlite3.Connection) -> None:
    """Add `search_id` / `position` to a pre-existing `bike_results` table."""
    cols = {r[1] for r in raw.execute("PRAGMA table_info(bike_results)")}
    if "search_id" not in cols:
        raw.execute("ALTER TABLE bike_results ADD COLUMN search_id INTEGER REFERENCES searches(id)")
    if "position" not in cols:
        raw.execute("ALTER TABLE bike_results ADD COLUMN position INTEGER NOT NULL DEFAULT 0")
    raw.commit()


def _legacy_search_rows(raw: sqlite3.Connection) -> list[tuple]:
    exists = raw.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='search_cache'"
    ).fetchone()
    if not exists:
        return []
    return raw.execute(
        "SELECT query, bikes, time_stored, ttl FROM search_cache ORDER BY id"
    ).fetchall()


def _copy_search_rows(db_path: Path, force: bool) -> dict:
    """Backfill `search_cache` blobs into `searches` + `bike_results`.

    Each blob bike is resolved to a `bikes` identity through the same
    normalised get-or-create the app uses, so a cached search naming
    `TREK`/`Marlin 5` attaches to the existing `Trek`/`Marlin 5` row rather
    than minting a case-split duplicate.
    """
    raw = sqlite3.connect(str(db_path))
    rows = _legacy_search_rows(raw)
    raw.close()

    session = models.get_session()
    stats = {"legacy_searches": len(rows), "searches": 0, "results": 0, "searches_skipped": 0}
    stamp: dict[int, datetime] = {}

    try:
        for query, bikes_json, time_stored, ttl in rows:
            norm_query = norm(query)
            search = session.query(Search).filter(Search.query == norm_query).first()
            if search is not None:
                if not force:
                    stats["searches_skipped"] += 1
                    continue
                session.delete(search)
                session.flush()

            stored_at = _to_naive_utc(time_stored)
            search = Search(query=norm_query, created_at=stored_at, ttl_seconds=ttl)
            session.add(search)
            session.flush()
            stamp[search.id] = stored_at

            for position, b in enumerate(json.loads(bikes_json)):
                bike = repository._get_or_create_bike(
                    session, b.get("brand", ""), b.get("model", "")
                )
                result = BikeResult(
                    search_id=search.id,
                    bike_id=bike.id,
                    position=position,
                    match_score=b.get("match_score", 0.0),
                    explanation=b.get("explanation", ""),
                    created_at=stored_at,
                )
                session.add(result)
                session.flush()
                for name in b.get("accessories", []):
                    session.add(Accessory(bike_result_id=result.id, name=name))
                stats["results"] += 1

            stats["searches"] += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # `Search.created_at` is the TTL anchor; re-assert it the same way the
    # details rows do, and prove it stuck.
    if stamp:
        raw = sqlite3.connect(str(db_path))
        for search_id, stored_at in stamp.items():
            raw.execute(
                "UPDATE searches SET created_at = ? WHERE id = ?",
                (stored_at.isoformat(sep=" "), search_id),
            )
        raw.commit()
        raw.close()

        session = models.get_session()
        try:
            for search_id, stored_at in stamp.items():
                got = session.get(Search, search_id).created_at
                assert got == stored_at, (
                    f"created_at not preserved for search id={search_id}: "
                    f"stored {got!r}, expected {stored_at!r}"
                )
        finally:
            session.close()

    return stats


def _repair_placeholder_casing(db_path: Path) -> dict:
    """Upgrade placeholder-cased `bikes` rows from the search blob's real casing.

    Runs on EVERY invocation, independent of whether the search rows themselves
    were skipped as already-migrated. That matters: the details backfill seeds
    `bikes` from the old blob's keys, which `store.save_bike_details` had
    lowercased, so a DB migrated by an earlier build carries placeholder casing
    that search results then surface (`cannondale` instead of `Cannondale`).
    Skipping-based idempotency alone would never revisit those rows, leaving a
    migration that cannot repair its own earlier output.

    `search_cache` is the only place real casing survives, so once it has been
    dropped this can no longer repair anything — hence `placeholders_left`,
    which the report escalates.
    """
    raw = sqlite3.connect(str(db_path))
    rows = _legacy_search_rows(raw)
    raw.close()

    session = models.get_session()
    repaired: list[str] = []
    try:
        for _query, bikes_json, _ts, _ttl in rows:
            for b in json.loads(bikes_json):
                brand, model = b.get("brand", ""), b.get("model", "")
                bike = repository._find_bike_ci(session, brand, model)
                if bike is None:
                    continue
                before = (bike.brand, bike.model)
                # Same placeholder rule as repository._get_or_create_bike.
                for attr, incoming in (("brand", brand), ("model", model)):
                    stored = getattr(bike, attr)
                    if stored == norm(stored) and incoming.strip() != norm(incoming):
                        setattr(bike, attr, incoming.strip())
                if (bike.brand, bike.model) != before:
                    repaired.append(f"{before[0]}/{before[1]} -> {bike.brand}/{bike.model}")
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    # Anything still lowercase AND referenced by a search result would render
    # that way in the UI; report it rather than let it pass silently.
    session = models.get_session()
    try:
        left = [
            f"{b.brand}/{b.model}"
            for b in session.query(Bike)
            .filter((Bike.brand == Bike.brand_norm) | (Bike.model == Bike.model_norm))
            .all()
            if session.query(BikeResult).filter_by(bike_id=b.id).first()
        ]
    finally:
        session.close()

    return {"casing_repaired": repaired, "placeholders_left": left}


def _cleanup() -> dict:
    """Drop results orphaned from any search, and any bike nobody references."""
    session = models.get_session()
    stats = {
        "bike_results_deleted": 0,
        "accessories_deleted": 0,
        "orphan_bikes_deleted": 0,
        "orphan_names": [],
    }
    try:
        # Results with no parent search are the old test-script leftovers —
        # nothing wrote a search_id before this migration. Migrated rows all
        # have one, so this no longer deletes real data.
        results = session.query(BikeResult).filter(BikeResult.search_id.is_(None)).all()
        stats["bike_results_deleted"] = len(results)
        stats["accessories_deleted"] = sum(len(r.accessories) for r in results)
        for r in results:
            session.delete(r)
        session.flush()

        for bike in session.query(Bike).all():
            referenced = (
                session.query(BikeDetails).filter_by(bike_id=bike.id).first()
                or session.query(BikeResult).filter_by(bike_id=bike.id).first()
                or session.query(BikeOffer).filter_by(bike_id=bike.id).first()
            )
            if referenced:
                continue
            stats["orphan_names"].append(f"{bike.brand}/{bike.model}")
            session.delete(bike)
            stats["orphan_bikes_deleted"] += 1

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return stats


def _drop_blob_tables(db_path: Path) -> list[str]:
    """Drop both legacy blob tables. Returns the names actually dropped.

    Callers must check `_unrepaired_placeholders()` first — see `migrate()`.
    """
    raw = sqlite3.connect(str(db_path))
    dropped: list[str] = []
    try:
        for table, index in (
            ("bike_details_cache", "idx_bike_details_company_model"),
            ("search_cache", "idx_search_cache_query"),
        ):
            exists = raw.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                continue
            raw.execute(f"DROP INDEX IF EXISTS {index}")
            raw.execute(f"DROP TABLE {table}")
            dropped.append(table)
        raw.commit()
        return dropped
    finally:
        raw.close()


def migrate(
    db_path: Optional[Path] = None,
    drop_blob_table: bool = False,
    force: bool = False,
    verbose: bool = True,
    allow_unsafe_drop: bool = False,
) -> dict:
    """Run the whole migration against `db_path` (default backend/cache.db).

    `drop_blob_table` defaults to False so this matches a bare CLI run: dropping
    the legacy tables is opt-in from both entry points, because the parity tests
    read the blob path and cannot be re-run once it is gone.
    """
    target = Path(db_path) if db_path is not None else models.DEFAULT_DB_PATH
    previous_engine, previous_sessions = models._engine, models._SessionLocal
    models.configure_db(target)
    try:
        models.init_db()

        raw = sqlite3.connect(str(target))
        try:
            norm_backfilled = _ensure_norm_columns(raw)
            merged = _merge_case_split_bikes(raw)
            _apply_norm_unique_index(raw)
            _ensure_result_columns(raw)
        finally:
            raw.close()

        stats = _copy_blob_rows(target, force=force)
        stats["norm_backfilled"] = norm_backfilled
        stats["merged_bikes"] = len(merged)
        stats["merged_names"] = merged
        stats.update(_copy_search_rows(target, force=force))
        # After both backfills, regardless of what was skipped — see the
        # docstring on why this cannot live inside the skip-based copy.
        stats.update(_repair_placeholder_casing(target))
        stats.update(_cleanup())

        session = models.get_session()
        try:
            stats["bikes"] = session.query(Bike).count()
        finally:
            session.close()

        # `--force` repairs placeholder casing by rebuilding from the legacy
        # blob tables, so dropping them while any row is still unrepaired
        # destroys the only copy of the correct casing. The two flags look
        # independent but are strictly order-dependent; refuse rather than let
        # a recoverable mistake become an unrecoverable one.
        stats["blob_drop_refused"] = []
        if drop_blob_table and stats["placeholders_left"] and not allow_unsafe_drop:
            stats["blob_drop_refused"] = list(stats["placeholders_left"])
            stats["blob_tables_dropped"] = []
        elif drop_blob_table:
            stats["blob_tables_dropped"] = _drop_blob_tables(target)
        else:
            stats["blob_tables_dropped"] = []

        if verbose:
            _report(target, stats)
        return stats
    finally:
        models._engine, models._SessionLocal = previous_engine, previous_sessions


def verify() -> None:
    """Re-read every migrated row through the ORM and print what came back."""
    session = models.get_session()
    try:
        details = session.query(BikeDetails).join(Bike).order_by(Bike.brand, Bike.model).all()
        rows = [
            (d.bike.brand, d.bike.model, d.bike.brand_norm, d.bike.model_norm,
             d.updated_at, d.ttl_seconds, len(d.photos))
            for d in details
        ]
    finally:
        session.close()

    print(f"\nVerification — {len(rows)} bike_details rows:")
    for brand, model, brand_norm, model_norm, updated_at, ttl, photo_rows in rows:
        got = repository.get_bike_details(brand, model)
        state = "MISS" if got is None else f"ok, photos={len(got.photos)}"
        print(
            f"  {brand!r}/{model!r}  norm={brand_norm!r}/{model_norm!r}  "
            f"updated_at={updated_at}  ttl={ttl}  photo_rows={photo_rows}  read-back={state}"
        )
        if got is not None:
            assert got.company == brand and got.model == model, "casing echo broken"
            assert got.photos is not None, "photos must never be None"
            assert len(got.photos) == photo_rows, "photo count mismatch"


def _report(target: Path, stats: dict) -> None:
    print(f"cache.db: {target}")
    print(
        f"\nSchema:  brand_norm/model_norm written on {stats['norm_backfilled']} bikes | "
        f"case-split merges={stats['merged_bikes']} {stats['merged_names'] or ''}"
    )
    print(
        f"Details: {stats['legacy_rows']} legacy rows | details written={stats['details']} "
        f"skipped(already present)={stats['skipped']} photos written={stats['photos']}"
    )
    print(
        f"Search:  {stats['legacy_searches']} legacy rows | searches written={stats['searches']} "
        f"skipped(already present)={stats['searches_skipped']} results written={stats['results']}"
    )
    repaired, left = stats["casing_repaired"], stats["placeholders_left"]
    print(f"Casing:  placeholder rows repaired={len(repaired)} {repaired or ''}")
    if left:
        print(
            f"  !! WARNING: {len(left)} bike(s) still stored with placeholder (all-lowercase)\n"
            f"     casing and referenced by search results: {left}\n"
            f"     They will render lowercase in the UI. If `search_cache` still exists,\n"
            f"     re-run with --force to rebuild from it; if it has been dropped, the\n"
            f"     original casing is gone and the next real search for each bike will\n"
            f"     restore it."
        )
    print(
        f"Cleanup: orphaned bike_results deleted={stats['bike_results_deleted']} "
        f"accessories deleted={stats['accessories_deleted']} "
        f"orphan bikes deleted={stats['orphan_bikes_deleted']} {stats['orphan_names']}"
    )
    if stats["blob_drop_refused"]:
        print(
            "\n  !! --drop-legacy REFUSED. "
            f"{len(stats['blob_drop_refused'])} bike(s) still have placeholder\n"
            f"     (all-lowercase) casing: {stats['blob_drop_refused']}\n"
            "     The legacy blob tables are the ONLY remaining copy of their real\n"
            "     casing, and --force rebuilds from them. Dropping now makes this\n"
            "     unrecoverable by anything but hand-editing.\n"
            "     Fix first:  python scripts/migrate_bike_details.py --force\n"
            "     then re-run with --drop-legacy. To drop anyway, accepting the\n"
            "     permanent loss:  --i-know-what-im-doing"
        )
    else:
        print(f"Legacy blob tables dropped: {stats['blob_tables_dropped'] or 'none (kept)'}")
    verify()


def main(argv: Optional[list[str]] = None) -> dict:
    parser = argparse.ArgumentParser(
        description="Migrate the bike details blob cache into the ORM tables."
    )
    parser.add_argument(
        "--db", type=Path, default=None,
        help="SQLite file to operate on (default: backend/cache.db)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="rebuild bike_details rows that already exist (default: skip them)",
    )
    parser.add_argument(
        "--drop-legacy", action="store_true",
        help="drop the legacy blob tables (bike_details_cache, search_cache) when done — "
             "run only once the parity tests are green. Refused while any bike still "
             "has unrepaired placeholder casing",
    )
    parser.add_argument(
        "--i-know-what-im-doing", dest="allow_unsafe_drop", action="store_true",
        help="allow --drop-legacy even with unrepaired placeholder casing, accepting "
             "that the real casing is destroyed permanently",
    )
    args = parser.parse_args(argv)

    stats = migrate(
        db_path=args.db,
        drop_blob_table=args.drop_legacy,
        force=args.force,
        allow_unsafe_drop=args.allow_unsafe_drop,
    )
    if stats["blob_drop_refused"]:
        print("\nDone — but --drop-legacy was REFUSED (see above).")
        raise SystemExit(1)
    print("\nDone.")
    return stats


if __name__ == "__main__":
    main()
