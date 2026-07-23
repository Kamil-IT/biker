"""Additive, queryable cache tables for follow-up queries.

Sits on top of the generic response cache in `cache.py` (shares the same
`cache.db` connection). Unlike the generic cache, these tables are keyed by
semantic identity (normalised query, or company+model) and are queryable by
attribute (e.g. find cached bikes by brand) so follow-up requests can be
served without any web/Claude call.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from .cache import get_conn, _normalise
from .price_parse import parse_price
from .schemas import BikeResult, BikeSearchResponse, BikeDetailsResponse

logger = logging.getLogger(__name__)

# TTL defaults: searches change often, bike specs rarely.
SEARCH_TTL_SECONDS = 24 * 60 * 60          # 24 hours
DETAILS_TTL_SECONDS = 30 * 24 * 60 * 60    # 30 days


def init_store() -> None:
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS search_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            query       TEXT NOT NULL UNIQUE,
            bikes       TEXT NOT NULL,
            time_stored TEXT NOT NULL,
            ttl         INTEGER NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_search_cache_query ON search_cache(query)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bike_details_cache (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company     TEXT NOT NULL,
            model       TEXT NOT NULL,
            description TEXT NOT NULL,
            components  TEXT NOT NULL,
            photos      TEXT NOT NULL,
            time_stored TEXT NOT NULL,
            ttl         INTEGER NOT NULL,
            UNIQUE(company, model)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bike_details_company_model "
        "ON bike_details_cache(company, model)"
    )
    conn.commit()
    logger.info("follow-up cache tables ready (search_cache, bike_details_cache)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_fresh(time_stored: str, ttl: int) -> bool:
    stored = datetime.fromisoformat(time_stored)
    age = (datetime.now(timezone.utc) - stored).total_seconds()
    return age < ttl


def _norm(text: str) -> str:
    return text.strip().lower()


# ── search_cache ──────────────────────────────────────────────────────────

def save_search(query: str, bikes: list[BikeResult], ttl: int = SEARCH_TTL_SECONDS) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO search_cache (query, bikes, time_stored, ttl)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(query) DO UPDATE SET
                bikes = excluded.bikes,
                time_stored = excluded.time_stored,
                ttl = excluded.ttl
            """,
            (
                _norm(query),
                json.dumps([b.model_dump() for b in bikes]),
                _now_iso(),
                ttl,
            ),
        )
        conn.commit()
        logger.info("search_cache store | query=%r bikes=%d", query, len(bikes))
    except Exception as exc:  # noqa: BLE001 — cache writes must never break the request
        logger.warning("search_cache store failed (non-fatal) | %s", exc)


def get_search_by_query(query: str) -> Optional[list[BikeResult]]:
    conn = get_conn()
    row = conn.execute(
        "SELECT bikes, time_stored, ttl FROM search_cache WHERE query = ?",
        (_norm(query),),
    ).fetchone()
    if row is None:
        logger.info("search_cache miss | query=%r", query)
        return None
    bikes_json, time_stored, ttl = row
    if not _is_fresh(time_stored, ttl):
        logger.info("search_cache stale | query=%r", query)
        return None
    logger.info("search_cache hit | query=%r", query)
    return [BikeResult.model_validate(b) for b in json.loads(bikes_json)]


def find_bikes_by_brand(brand: str) -> list[BikeResult]:
    """Lookup-by-attribute: pull every cached bike whose brand matches, across
    all fresh cached searches. Purely a cache read — no web/Claude call."""
    conn = get_conn()
    rows = conn.execute("SELECT bikes, time_stored, ttl FROM search_cache").fetchall()
    needle = _norm(brand)
    matches: list[BikeResult] = []
    seen: set[tuple[str, str]] = set()
    for bikes_json, time_stored, ttl in rows:
        if not _is_fresh(time_stored, ttl):
            continue
        for b in json.loads(bikes_json):
            if _norm(b.get("brand", "")) == needle:
                key = (_norm(b.get("brand", "")), _norm(b.get("model", "")))
                if key in seen:
                    continue
                seen.add(key)
                matches.append(BikeResult.model_validate(b))
    logger.info("find_bikes_by_brand | brand=%r matches=%d", brand, len(matches))
    return matches


def find_bike_by_brand_model(brand: str, model: str) -> list[BikeResult]:
    """Lookup-by-attribute: pull every cached bike matching brand AND model,
    across all fresh cached searches. Purely a cache read — no web/Claude call."""
    try:
        conn = get_conn()
        rows = conn.execute("SELECT bikes, time_stored, ttl FROM search_cache").fetchall()
        want = (_norm(brand), _norm(model))
        matches: list[BikeResult] = []
        seen: set[tuple[str, str]] = set()
        for bikes_json, time_stored, ttl in rows:
            if not _is_fresh(time_stored, ttl):
                continue
            for b in json.loads(bikes_json):
                key = (_norm(b.get("brand", "")), _norm(b.get("model", "")))
                if key != want or key in seen:
                    continue
                seen.add(key)
                matches.append(BikeResult.model_validate(b))
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

    Reads the generic `cache` table directly — offer rows are keyed on the same
    normalised {company, model} shape `_norm()` produces, so no extra mapping is
    needed. Unparseable prices are dropped, not reported as 0."""
    try:
        conn = get_conn()
        rows = conn.execute(
            "SELECT response FROM cache WHERE endpoint IN (?, ?, ?, ?) AND request = ?",
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


# ── bike_details_cache ────────────────────────────────────────────────────

def save_bike_details(
    company: str, model: str, data: BikeDetailsResponse, ttl: int = DETAILS_TTL_SECONDS
) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO bike_details_cache
                (company, model, description, components, photos, time_stored, ttl)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company, model) DO UPDATE SET
                description = excluded.description,
                components = excluded.components,
                photos = excluded.photos,
                time_stored = excluded.time_stored,
                ttl = excluded.ttl
            """,
            (
                _norm(company),
                _norm(model),
                data.description.model_dump_json(),
                json.dumps([c.model_dump() for c in data.components]),
                json.dumps(data.photos),
                _now_iso(),
                ttl,
            ),
        )
        conn.commit()
        logger.info("bike_details_cache store | company=%r model=%r", company, model)
    except Exception as exc:  # noqa: BLE001
        logger.warning("bike_details_cache store failed (non-fatal) | %s", exc)


def get_bike_details(company: str, model: str) -> Optional[BikeDetailsResponse]:
    conn = get_conn()
    row = conn.execute(
        "SELECT company, model, description, components, photos, time_stored, ttl "
        "FROM bike_details_cache WHERE company = ? AND model = ?",
        (_norm(company), _norm(model)),
    ).fetchone()
    if row is None:
        logger.info("bike_details_cache miss | company=%r model=%r", company, model)
        return None
    _company, _model, description, components, photos, time_stored, ttl = row
    if not _is_fresh(time_stored, ttl):
        logger.info("bike_details_cache stale | company=%r model=%r", company, model)
        return None
    logger.info("bike_details_cache hit | company=%r model=%r", company, model)
    return BikeDetailsResponse.model_validate(
        {
            "company": company,
            "model": model,
            "description": json.loads(description),
            "components": json.loads(components),
            "photos": json.loads(photos),
        }
    )
