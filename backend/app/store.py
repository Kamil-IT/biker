"""Stores the bikes an AI search found (`save_search`).

Same database as the generic response cache in `cache.py` (the shared
SQLAlchemy engine in `models.py`). The only thing a search leaves behind is a
`bike` row per found bike (with the search's category where it had none), so a
later brand/model/category search finds it in the DB and the details view can
open it (`bike_exists` guards every on-demand search).

The per-search tables (`search_cache`, `search_bike_rating_cache`) were
dropped in TODO-043: nothing had read them since the cache-read endpoints went
(TODO-024/025), and their last payload columns were written as `""` / `"[]"`
since TODO-041. `scripts/migrate_drop_search_tables.py` removes them from an
existing database.
"""
import logging
from typing import Optional

from .bike_categories import category_for_ai_result
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


def save_search(query: str, bikes: list[BikeResult], bike_type: Optional[str] = None) -> None:
    """Make sure every bike the AI returned exists in `bike`. Non-fatal.

    With a search category (`bike_type`) every found bike whose category is
    still NULL gets `category_for_ai_result(bike_type)` — a stored category is
    never overwritten — so the next search by that category finds it in the DB.
    """
    category = category_for_ai_result(bike_type)
    session = get_session()
    try:
        ids = [_get_or_create_bike(session, b.brand, b.model) for b in bikes]
        created = sum(new for _, new in ids)
        stamped = 0
        if category is not None:
            stamped = session.query(Bike).filter(
                Bike.id.in_([bike_id for bike_id, _ in ids]), Bike.category.is_(None),
            ).update({Bike.category: category}, synchronize_session=False)
        session.commit()
        logger.info(
            "search store | query=%r bikes=%d new=%d category=%r stamped=%d",
            query, len(bikes), created, category, stamped,
        )
    except Exception as exc:  # noqa: BLE001 — store writes must never break the request
        session.rollback()
        logger.warning("search store failed (non-fatal) | %s", exc)
    finally:
        session.close()
