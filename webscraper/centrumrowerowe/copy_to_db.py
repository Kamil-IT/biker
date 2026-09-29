"""Copy what bike discovery stored in one database into another (TODO-036) — no page is re-fetched.

Phase 1 reads the source (bike_discovery rows + the details and photos of each done/skipped row's
bike) into memory and closes it; phase 2 writes the target: bike details through the same verified
save as the processor, the bike's photos (only when the target bike has none), the /v1/bike/details
cache, then every queue row upserted by (source, source_product_id).

    python copy_to_db.py --target-url "postgresql+psycopg://user@127.0.0.1:6543/biker" --allow-remote
    python copy_to_db.py --target-url ... --dry-run      # report what would change, write nothing
"""
import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402  (puts backend/ on sys.path, loads backend/.env)
from db import DONE, FAILED, IN_PROGRESS, PENDING, SKIPPED, BikeDiscovery, models, repository, session  # noqa: E402
from bike_store import (  # noqa: E402
    CACHE_FAILED, CACHE_PRESENT, CACHE_WRITTEN, KEPT, PHOTOS_FAILED, PHOTOS_NONE, PHOTOS_PRESENT, PHOTOS_WRITTEN,
    WRITTEN, bike_state, cache_details, store_details, store_photos, tx,
)
from app import photos_repository  # noqa: E402
from app.schemas import BikeDetailsResponse  # noqa: E402
from sqlalchemy import inspect  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

logger = logging.getLogger("copy_to_db")

# Copied as-is from the source row; id, bike_id and locked_at never are.
COPIED_COLUMNS = ("source", "source_product_id", "raw_name", "company", "model", "bike_type", "details_link",
                  "price", "status", "attempts", "last_error", "next_attempt_at",
                  "first_seen_at", "last_seen_at", "updated_at")
FINAL = (DONE, SKIPPED)
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")


@dataclass
class SourceBike:
    brand: str
    model: str
    details: Optional[BikeDetailsResponse]
    photos: list[str] = field(default_factory=list)  # bike_detail_photos, display order


@dataclass
class Snapshot:
    rows: list[dict] = field(default_factory=list)          # COPIED_COLUMNS + "src_bike_id"
    bikes: dict[int, SourceBike] = field(default_factory=dict)  # source bike id → bike


def default_source_url() -> str:
    """DATABASE_URL from backend/.env (db.py loaded it), else the backend's own fallback."""
    return os.environ.get("DATABASE_URL") or models.database_url()


def database_identity(url: str) -> tuple:
    """What makes two URLs the same database: the resolved file for SQLite, host/port/name otherwise."""
    u = make_url(url)
    if u.get_backend_name() == "sqlite":
        return ("sqlite", str(Path(u.database or "").resolve()).lower())
    host = (u.host or str(u.query.get("host", ""))).lower()
    host = "localhost" if host in LOCAL_HOSTS else host
    return (u.get_backend_name(), host, u.port or 5432, u.database)


def read_source(source_url: str, shop: Optional[str] = None, limit: Optional[int] = None) -> Snapshot:
    """Phase 1: everything needed from the source, as plain objects; the source engine is closed after."""
    models.configure_db(source_url)
    try:
        if not inspect(models.get_engine()).has_table(BikeDiscovery.__tablename__):
            raise SystemExit(f"the source has no {BikeDiscovery.__tablename__} table")
        snap = Snapshot()
        with session() as s:
            q = s.query(BikeDiscovery).order_by(BikeDiscovery.id)
            if shop:
                q = q.filter(BikeDiscovery.source == shop)
            if limit:
                q = q.limit(limit)
            for row in q:
                snap.rows.append({**{c: getattr(row, c) for c in COPIED_COLUMNS}, "src_bike_id": row.bike_id})
            bike_ids = {r["src_bike_id"] for r in snap.rows if r["src_bike_id"] is not None and r["status"] in FINAL}
            for bike in s.query(models.Bike).filter(models.Bike.id.in_(bike_ids)) if bike_ids else []:
                snap.bikes[bike.id] = SourceBike(bike.brand, bike.model, None)
        for bike in snap.bikes.values():  # details None when the source bike has no details row
            bike.details = repository.get_bike_details(bike.brand, bike.model)
            bike.photos = photos_repository.get_bike_photos(bike.brand, bike.model).photos
        return snap
    finally:
        models.dispose_engine()


