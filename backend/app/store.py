"""Additive, queryable cache for follow-up search queries.

Sits on top of the generic response cache in `cache.py` (shares the same
`cache.db` connection). Unlike the generic `endpoint_req_to_body_cache`, this is
keyed by semantic identity (the normalised enriched query) and is queryable by
attribute (e.g. find cached bikes by brand), so follow-up requests can be served
without any web/Claude call.

Two tables, both defined as ORM models in `app/models.py` and created by
`init_db()`; this module reads/writes them via the shared raw connection:

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

from .cache import get_conn, _normalise
from .price_parse import parse_price
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


def _get_or_create_bike(conn, brand: str, model: str) -> int:
    """Resolve a bike identity to its `bike.id`, creating the row if needed.

    Lookup is case-insensitive but the row keeps the caller's original casing —
    UNIQUE(brand, model) is case-sensitive, so matching on LOWER() is what stops
    'Trek' and 'trek' becoming two identities (the case-split TODO-019 flags).
    """
    row = conn.execute(
        "SELECT id FROM bike WHERE LOWER(brand) = ? AND LOWER(model) = ?",
        (_norm(brand), _norm(model)),
    ).fetchone()
    if row is not None:
        return row[0]
    cur = conn.execute(
        "INSERT INTO bike (brand, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (brand, model, _now_iso(), _now_iso()),
    )
    return cur.lastrowid


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
    conn = get_conn()
    try:
        norm = _norm(query)
        row = conn.execute(
            "SELECT id FROM search_cache WHERE query = ?", (norm,)
        ).fetchone()
        if row is not None:
            search_id = row[0]
            # Replace this query's bikes wholesale.
            conn.execute(
                "DELETE FROM search_bike_rating_cache WHERE search_cache_id = ?",
                (search_id,),
            )
            conn.execute(
                "UPDATE search_cache SET time_stored = ? WHERE id = ?",
                (_now_iso(), search_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO search_cache (query, time_stored) VALUES (?, ?)",
                (norm, _now_iso()),
            )
            search_id = cur.lastrowid

        for i, b in enumerate(bikes):
            bike_id = _get_or_create_bike(conn, b.brand, b.model)
            conn.execute(
                "INSERT INTO search_bike_rating_cache "
                "(search_cache_id, bike_id, rating, explanation, accessories, display_order) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (search_id, bike_id, b.match_score, b.explanation,
                 json.dumps(b.accessories), i),
            )
        conn.commit()
        logger.info("search_cache store | query=%r bikes=%d", query, len(bikes))
    except Exception as exc:  # noqa: BLE001 — cache writes must never break the request
        conn.rollback()
        logger.warning("search_cache store failed (non-fatal) | %s", exc)


def get_search_by_query(query: str) -> Optional[list[BikeResult]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT id, time_stored FROM search_cache WHERE query = ?",
        (_norm(query),),
    ).fetchone()
    if row is None:
        logger.info("search_cache miss | query=%r", query)
        return None
    search_id, time_stored = row
    if not _is_fresh(time_stored, SEARCH_TTL_SECONDS):
        logger.info("search_cache stale | query=%r", query)
        return None
    logger.info("search_cache hit | query=%r", query)
    rows = conn.execute(
        "SELECT b.brand, b.model, r.rating, r.explanation, r.accessories "
        "FROM search_bike_rating_cache r JOIN bike b ON b.id = r.bike_id "
        "WHERE r.search_cache_id = ? ORDER BY r.display_order, r.id",
        (search_id,),
    ).fetchall()
    return [_row_to_bike(*r) for r in rows]


def _find_rated_bikes(brand: Optional[str], model: Optional[str]) -> list[BikeResult]:
    """Shared lookup-by-attribute over fresh searches. Joins ratings to their
    search (for the freshness check) and to `bike` (for brand/model), filters in
    SQL where it can, dedups by (brand, model). Purely a cache read."""
    conn = get_conn()
    sql = (
        "SELECT s.time_stored, b.brand, b.model, r.rating, r.explanation, r.accessories "
        "FROM search_bike_rating_cache r "
        "JOIN search_cache s ON s.id = r.search_cache_id "
        "JOIN bike b ON b.id = r.bike_id"
    )
    conds, params = [], []
    if brand is not None:
        conds.append("LOWER(b.brand) = ?")
        params.append(_norm(brand))
    if model is not None:
        conds.append("LOWER(b.model) = ?")
        params.append(_norm(model))
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY r.display_order, r.id"

    matches: list[BikeResult] = []
    seen: set[tuple[str, str]] = set()
    for time_stored, br, mo, rating, expl, acc in conn.execute(sql, params).fetchall():
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


def find_bike_by_brand_model(brand: str, model: str) -> list[BikeResult]:
    """Lookup-by-attribute: pull every cached bike matching brand AND model,
    across all fresh cached searches. Purely a cache read — no web/Claude call."""
    try:
        matches = _find_rated_bikes(brand, model)
        logger.info(
            "find_bike_by_brand_model | brand=%r model=%r matches=%d", brand, model, len(matches)
        )
        return matches
    except Exception as exc:  # noqa: BLE001 — cache reads must never break the request
        logger.warning("find_bike_by_brand_model failed (non-fatal) | %s", exc)
        return []


# The four offer endpoints whose cached responses carry a price for a bike.
_OFFER_ENDPOINTS = ("/v1/bike/offer", "/v1/bike/ceneo", "/v1/bike/decathlon", "/v1/bike/used")


def find_offer_prices(brand: str, model: str) -> list[float]:
    """Every parseable offer price for this bike across all offer endpoints.

    Reads the generic `endpoint_req_to_body_cache` table directly — offer rows are
    keyed on the same normalised {company, model} shape `_norm()` produces, so no
    extra mapping is needed. Unparseable prices are dropped, not reported as 0."""
    try:
        conn = get_conn()
        rows = conn.execute(
            "SELECT response FROM endpoint_req_to_body_cache "
            "WHERE endpoint IN (?, ?, ?, ?) AND request = ?",
            (*_OFFER_ENDPOINTS, _normalise({"company": brand, "model": model})),
        ).fetchall()
        prices: list[float] = []
        for (response,) in rows:
            for offer in json.loads(response).get("offers", []):
                price = parse_price(offer.get("price") or "")
                if price is not None:
                    prices.append(price)
        logger.info(
            "find_offer_prices | brand=%r model=%r rows=%d prices=%d",
            brand, model, len(rows), len(prices),
        )
        return prices
    except Exception as exc:  # noqa: BLE001 — cache reads must never break the request
        logger.warning("find_offer_prices failed (non-fatal) | %s", exc)
        return []


# ── bike details ─────────────────────────────────────────────────────────
# `save_bike_details` / `get_bike_details` used to live here, backed by a
# `bike_details_cache` blob table. That table has been migrated into
# `bike_detail` + `bike_detail_component` and dropped; the two helpers now live
# in `repository.py` and `main.py` imports them from there. Nothing in this
# module recreates the old table — that is deliberate, see TODO-019.
