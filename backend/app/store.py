"""Stores the bikes an AI search found (`save_search`).

Same database as the generic response cache in `cache.py` (the shared
SQLAlchemy engine in `models.py`). Write-only since the `GET /v1/bike/search-cache`
reader was removed: the rows put the found bikes into `bike`, so a later
brand/model search finds them in the DB.

Two tables, both defined as ORM models in `app/models.py` and created by
`init_db()`; this module reads/writes them through ORM sessions:

- `search_cache`               — one row per query: `query`, `time_stored`.
- `search_bike_rating_cache`   — one row per bike a search returned: FK to
  `search_cache`, FK to `bike`, `explanation`, `accessories` (inline
  JSON array), `display_order` (the AI answer's order). Since TODO-041 the last two
  hold `""` / `"[]"` and nothing reads them: a result's explanation / accessories are
  filled from the bike's stored details (repository.fill_bike_results). The `rating` column
  (the old match score) was dropped in TODO-040 — `scripts/migrate_drop_search_rating.py`.

`time_stored` is refreshed on every save; nothing reads it any more.
"""
import logging
from datetime import datetime, timezone

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


def _norm(text: str) -> str:
    return text.strip().lower()


# ── search_cache / search_bike_rating_cache ────────────────────────────────
#
# One search fans out to many rated bikes. `search_cache` holds the query and
# when it was stored; each returned bike is one `search_bike_rating_cache` row
# carrying the per-*search* fields (explanation, accessories) plus a FK
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
                explanation="",
                accessories="[]",
                display_order=i,
            ))
        session.commit()
        logger.info("search_cache store | query=%r bikes=%d", query, len(bikes))
    except Exception as exc:  # noqa: BLE001 — cache writes must never break the request
        session.rollback()
        logger.warning("search_cache store failed (non-fatal) | %s", exc)
    finally:
        session.close()


# ── bike details ─────────────────────────────────────────────────────────
# `save_bike_details` / `get_bike_details` used to live here, backed by a
# `bike_details_cache` blob table. That table has been migrated into
# `bike_detail` + `bike_detail_component` and dropped; the two helpers now live
# in `repository.py` and `main.py` imports them from there. Nothing in this
# module recreates the old table — that is deliberate, see TODO-019.
