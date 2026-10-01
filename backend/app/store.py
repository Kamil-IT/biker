"""Stores the bikes an AI search found (`save_search`).

Same database as the generic response cache in `cache.py` (the shared
SQLAlchemy engine in `models.py`). The only thing a search leaves behind is a
`bike` row per found bike, so a later brand/model search finds it in the DB
and the details view can open it (`bike_exists` guards every on-demand search).

The per-search tables (`search_cache`, `search_bike_rating_cache`) were
dropped in TODO-043: nothing had read them since the cache-read endpoints went
(TODO-024/025), and their last payload columns were written as `""` / `"[]"`
since TODO-041. `scripts/migrate_drop_search_tables.py` removes them from an
existing database.
"""
import logging

from .models import Bike, get_session
from .repository import _find_bike_id
from .schemas import BikeResult

logger = logging.getLogger(__name__)


def init_store() -> None:
    # Owns no tables (every table is an ORM model created by init_db()); kept as
    # the app's lifespan hook / log marker.
    logger.info("search store ready (AI-found bikes go into `bike` only)")


def _get_or_create_bike(session, brand: str, model: str) -> tuple[int, bool]:
    """Resolve a bike identity to `(bike.id, created)`, creating the row if needed.

    The lookup is normalised in Python (`repository._find_bike_id`, never SQL
    `lower()`); a new row keeps the caller's casing.
    """
    bike_id = _find_bike_id(session, brand, model)
    if bike_id is not None:
        return bike_id, False
    bike = Bike(brand=brand, model=model)
    session.add(bike)
    session.flush()
    return bike.id, True


def save_search(query: str, bikes: list[BikeResult]) -> None:
    """Make sure every bike the AI returned exists in `bike`. Non-fatal."""
    session = get_session()
    try:
        created = sum(_get_or_create_bike(session, b.brand, b.model)[1] for b in bikes)
        session.commit()
        logger.info("search store | query=%r bikes=%d new=%d", query, len(bikes), created)
    except Exception as exc:  # noqa: BLE001 — store writes must never break the request
        session.rollback()
        logger.warning("search store failed (non-fatal) | %s", exc)
    finally:
        session.close()