class TargetIndex:
    """Normalised identity → target bike id, built once (repository._find_bike_id scans every bike per call).

    Oldest row wins, exactly like _find_bike_id; bikes written during the run are added.
    """

    def __init__(self) -> None:
        self._ids: dict[tuple[str, str], int] = {}
        with session() as s:
            for b in s.query(models.Bike.id, models.Bike.brand, models.Bike.model).order_by(models.Bike.id):
                self._ids.setdefault(self._key(b.brand, b.model), b.id)

    @staticmethod
    def _key(brand: str, model: str) -> tuple[str, str]:
        return repository._lc(brand), repository._lc(model)

    def find(self, brand: str, model: str) -> Optional[int]:
        return self._ids.get(self._key(brand, model))

    def add(self, brand: str, model: str, bike_id: int) -> None:
        self._ids.setdefault(self._key(brand, model), bike_id)


def copy_bike(bike: SourceBike, index: TargetIndex, counts: dict, dry_run: bool) -> Optional[tuple[int, str, str]]:
    """Write one bike's details and photos to the target; (target bike id, stored brand, stored model) or None.

    Details already in the target are kept (only linked); photos go in only when the target bike
    has none. In a dry run the id is -1 for a bike that would be created. Never raises: a failure
    is logged and counted.
    """
    try:
        if dry_run:
            bike_id = index.find(bike.brand, bike.model)
            brand, model, has = bike_state(bike_id) if bike_id is not None else (bike.brand, bike.model, False)
            counts["bikes " + (KEPT if has else WRITTEN)] += 1
            if not has and bike.details is None:
                return None
            counts["cache " + cache_details(brand, model, bike.details, write=False)] += 1
            photos = (store_photos(bike_id, brand, model, bike.photos, write=False) if bike_id is not None
                      else PHOTOS_WRITTEN if bike.photos else PHOTOS_NONE)
            counts["photos " + photos] += 1
            return (bike_id if bike_id is not None else -1), brand, model
        if bike.details is None:  # nothing to write; link only when the target already has details
            bike_id = index.find(bike.brand, bike.model)
            if bike_id is None or not bike_state(bike_id)[2]:
                return None
            outcome, brand, model, response = KEPT, *bike_state(bike_id)[:2], None
        else:
            details = bike.details
            outcome, bike_id, brand, model, response = store_details(
                bike.brand, bike.model, lambda c, m: details.model_copy(update={"company": c, "model": m}),
                find_id=index.find)
            index.add(brand, model, bike_id)
        counts["bikes " + outcome] += 1
        counts["photos " + store_photos(bike_id, brand, model, bike.photos)] += 1
        if response is None:  # kept: cache the target's own details (first write wins anyway)
            response = repository.get_bike_details(brand, model)
        if response is not None:
            counts["cache " + cache_details(brand, model, response)] += 1
        return bike_id, brand, model
    except Exception as exc:
        counts["bikes failed"] += 1
        logger.warning("bike %r %r not copied | %s: %s", bike.brand, bike.model, type(exc).__name__, exc)
        return None


def target_values(row: dict, linked: Optional[tuple[int, str, str]]) -> dict:
    """The row as it should look in the target: TARGET bike id, never the source's; no lease."""
    values = {c: row[c] for c in COPIED_COLUMNS}
    values["bike_id"] = None
    values["locked_at"] = None
    if row["status"] in FINAL and row["src_bike_id"] is not None:
        if linked is None:  # the bike could not be written here: let the processor fetch it again
            values.update(status=PENDING, attempts=0, next_attempt_at=None)
        else:
            values["bike_id"], values["company"], values["model"] = linked
    elif row["status"] == IN_PROGRESS:
        values.update(status=PENDING, attempts=0, next_attempt_at=None)
    return values


