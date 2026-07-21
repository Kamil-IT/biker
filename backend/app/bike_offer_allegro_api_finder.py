import logging
import os
import time

import httpx

from .schemas import BikeOffer, BikeOfferResponse

logger = logging.getLogger("biker.offer.allegro_api")

# Sandbox by default; set ALLEGRO_ENV=production to hit the live API.
_SANDBOX_BASE = "https://api.allegro.pl.allegrosandbox.pl"
_PRODUCTION_BASE = "https://api.allegro.pl"
_SANDBOX_AUTH = "https://allegro.pl.allegrosandbox.pl/auth/oauth/token"
_PRODUCTION_AUTH = "https://allegro.pl/auth/oauth/token"

# Allegro "Rowery" (bikes) category id. Same id in sandbox and production.
_BIKES_CATEGORY_ID = "1112"

_ACCEPT = "application/vnd.allegro.public.v1+json"
_REFRESH_SKEW_SECONDS = 60  # refresh a bit before the token actually expires

# Module-level token cache: {"token": str, "expires_at": float}
_token_cache: dict[str, object] = {}


def _is_production() -> bool:
    return os.getenv("ALLEGRO_ENV", "sandbox").strip().lower() == "production"


def _api_base() -> str:
    return _PRODUCTION_BASE if _is_production() else _SANDBOX_BASE


def _auth_url() -> str:
    return _PRODUCTION_AUTH if _is_production() else _SANDBOX_AUTH


async def _get_token() -> str | None:
    """Return a cached OAuth2 token, fetching a new one when missing/expired."""
    now = time.time()
    cached_token = _token_cache.get("token")
    expires_at = _token_cache.get("expires_at", 0.0)
    if cached_token and isinstance(expires_at, (int, float)) and now < expires_at:
        logger.info("allegro token cache hit | expires_in=%.0fs", expires_at - now)
        return str(cached_token)

    client_id = os.getenv("ALLEGRO_CLIENT_ID", "").strip()
    client_secret = os.getenv("ALLEGRO_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        logger.warning("ALLEGRO_CLIENT_ID / ALLEGRO_CLIENT_SECRET not set")
        return None

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                _auth_url(),
                data={"grant_type": "client_credentials"},
                auth=(client_id, client_secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("allegro token request failed | %s", exc)
        return None

    data = resp.json()
    token = data.get("access_token")
    expires_in = data.get("expires_in", 3600)
    if not token:
        logger.error("allegro token response missing access_token | %r", data)
        return None

    _token_cache["token"] = token
    _token_cache["expires_at"] = time.time() + max(0, int(expires_in) - _REFRESH_SKEW_SECONDS)
    logger.info("allegro token obtained | expires_in=%ss", expires_in)
    return str(token)


def _extract_price(offer: dict) -> str:
    selling_mode = offer.get("sellingMode") or {}
    price = selling_mode.get("price") or {}
    amount = price.get("amount", "")
    currency = price.get("currency", "")
    if amount and currency:
        return f"{amount} {currency}"
    return str(amount or "")


def _extract_photos(offer: dict) -> list[str]:
    images = offer.get("images") or []
    urls: list[str] = []
    for img in images:
        if isinstance(img, dict) and img.get("url"):
            urls.append(str(img["url"]))
        elif isinstance(img, str):
            urls.append(img)
    return urls


def _map_offer(item: dict, company: str, model: str) -> BikeOffer | None:
    try:
        selling_mode = item.get("sellingMode") or {}
        # Only BUY_NOW / fixed-price offers carry a usable price + url.
        offer_id = item.get("id", "")
        url = f"https://allegro.pl/oferta/{offer_id}" if offer_id else ""
        condition = ""
        for param in item.get("parameters", []) or []:
            if isinstance(param, dict) and param.get("name", "").lower() in ("stan", "condition"):
                values = param.get("values") or []
                condition = str(values[0]).lower() if values else ""
                break
        is_new = "now" in condition or "new" in condition
        return BikeOffer(
            brand=company,
            model=model,
            price=_extract_price(item) or (str(selling_mode.get("format", ""))),
            is_new=is_new,
            url=url,
            photos=_extract_photos(item),
            source="allegro.pl",
        )
    except Exception as exc:
        logger.warning("skipping malformed allegro offer: %s | item=%r", exc, item)
        return None


async def find_allegro_api_offers(company: str, model: str) -> BikeOfferResponse:
    token = await _get_token()
    if token is None:
        return BikeOfferResponse(
            offers=[],
            info="Allegro API credentials missing or token request failed.",
        )

    phrase = f"{company} {model}".strip()
    params = {
        "phrase": phrase,
        "category.id": _BIKES_CATEGORY_ID,
        "limit": "10",
    }
    t = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{_api_base()}/offers/listing",
                params=params,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": _ACCEPT,
                },
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:300]
        logger.error("allegro listing failed | status=%s body=%r", exc.response.status_code, body)
        return BikeOfferResponse(
            offers=[],
            info=f"Allegro listing error (HTTP {exc.response.status_code}). "
            "Note: /offers/listing requires a verified Allegro application.",
        )
    except httpx.HTTPError as exc:
        logger.error("allegro listing request failed | %s", exc)
        return BikeOfferResponse(offers=[], info=f"Allegro listing request failed: {exc}")

    elapsed = time.perf_counter() - t
    data = resp.json()
    items = data.get("items", {}) or {}
    promoted = items.get("promoted", []) or []
    regular = items.get("regular", []) or []
    raw_offers = (promoted + regular)[:3]
    logger.info(
        "allegro listing done | phrase=%r elapsed=%.2fs promoted=%d regular=%d",
        phrase, elapsed, len(promoted), len(regular),
    )

    offers: list[BikeOffer] = []
    for item in raw_offers:
        mapped = _map_offer(item, company, model)
        if mapped is not None:
            offers.append(mapped)

    info = "" if offers else "No offers found on Allegro."
    return BikeOfferResponse(offers=offers, info=info)
