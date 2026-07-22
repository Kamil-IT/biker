"""Amazon offer finder — Product Advertising API (PA-API) 5.0.

Auth method: **PA-API 5.0** with AWS Signature Version 4 request signing.
Chosen over SP-API because PA-API exposes a first-class product search
(`SearchItems`) usable for buyer-facing offers, whereas SP-API is seller-centric
and would require LWA OAuth plus a registered selling account.

PA-API requires an active Amazon Associate account with qualifying sales, so
credentials are frequently unavailable in dev. This module degrades gracefully:
missing credentials or any API/network error yields `{offers: [], info: ...}` —
never a 502.

Credentials (env):
- AMAZON_ACCESS_KEY / AMAZON_SECRET_KEY — PA-API access key pair
- AMAZON_PARTNER_TAG — Associate tag (partner tag)
- AMAZON_REGION / AMAZON_HOST — marketplace endpoint (default us-east-1 / webservices.amazon.com)
"""
import datetime
import hashlib
import hmac
import json
import logging
import os

import httpx

from .schemas import BikeOffer, BikeOfferResponse

logger = logging.getLogger("biker.amazon")

_SERVICE = "ProductAdvertisingAPI"
_PATH = "/paapi5/searchitems"
_TARGET = "com.amazon.paapi5.v1.ProductAdvertisingAPIv1.SearchItems"


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, date_stamp: str, region: str) -> bytes:
    k_date = _sign(("AWS4" + secret).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, _SERVICE)
    return _sign(k_service, "aws4_request")


def _map_offer(item: dict, brand: str, model: str) -> BikeOffer | None:
    try:
        url = str(item.get("DetailPageURL", ""))
        if not url:
            return None

        item_info = item.get("ItemInfo", {}) or {}
        title = (item_info.get("Title", {}) or {}).get("DisplayValue", "")

        by_line = item_info.get("ByLineInfo", {}) or {}
        item_brand = (by_line.get("Brand", {}) or {}).get("DisplayValue", "") \
            or (by_line.get("Manufacturer", {}) or {}).get("DisplayValue", "")

        price = ""
        is_new = True
        listings = (item.get("Offers", {}) or {}).get("Listings", []) or []
        if listings:
            listing = listings[0]
            price = str((listing.get("Price", {}) or {}).get("DisplayAmount", ""))
            condition = ((listing.get("Condition", {}) or {}).get("Value", "") or "").lower()
            if condition and condition != "new":
                is_new = False

        photos = []
        images = item.get("Images", {}) or {}
        primary = (images.get("Primary", {}) or {}).get("Large", {}) or {}
        if primary.get("URL"):
            photos.append(str(primary["URL"]))

        return BikeOffer(
            brand=str(item_brand or brand),
            model=str(title or model),
            price=price,
            is_new=is_new,
            url=url,
            photos=photos,
            source="amazon",
        )
    except Exception as exc:
        logger.warning("skipping malformed amazon item: %s | item=%r", exc, item)
        return None


async def find_amazon_offers(company: str, model: str) -> BikeOfferResponse:
    access_key = os.getenv("AMAZON_ACCESS_KEY", "").strip()
    secret_key = os.getenv("AMAZON_SECRET_KEY", "").strip()
    partner_tag = os.getenv("AMAZON_PARTNER_TAG", "").strip()
    region = os.getenv("AMAZON_REGION", "us-east-1").strip()
    host = os.getenv("AMAZON_HOST", "webservices.amazon.com").strip()

    if not (access_key and secret_key and partner_tag):
        logger.warning("Amazon PA-API credentials missing — returning empty offers")
        return BikeOfferResponse(
            offers=[],
            info="Amazon PA-API credentials not configured. Set AMAZON_ACCESS_KEY, "
                 "AMAZON_SECRET_KEY, and AMAZON_PARTNER_TAG (requires a verified "
                 "Associate account with qualifying sales).",
        )

    keywords = f"{company} {model} bike".strip()
    payload = {
        "Keywords": keywords,
        "SearchIndex": "SportingGoods",
        "ItemCount": 3,
        "PartnerTag": partner_tag,
        "PartnerType": "Associates",
        "Marketplace": f"www.{host.replace('webservices.', '')}",
        "Resources": [
            "ItemInfo.Title",
            "ItemInfo.ByLineInfo",
            "Offers.Listings.Price",
            "Offers.Listings.Condition",
            "Images.Primary.Large",
        ],
    }
    body = json.dumps(payload)

    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")

    canonical_headers = (
        f"content-encoding:amz-1.0\n"
        f"host:{host}\n"
        f"x-amz-date:{amz_date}\n"
        f"x-amz-target:{_TARGET}\n"
    )
    signed_headers = "content-encoding;host;x-amz-date;x-amz-target"
    payload_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()
    canonical_request = (
        f"POST\n{_PATH}\n\n{canonical_headers}\n{signed_headers}\n{payload_hash}"
    )

    credential_scope = f"{date_stamp}/{region}/{_SERVICE}/aws4_request"
    string_to_sign = (
        f"AWS4-HMAC-SHA256\n{amz_date}\n{credential_scope}\n"
        f"{hashlib.sha256(canonical_request.encode('utf-8')).hexdigest()}"
    )

    signature = hmac.new(
        _signing_key(secret_key, date_stamp, region),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    authorization = (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    headers = {
        "content-encoding": "amz-1.0",
        "content-type": "application/json; charset=utf-8",
        "host": host,
        "x-amz-date": amz_date,
        "x-amz-target": _TARGET,
        "Authorization": authorization,
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"https://{host}{_PATH}", content=body, headers=headers)
    except Exception as exc:
        logger.error("Amazon PA-API request failed: %s", exc)
        return BikeOfferResponse(offers=[], info=f"Amazon request failed: {exc}")

    if resp.status_code != 200:
        logger.error("Amazon PA-API HTTP %d | body=%r", resp.status_code, resp.text[:300])
        return BikeOfferResponse(
            offers=[],
            info=f"Amazon PA-API returned HTTP {resp.status_code}.",
        )

    try:
        data = resp.json()
    except Exception as exc:
        logger.error("Amazon PA-API JSON decode failed: %s", exc)
        return BikeOfferResponse(offers=[], info="Amazon response was not valid JSON.")

    items = (data.get("SearchResult", {}) or {}).get("Items", []) or []
    offers = []
    for item in items[:3]:
        mapped = _map_offer(item, company, model)
        if mapped is not None:
            offers.append(mapped)

    if not offers:
        logger.warning("no amazon offers returned for %r", keywords)

    return BikeOfferResponse(offers=offers, info="")
