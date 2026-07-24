"""Offer price lookup over the generic response cache.

What is left of the old blob-cache layer. Both of its tables have moved to the
normalised ORM tables in `app/repository.py` — `bike_details_cache` and
`search_cache` alike (TODO-019).

`find_offer_prices` stays here because it reads the generic `cache` table in
`cache.py` rather than a table of its own: the ORM's `bike_offers` is empty and
nothing populates it, so there is no ORM equivalent to move it to yet.
"""
import json
import logging

from .cache import get_conn, _normalise
from .price_parse import parse_price

logger = logging.getLogger(__name__)


def init_store() -> None:
    """No tables of its own any more — kept as the app's startup hook."""
    logger.info("store ready (offer price lookup only; search + details are ORM-backed)")


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
