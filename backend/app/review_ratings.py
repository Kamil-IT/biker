"""Expert ratings of stored reviews for a batch of bikes — POST /v1/bike/review/cached (TODO-040).

The search results show each bike's expert rating, but only when its review is
already stored in `bike_review` (TODO-037: written by the searcher service or
copied once by scripts/copy_review_cache_to_table.py). No AI call, no write:
a bike without a stored review stays unrated ("?" in the UI) and nothing is
fetched for it. The old generic-cache rows under /v1/bike/review are not read.
"""
import logging

from .models import Bike, BikeReview, get_session
from .repository import _lc
from .schemas import CachedRating, CachedRatingItem, CachedRatingsResponse

logger = logging.getLogger(__name__)


def _key(company: str, model: str) -> tuple[str, str]:
    # The same Python normalisation as repository._find_bike_id (never SQL lower(),
    # which is ASCII-only in SQLite).
    return _lc(company), _lc(model)


def _stored_ratings(items: list[CachedRatingItem]) -> dict[tuple[str, str], float]:
    """Usable stored rating per requested identity: two queries for the whole batch."""
    wanted = {_key(i.company, i.model) for i in items}
    session = get_session()
    try:
        bike_ids: dict[tuple[str, str], int] = {}
        # Oldest row wins should a case-split duplicate identity exist — as in _find_bike_id.
        for bike_id, brand, model in session.query(Bike.id, Bike.brand, Bike.model).order_by(Bike.id):
            key = _key(brand, model)
            if key in wanted and key not in bike_ids:
                bike_ids[key] = bike_id
        if not bike_ids:
            return {}
        rows = (
            session.query(BikeReview.bike_id, BikeReview.rating, BikeReview.sources_used)
            .filter(BikeReview.bike_id.in_(list(bike_ids.values())))
            .all()
        )
        # rating 0 or no source = the "no review" placeholder, never a real 0/10.
        usable = {bike_id: rating for bike_id, rating, sources in rows if rating > 0 and sources >= 1}
        return {key: usable[bike_id] for key, bike_id in bike_ids.items() if bike_id in usable}
    finally:
        session.close()


def get_cached_ratings(items: list[CachedRatingItem]) -> CachedRatingsResponse:
    """One entry per requested bike, same order, company/model echoed as sent.

    Unknown bike, no bike_review row, rating <= 0 or sources_used < 1 → found
    false. A DB error → found false for every bike (logged at ERROR).
    """
    try:
        stored = _stored_ratings(items)
    except Exception as exc:  # noqa: BLE001 — a DB read must never 500 the results page
        logger.error("cached ratings read failed — answering found=false for all | %s", exc)
        stored = {}
    ratings = []
    for item in items:
        rating = stored.get(_key(item.company, item.model))
        ratings.append(CachedRating(
            company=item.company, model=item.model,
            rating=round(float(rating), 1) if rating is not None else None,
            found=rating is not None,
        ))
    return CachedRatingsResponse(ratings=ratings)
