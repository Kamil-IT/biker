"""Storing bike data the way the backend reads it (TODO-036), shared by process_queue and copy_to_db.

Two places, two readers:
- `bike` (description, short_description) + `bike_detail_component` — DB-first search, POST /v1/bike/details and GET /v1/bike/details-cache;
- the generic cache under POST /v1/bike/details — the only thing the details view's details call reads;
- `bike_detail_photos` keyed on `bike_id` — POST /v1/bike/photos (the details view's photo gallery).

Details and photos are independent: a details save never touches photos, and photos a bike
already has are never replaced. Stored details have no TTL any more (removed upstream with the
photos re-key), so existing details are always kept. Everything works on the backend's *current*
engine (`models.configure_db` repoints it).
"""
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Optional

from db import models, repository, session, utcnow
from app import photos_repository
from app.schemas import BikeDetailsResponse

logger = logging.getLogger("bike_store")

KEPT, WRITTEN = "kept", "written"

PHOTOS_WRITTEN, PHOTOS_PRESENT, PHOTOS_NONE, PHOTOS_FAILED = "written", "present", "none", "failed"

# find_id(brand, model) -> bike id for the Python-normalised identity, or None
FindId = Callable[[str, str], Optional[int]]


@contextmanager
def tx():
    """db.session() plus commit on success / rollback on error (db.session() only closes)."""
    with session() as s:
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise


def aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def find_bike_id(brand: str, model: str) -> Optional[int]:
    """repository._find_bike_id in its own session (scans every bike — fine for one lookup)."""
    with session() as s:
        return repository._find_bike_id(s, brand, model)


def bike_state(bike_id: int) -> tuple[str, str, bool]:
    """(stored brand, stored model, has details - bike.description is set) of an existing bike."""
    with session() as s:
        bike = s.get(models.Bike, bike_id)
        has_details = bike.description is not None
        return bike.brand, bike.model, has_details


def _exact_bike_id(brand: str, model: str) -> Optional[int]:
    """Id of the bike save_bike_details wrote to (it matches brand/model exactly)."""
    with session() as s:
        bike = s.query(models.Bike).filter_by(brand=brand, model=model).first()
        return bike.id if bike is not None else None


def store_details(brand: str, model: str, make_response: Callable[[str, str], BikeDetailsResponse],
                  find_id: FindId = find_bike_id) -> tuple[str, int, str, str, Optional[BikeDetailsResponse]]:
    """Store details for a bike unless it already has some.

    Returns (KEPT, bike_id, stored brand, stored model, None) when details exist — of any age,
    AI- or earlier-parsed, nothing is overwritten — else (WRITTEN, bike_id, brand, model, response)
    after a verified save. An existing bike's stored casing is reused, because save_bike_details
    matches brand/model exactly and would otherwise mint a duplicate bike. Raises RuntimeError
    when the save did not land.
    """
    bike_id = find_id(brand, model)
    if bike_id is not None:
        brand, model, has_details = bike_state(bike_id)
        if has_details:
            return KEPT, bike_id, brand, model, None
    response = make_response(brand, model)
    # save_bike_details swallows its own errors (WARNING log, rollback) and returns False then.
    if not repository.save_bike_details(brand, model, response):
        raise RuntimeError("save_bike_details stored nothing (see its warning in the log)")
    saved = _exact_bike_id(brand, model)
    if saved is None:
        raise RuntimeError("save_bike_details stored nothing (bike row not found after the save)")
    return WRITTEN, saved, brand, model, response


def photo_count(bike_id: int) -> int:
    with session() as s:
        return s.query(models.BikeDetailPhoto.id).filter_by(bike_id=bike_id).count()


def store_photos(bike_id: int, brand: str, model: str, photos: list[str], write: bool = True) -> str:
    """Store the shop's photos for a bike that has none, through the backend's
    photos_repository.save_bike_photos (the writer the offline pipeline uses; it never replaces).

    `brand`/`model` are the bike's stored casing. Returns PHOTOS_WRITTEN / PHOTOS_PRESENT
    (the bike already has photos — kept) / PHOTOS_NONE (nothing to store) / PHOTOS_FAILED;
    never raises.
    """
    try:
        if photo_count(bike_id):
            return PHOTOS_PRESENT
        if not [u for u in photos if u]:
            return PHOTOS_NONE
        if not write:
            return PHOTOS_WRITTEN
        photos_repository.save_bike_photos(brand, model, photos)  # swallows DB errors itself
        if photo_count(bike_id):
            return PHOTOS_WRITTEN
        logger.warning("photos for %r %r did not land (see the photos warning)", brand, model)
    except Exception as exc:
        logger.warning("photos for %r %r failed | %s: %s", brand, model, type(exc).__name__, exc)
    return PHOTOS_FAILED
