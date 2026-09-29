"""Storing bike details the way the backend expects them (TODO-036), shared by process_queue and copy_to_db.

Everything here works on the backend's *current* engine (`models.configure_db` repoints it).
"""
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Optional

from db import models, repository, session, utcnow
from app import cache
from app.schemas import BikeDetailsResponse

logger = logging.getLogger("bike_store")

KEPT, WRITTEN = "kept", "written"

# POST /v1/bike/details reads only the generic cache, never the ORM tables — so a parsed bike
# must be cached there too or the details view would run the AI pipeline for it.
DETAILS_ENDPOINT = "/v1/bike/details"
CACHE_WRITTEN, CACHE_PRESENT, CACHE_MISSING, CACHE_FAILED = "written", "present", "missing", "failed"

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
    """(stored brand, stored model, has details within the TTL) of an existing bike."""
    with session() as s:
        bike = s.get(models.Bike, bike_id)
        details = s.query(models.BikeDetails).filter_by(bike_id=bike_id).first()
        fresh = False
        if details is not None and details.updated_at is not None:
            fresh = (utcnow() - aware(details.updated_at)).total_seconds() <= repository.TTL_DETAILS
        return bike.brand, bike.model, fresh


def _saved_bike_id(brand: str, model: str, since: datetime) -> Optional[int]:
    """Id of the bike save_bike_details wrote to (it matches brand/model exactly), if its details
    row was written at or after `since` — an older (stale) row left by a rolled-back save does not count."""
    with session() as s:
        bike = s.query(models.Bike).filter_by(brand=brand, model=model).first()
        if bike is None:
            return None
        details = s.query(models.BikeDetails).filter_by(bike_id=bike.id).first()
        if details is None or details.updated_at is None or aware(details.updated_at) < since:
            return None
        return bike.id


def store_details(brand: str, model: str, make_response: Callable[[str, str], BikeDetailsResponse],
                  find_id: FindId = find_bike_id) -> tuple[str, int, str, str, Optional[BikeDetailsResponse]]:
    """Store details for a bike unless it already has fresh ones.

    Returns (KEPT, bike_id, stored brand, stored model, None) when fresh details exist (nothing is
    overwritten), else (WRITTEN, bike_id, brand, model, response) after a verified save. An existing
    bike's stored casing is reused, because save_bike_details matches brand/model exactly and would
    otherwise mint a duplicate bike. Raises RuntimeError when the save did not land.
    """
    bike_id = find_id(brand, model)
    if bike_id is not None:
        brand, model, fresh = bike_state(bike_id)
        if fresh:
            return KEPT, bike_id, brand, model, None
    response = make_response(brand, model)
    start = utcnow()
    repository.save_bike_details(brand, model, response)
    # save_bike_details swallows its own errors (WARNING log) and rolls back, so confirm the write landed.
    saved = _saved_bike_id(brand, model, start)
    if saved is None:
        raise RuntimeError("save_bike_details stored nothing (see its warning in the log)")
    return WRITTEN, saved, brand, model, response


def cache_details(company: str, model: str, response, write: bool = True) -> str:
    """Put `response` into the generic cache under POST /v1/bike/details — the only place that endpoint reads.

    `company`/`model` must be the bike row's stored casing (what search returns and the
    frontend sends). First write wins: an existing (e.g. AI-made) entry is kept.
    Returns CACHE_WRITTEN / CACHE_PRESENT / CACHE_FAILED; never raises.
    """
    fields = {"company": company, "model": model}
    try:
        if cache.get_cached(DETAILS_ENDPOINT, fields, BikeDetailsResponse) is not None:
            return CACHE_PRESENT
        if not write:
            return CACHE_WRITTEN
        cache.set_cached(DETAILS_ENDPOINT, fields, response)  # swallows DB errors itself
        if cache.get_cached(DETAILS_ENDPOINT, fields, BikeDetailsResponse) is not None:
            return CACHE_WRITTEN
        logger.warning("cache write for %r %r did not land (see the cache warning)", company, model)
    except Exception as exc:
        logger.warning("cache write for %r %r failed | %s: %s", company, model, type(exc).__name__, exc)
    return CACHE_FAILED
