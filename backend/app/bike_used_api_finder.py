"""Used-bike offers from the official OLX Partner REST API.

Runs alongside the web-search + Playwright scraper in ``bike_used_finder.py``.
Uses OAuth2 client-credentials to obtain a bearer token (cached until expiry),
then queries the OLX adverts endpoint by phrase within the bikes category.

Graceful degradation is the priority: missing credentials, OAuth failure, or a
non-200 from OLX all return ``UsedBikeResponse(offers=[], info=...)`` — never a 502.
"""

import logging
import os
import time

import httpx

from .schemas import BikeOffer, UsedBikeResponse

logger = logging.getLogger("biker.used_api")

# OLX.pl "Rowery" (bikes) leaf-ish category. Override via OLX_BIKES_CATEGORY_ID.
_DEFAULT_BIKES_CATEGORY_ID = 1466
_REGION_PL = "PL"
_TOKEN_SCOPE = "v2 read"
_MAX_OFFERS = 5

_HOSTS = {
    "production": "https://www.olx.pl",
    "sandbox": "https://www.olx.pl",
}

# Module-level token cache shared across requests.
_token_cache: dict = {"token": None, "expires_at": 0.0}


def _base_url() -> str:
    env = (os.getenv("OLX_ENV") or "sandbox").strip().lower()
    return os.getenv("OLX_API_BASE") or _HOSTS.get(env, _HOSTS["sandbox"])


def _credentials() -> tuple[str, str] | None:
    client_id = (os.getenv("OLX_CLIENT_ID") or "").strip()
    client_secret = (os.getenv("OLX_CLIENT_SECRET") or "").strip()
    if not client_id or not client_secret:
        return None
    return client_id, client_secret


async def _get_token(client: httpx.AsyncClient) -> str | None:
    """Return a cached bearer token, refreshing via client-credentials when stale."""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"]:
        return _token_cache["token"]

    creds = _credentials()
    if creds is None:
        return None
    client_id, client_secret = creds

    try:
        resp = await client.post(
            f"{_base_url()}/api/open/oauth/token",
            json={
                "grant_type": "client_credentials",
                "scope": _TOKEN_SCOPE,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Content-Type": "application/json"},
        )
    except httpx.HTTPError as exc:
        logger.error("OLX token request failed | %s", exc)
        return None

    if resp.status_code != 200:
        logger.error("OLX token non-200 | status=%d body=%r", resp.status_code, resp.text[:300])
        return None

    data = resp.json()
    token = data.get("access_token")
    if not token:
        logger.error("OLX token response missing access_token | body=%r", str(data)[:300])
        return None

    expires_in = int(data.get("expires_in", 3600))
    # Refresh a minute early to avoid using a token that expires mid-request.
    _token_cache["token"] = token
    _token_cache["expires_at"] = now + max(expires_in - 60, 0)
    logger.info("OLX token obtained | expires_in=%ds", expires_in)
    return token


def _extract_price(advert: dict) -> str:
    for param in advert.get("params", []):
        if param.get("key") == "price":
            value = param.get("value") or {}
            label = value.get("label")
            if label:
                return str(label)
            amount = value.get("value")
            currency = value.get("currency", "")
            if amount is not None:
                return f"{amount} {currency}".strip()
    return ""


def _extract_photos(advert: dict) -> list[str]:
    photos: list[str] = []
    for photo in advert.get("photos", []):
        link = photo.get("link") or ""
        if not link:
            continue
        # OLX photo links may carry {width}x{height} placeholders.
        link = link.replace("{width}", "800").replace("{height}", "600")
        photos.append(link)
    return photos[:4]


def _extract_city(advert: dict) -> str | None:
    location = advert.get("location") or {}
    city = location.get("city") or {}
    name = city.get("name")
    return str(name) if name else None


def _map_advert(advert: dict, company: str, model: str) -> BikeOffer:
    return BikeOffer(
        brand=company,
        model=model,
        price=_extract_price(advert),
        is_new=False,
        url=str(advert.get("url", "")),
        photos=_extract_photos(advert),
        source="olx.pl",
        city=_extract_city(advert),
    )


async def find_used_bikes_api(company: str, model: str) -> UsedBikeResponse:
    if _credentials() is None:
        logger.info("OLX credentials not configured — skipping API lookup")
        return UsedBikeResponse(
            offers=[],
            info="OLX API credentials not configured (OLX_CLIENT_ID / OLX_CLIENT_SECRET).",
        )

    category_id = os.getenv("OLX_BIKES_CATEGORY_ID") or _DEFAULT_BIKES_CATEGORY_ID
    phrase = f"{company} {model}".strip()

    t = time.perf_counter()
    async with httpx.AsyncClient(timeout=30) as client:
        token = await _get_token(client)
        if token is None:
            return UsedBikeResponse(offers=[], info="OLX authentication failed.")

        try:
            resp = await client.get(
                f"{_base_url()}/api/partner/adverts",
                params={
                    "query": phrase,
                    "category_id": category_id,
                    "region": _REGION_PL,
                    "limit": _MAX_OFFERS,
                    "offset": 0,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Version": "2.0",
                },
            )
        except httpx.HTTPError as exc:
            logger.error("OLX adverts request failed | %s", exc)
            return UsedBikeResponse(offers=[], info="OLX listing request failed.")

    elapsed = time.perf_counter() - t

    if resp.status_code != 200:
        logger.error("OLX adverts non-200 | status=%d body=%r", resp.status_code, resp.text[:300])
        return UsedBikeResponse(
            offers=[],
            info=f"OLX listing request returned HTTP {resp.status_code}.",
        )

    payload = resp.json()
    adverts = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(adverts, list):
        logger.error("OLX adverts unexpected payload | body=%r", str(payload)[:300])
        return UsedBikeResponse(offers=[], info="OLX returned an unexpected response shape.")

    offers: list[BikeOffer] = []
    for advert in adverts[:_MAX_OFFERS]:
        if not isinstance(advert, dict):
            continue
        try:
            offers.append(_map_advert(advert, company, model))
        except Exception as exc:  # noqa: BLE001 — never let one bad advert 502
            logger.warning("skipping malformed advert: %s", exc)

    logger.info(
        "OLX API search done | phrase=%r offers=%d elapsed=%.2fs",
        phrase, len(offers), elapsed,
    )
    return UsedBikeResponse(offers=offers, info="")