def upsert_row(values: dict, counts: dict, dry_run: bool) -> None:
    """Insert a new queue row, or promote an existing pending/failed one — never downgrade."""
    with tx() as s:
        existing = s.query(BikeDiscovery).filter_by(
            source=values["source"], source_product_id=values["source_product_id"]).first()
        if existing is None:
            counts["rows inserted"] += 1
            if not dry_run:
                s.add(BikeDiscovery(**values))
            return
        if existing.status in (PENDING, FAILED) and values["status"] in FINAL:
            counts["rows updated"] += 1
            if not dry_run:
                for key in ("status", "bike_id", "company", "model", "last_error", "attempts", "updated_at"):
                    setattr(existing, key, values[key])
                existing.next_attempt_at = None
                existing.locked_at = None
            return
        counts["rows unchanged"] += 1
        s.rollback()


def write_target(target_url: str, snap: Snapshot, dry_run: bool = False) -> dict[str, int]:
    """Phase 2: bikes first (commit per bike), then every queue row (commit per row)."""
    counts = {k: 0 for k in ("rows inserted", "rows updated", "rows unchanged", "rows failed",
                             "bikes " + WRITTEN, "bikes " + KEPT, "bikes failed",
                             "cache " + CACHE_WRITTEN, "cache " + CACHE_PRESENT, "cache " + CACHE_FAILED,
                             "photos " + PHOTOS_WRITTEN, "photos " + PHOTOS_PRESENT, "photos " + PHOTOS_NONE,
                             "photos " + PHOTOS_FAILED)}
    models.configure_db(target_url)
    try:
        has_table = inspect(models.get_engine()).has_table(BikeDiscovery.__tablename__)
        if not dry_run:
            db.ensure_table()  # the backend owns (and has created) its own tables
        index = TargetIndex()
        linked = {src_id: copy_bike(bike, index, counts, dry_run) for src_id, bike in snap.bikes.items()}
        for row in snap.rows:
            values = target_values(row, linked.get(row["src_bike_id"]))
            try:
                if dry_run and not has_table:
                    counts["rows inserted"] += 1
                else:
                    upsert_row(values, counts, dry_run)
            except Exception as exc:
                counts["rows failed"] += 1
                logger.warning("queue row %s not copied | %s: %s", row["source_product_id"], type(exc).__name__, exc)
        return counts
    finally:
        models.dispose_engine()


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--target-url", required=True, help="SQLAlchemy URL of the database to write (password may "
                                                        "come from PGPASSFILE / PGPASSWORD)")
    ap.add_argument("--source-url", default=None, help="database to read (default: DATABASE_URL from backend/.env)")
    ap.add_argument("--source", default=None, help="only this shop, e.g. centrumrowerowe.pl")
    ap.add_argument("--limit", type=int, default=None, help="copy at most this many queue rows")
    ap.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    ap.add_argument("--allow-remote", action="store_true", help="required when the target is not a local database")
    args = ap.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        ap.error("--limit must be >= 1")
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    source_url = args.source_url or default_source_url()
    print(f"source: {db.describe_target(source_url, allow_remote=True)}")  # only read — may be anything
    # A dry run writes nothing, so it only prints the target instead of refusing a remote one.
    print(f"target: {db.describe_target(args.target_url, allow_remote=args.allow_remote or args.dry_run)}")
    if database_identity(source_url) == database_identity(args.target_url):
        raise SystemExit("source and target are the same database — refusing to copy onto itself")

    snap = read_source(source_url, args.source, args.limit)
    print(f"read {len(snap.rows)} queue rows, {len(snap.bikes)} bikes "
          f"({sum(b.details is not None for b in snap.bikes.values())} with details, "
          f"{sum(bool(b.photos) for b in snap.bikes.values())} with photos)")
    counts = write_target(args.target_url, snap, dry_run=args.dry_run)
    prefix = "dry run, would be: " if args.dry_run else ""
    print(prefix + " ".join(f"{k.replace(' ', '_')}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
