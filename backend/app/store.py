"""Additive, queryable cache for follow-up search queries.

Sits on top of the generic response cache in `cache.py` (same database, via
the shared SQLAlchemy engine in `models.py`). Unlike the generic
`endpoint_req_to_body_cache`, this is keyed by semantic identity (the normalised
enriched query) and is queryable by attribute (e.g. find cached bikes by brand),
so follow-up requests can be served without any web/Claude call.

Two tables, both defined as ORM models in `app/models.py` and created by
`init_db()`; this module reads/writes them through ORM sessions:

- `search_cache`               — one row per query: `query`, `time_stored`.
- `search_bike_rating_cache`   — one row per bike a search returned: FK to
  `search_cache`, FK to `bike`, `rating`, `explanation`, `accessories` (inline
  JSON array), `display_order`.

Freshness is `time_stored + SEARCH_TTL_SECONDS`; there is no per-row ttl column.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func

from .models import Bike, SearchBikeRating, SearchCache, get_session
from .schemas import BikeResult

logger = logging.getLogger(__name__)

# Searches change often, so cached rows expire after a day.
SEARCH_TTL_SECONDS = 24 * 60 * 60          # 24 hours


def init_store() -> None:
    # The search-cache tables are ORM models now (app/models.py), created by
    # init_db(). Nothing to create here; kept as a lifespan hook / log marker.
    logger.info("follow-up cache ready (search_cache, search_bike_rating_cache — ORM)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_fresh(time_stored: str, ttl: int) -> bool:
    stored = datetime.fromisoformat(time_stored)
    age = (datetime.now(timezone.utc) - stored).total_seconds()
    return age < ttl


def _norm(text: str) -> str:
    return text.strip().lower()


# ── search_cache / search_bike_rating_cache ────────────────────────────────
#
# One search fans out to many rated bikes. `search_cache` holds the query and
# when it was stored; each returned bike is one `search_bike_rating_cache` row
# carrying the per-*search* fields (rating, explanation, accessories) plus a FK
# to the canonical `bike`. brand/model are never duplicated — they come via the
# FK. accessories is stored inline as a JSON array of strings.


def _get_or_create_bike(session, brand: str, model: str) -> int:
    """Resolve a bike identity to its `bike.id`, creating the row if needed.

    Lookup is case-insensitive but the row keeps the caller's original casing —
    UNIQUE(brand, model) is case-sensitive, so matching on LOWER() is what stops
    'Trek' and 'trek' becoming two identities (the case-split TODO-019 flags).
    """
    bike_id = (
        session.query(Bike.id)
        .filter(func.lower(Bike.brand) == _norm(brand), func.lower(Bike.model) == _norm(model))
        .order_by(Bike.id)
        .limit(1)
        .scalar()
    )
    if bike_id is not None:
        return bike_id
    bike = Bike(brand=brand, model=model)
    session.add(bike)
    session.flush()
    return bike.id


def _row_to_bike(brand, model, rating, explanation, accessories_json) -> BikeResult:
    """Turn one joined rating row back into a BikeResult schema."""
    try:
        accessories = json.loads(accessories_json) if accessories_json else []
    except (TypeError, ValueError):
        accessories = []
    return BikeResult(
        brand=brand,
        model=model,
        accessories=accessories,
        match_score=rating,
        explanation=explanation,
    )


def save_search(query: str, bikes: list[BikeResult], ttl: int = SEARCH_TTL_SECONDS) -> None:
    """Upsert a search and its rated bikes. `ttl` is accepted for signature
    compatibility but unused — freshness comes from SEARCH_TTL_SECONDS."""
    session = get_session()
    try:
        norm = _norm(query)
        search = session.query(SearchCache).filter_by(query=norm).first()
        if search is not None:
            # Replace this query's bikes wholesale.
            session.query(SearchBikeRating).filter_by(search_cache_id=search.id).delete()
            search.time_stored = _now_iso()
        else:
            search = SearchCache(query=norm, time_stored=_now_iso())
            session.add(search)
        session.flush()

        for i, b in enumerate(bikes):
            session.add(SearchBikeRating(
                search_cache_id=search.id,
                bike_id=_get_or_create_bike(session, b.brand, b.model),
                rating=b.match_score,
                explanation=b.explanation,
                accessories=json.dumps(b.accessories),
                display_order=i,
            ))
        session.commit()
        logger.info("search_cache store | query=%r bikes=%d", query, len(bikes))
    except Exception as exc:  # noqa: BLE001 — cache writes must never break the request
        session.rollback()
        logger.warning("search_cache store failed (non-fatal) | %s", exc)
    finally:
        session.close()


# brand, model, rating, explanation, accessories — the columns _row_to_bike takes.
_RATED_COLUMNS = (
    Bike.brand, Bike.model, SearchBikeRating.rating,
    SearchBikeRating.explanation, SearchBikeRating.accessories,
)


def get_search_by_query(query: str) -> Optional[list[BikeResult]]:
    session = get_session()
    try:
        search = (
            session.query(SearchCache.id, SearchCache.time_stored)
            .filter_by(query=_norm(query))
            .first()
        )
        if search is None:
            logger.info("search_cache miss | query=%r", query)
            return None
        if not _is_fresh(search.time_stored, SEARCH_TTL_SECONDS):
            logger.info("search_cache stale | query=%r", query)
            return None
        logger.info("search_cache hit | query=%r", query)
        rows = (
            session.query(*_RATED_COLUMNS)
            .select_from(SearchBikeRating)
            .join(Bike, Bike.id == SearchBikeRating.bike_id)
            .filter(SearchBikeRating.search_cache_id == search.id)
            .order_by(SearchBikeRating.display_order, SearchBikeRating.id)
            .all()
        )
        return [_row_to_bike(*r) for r in rows]
    finally:
        session.close()


def _find_rated_bikes(brand: Optional[str], model: Optional[str]) -> list[BikeResult]:
    """Shared lookup-by-attribute over fresh searches. Joins ratings to their
    search (for the freshness check) and to `bike` (for brand/model), filters in
    SQL where it can, dedups by (brand, model). Purely a cache read."""
    session = get_session()
    try:
        q = (
            session.query(SearchCache.time_stored, *_RATED_COLUMNS)
            .select_from(SearchBikeRating)
            .join(SearchCache, SearchCache.id == SearchBikeRating.search_cache_id)
            .join(Bike, Bike.id == SearchBikeRating.bike_id)
        )
        if brand is not None:
            q = q.filter(func.lower(Bike.brand) == _norm(brand))
        if model is not None:
            q = q.filter(func.lower(Bike.model) == _norm(model))
        rows = q.order_by(SearchBikeRating.display_order, SearchBikeRating.id).all()
    finally:
        session.close()

    matches: list[BikeResult] = []
    seen: set[tuple[str, str]] = set()
    for time_stored, br, mo, rating, expl, acc in rows:
        if not _is_fresh(time_stored, SEARCH_TTL_SECONDS):
            continue
        key = (_norm(br), _norm(mo))
        if key in seen:
            continue
        seen.add(key)
        matches.append(_row_to_bike(br, mo, rating, expl, acc))
    return matches


def find_bikes_by_brand(brand: str) -> list[BikeResult]:
    """Lookup-by-attribute: pull every cached bike whose brand matches, across
    all fresh cached searches. Purely a cache read — no web/Claude call."""
    try:
        matches = _find_rated_bikes(brand, None)
        logger.info("find_bikes_by_brand | brand=%r matches=%d", brand, len(matches))
        return matches
    except Exception as exc:  # noqa: BLE001 — cache reads must never break the request
        logger.warning("find_bikes_by_brand failed (non-fatal) | %s", exc)
        return []


# ── bike details ─────────────────────────────────────────────────────────
# `save_bike_details` / `get_bike_details` used to live here, backed by a
# `bike_details_cache` blob table. That table has been migrated into
# `bike_detail` + `bike_detail_component` and dropped; the two helpers now live
# in `repository.py` and `main.py` imports them from there. Nothing in this
# module recreates the old table — that is deliberate, see TODO-019.
