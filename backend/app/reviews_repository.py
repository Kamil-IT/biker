"""Stored expert reviews — the read side of bike_review / bike_review_source (TODO-037).

Every row is written by the separate searcher service (POST /v1/search/review,
searcher/app/repository.py) or copied once from the generic cache by
scripts/copy_review_cache_to_table.py; POST /v1/bike/review only reads them.
No AI, no generic cache, no TTL.
"""
import logging

from .models import BikeReview, BikeReviewSource, get_session
from .repository import _find_bike_id
from .schemas import BikeReviewResponse

logger = logging.getLogger(__name__)

# What POST /v1/bike/review answers when nothing is stored: the frontend reads
# an empty `ref` with sources_used 0 as "no data" and rating 0 as "Brak oceny".
EMPTY_REVIEW = BikeReviewResponse(score=0, explanation="", ref=[], rating=0.0, sources_used=0)


def get_review(company: str, model: str) -> BikeReviewResponse:
    """The stored review of one bike, `ref` in display_order — a pure DB read.

    The bike is matched by Python-normalised brand/model (never SQL lower()).
    An unknown bike, a bike without a review, or a DB error (logged at ERROR)
    all yield EMPTY_REVIEW — the details view must keep rendering.
    """
    session = get_session()
    try:
        bike_id = _find_bike_id(session, company, model)
        if bike_id is None:
            logger.info("stored review: bike not found | company=%r model=%r", company, model)
            return EMPTY_REVIEW.model_copy(deep=True)
        row = session.query(BikeReview).filter(BikeReview.bike_id == bike_id).one_or_none()
        if row is None:
            logger.info("stored review: none for bike | company=%r model=%r bike_id=%d", company, model, bike_id)
            return EMPTY_REVIEW.model_copy(deep=True)
        ref = [
            url for (url,) in session.query(BikeReviewSource.url)
            .filter(BikeReviewSource.review_id == row.id)
            .order_by(BikeReviewSource.display_order, BikeReviewSource.id)
        ]
        logger.info(
            "stored review served from DB | company=%r model=%r bike_id=%d rating=%.1f sources=%d",
            company, model, bike_id, row.rating, len(ref),
        )
        return BikeReviewResponse(
            score=row.score, explanation=row.explanation, ref=ref,
            rating=row.rating, sources_used=row.sources_used,
        )
    except Exception as exc:  # noqa: BLE001 — a DB read must never break the details view
        logger.error("stored review read failed | company=%r model=%r | %s", company, model, exc)
        return EMPTY_REVIEW.model_copy(deep=True)
    finally:
        session.close()


# The name the TODO-037 contract uses.
get_bike_review = get_review
