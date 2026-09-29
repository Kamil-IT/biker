"""Stored bike photos — the read side of bike_detail_photos.

Photos are keyed on `bike` (column `bike_id`), independent of the details
row: POST /v1/bike/photos reads them here, and the searcher service's photo
search (searcher/app/repository.py) writes them, only for a bike that has
none. No TTL and nothing is ever replaced. Lives next to repository.py rather
than in it, like offers_repository.py, to keep that file under 500 lines.
"""
import logging

from .models import BikeDetailPhoto, get_session
from .repository import _find_bike_id
from .schemas import BikePhotosResponse

logger = logging.getLogger(__name__)

MIGRATION_HINT = "run backend/scripts/migrate_photos_bike_id.py"


def _is_unmigrated(exc: Exception) -> bool:
    """True when the error is the old bike_detail_photos schema (no bike_id column).

    create_all() never ALTERs an existing table, so a database from before the
    re-key still has bike_detail_id. SQLite says "no such column", PostgreSQL
    "column ... does not exist".
    """
    msg = str(exc).lower()
    return "bike_id" in msg and ("no such column" in msg or "does not exist" in msg)


def _log_db_error(what: str, company: str, model: str, exc: Exception) -> None:
    if _is_unmigrated(exc):
        logger.error(
            "%s: bike_detail_photos has no bike_id column — database not migrated, %s | company=%r model=%r | %s",
            what, MIGRATION_HINT, company, model, exc,
        )
    else:
        logger.error("%s failed | company=%r model=%r | %s", what, company, model, exc)


def get_bike_photos(company: str, model: str) -> BikePhotosResponse:
    """Stored photos of one bike, ordered by display_order, id — a pure DB read.

    An unknown bike, no rows, or a DB error (an unmigrated table included) all
    yield an empty response — the details view must keep rendering.
    """
    session = get_session()
    try:
        bike_id = _find_bike_id(session, company, model)
        if bike_id is None:
            logger.info("stored photos: bike not found | company=%r model=%r", company, model)
            return BikePhotosResponse(photos=[])
        urls = [
            url for (url,) in session.query(BikeDetailPhoto.url)
            .filter(BikeDetailPhoto.bike_id == bike_id)
            .order_by(BikeDetailPhoto.display_order, BikeDetailPhoto.id)
        ]
        logger.info(
            "stored photos served from DB | company=%r model=%r bike_id=%d photos=%d",
            company, model, bike_id, len(urls),
        )
        return BikePhotosResponse(photos=urls)
    except Exception as exc:  # noqa: BLE001 — a DB read must never break the details view
        _log_db_error("stored photos read", company, model, exc)
        return BikePhotosResponse(photos=[])
    finally:
        session.close()


def save_bike_photos(company: str, model: str, photos: list[str]) -> int:
    """Store photos for an existing bike that has none yet; returns rows written.

    Same rule as the searcher: a bike's photos are never replaced, so a bike
    that already has photos, an unknown bike or an empty list writes nothing.
    Used by the offline pipeline (docs/bikes/pipeline/db_saver.py), which used
    to store photos through save_bike_details.
    """
    urls = [u for u in photos if u]
    if not urls:
        return 0
    session = get_session()
    try:
        bike_id = _find_bike_id(session, company, model)
        if bike_id is None:
            logger.warning("save photos: bike not found | company=%r model=%r", company, model)
            return 0
        if session.query(BikeDetailPhoto.id).filter(BikeDetailPhoto.bike_id == bike_id).first():
            logger.info("save photos: bike already has photos, kept | company=%r model=%r", company, model)
            return 0
        session.add_all(
            BikeDetailPhoto(bike_id=bike_id, url=url, display_order=idx)
            for idx, url in enumerate(urls)
        )
        session.commit()
        logger.info("photos stored | company=%r model=%r photos=%d", company, model, len(urls))
        return len(urls)
    except Exception as exc:  # noqa: BLE001 — mirrors save_bike_details: non-fatal
        session.rollback()
        _log_db_error("save photos", company, model, exc)
        return 0
    finally:
        session.close()
