"""Resolve a brand+model to its Shopify product, authoritatively.

Round 4 established that `<site>/products.json?limit=250` is the reliable way to
find a product, and that `product_type` is what separates a complete bike from a
frameset, a spare part, an outlet listing or an accessory bundle. Matching on the
title alone pulled "Bombtrack Arise Bearing Set" for `Arise` and
"Explorer Peak Recommended Accessories" for `Explorer Peak`.
"""
import logging
import re

import httpx

from pipeline.photo_extract import _UA

logger = logging.getLogger("pipeline.shopify_index")

SITES = {
    "Airdrop Bikes": "https://airdropbikes.com",
    "Ari Bikes": "https://aribikes.com",
    "Aventon": "https://www.aventon.com",
    "Bombtrack": "https://bombtrack.com",
    "Brooklyn Bicycle Co.": "https://brooklynbicycleco.com",
    "Chromag Bikes": "https://chromagbikes.com",
    "Crust Bikes": "https://crustbikes.com",
}

# product_type values that are NOT a complete bike.
# Every alternative is \b-anchored on BOTH sides: an unanchored `rack\b` matched
# "Bombt-rack" and rejected the entire Bombtrack catalogue.
NOT_COMPLETE = re.compile(
    r"\b(?:frameset|frames|frame|spare|bearing|seat\s*clamp|outlet|accessor\w*|"
    r"parts?|apparel|tools?|components?|wheels?|wheelset|tyres?|tires?|bags?|"
    r"racks?|clothing|suspension)\b",
    re.I,
)
COMPLETE_HINT = re.compile(r"bike|complete|bicycle", re.I)

_cache: dict[str, list[dict]] = {}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def index(site: str) -> list[dict]:
    """All products for a storefront, paginated. Cached per process."""
    if site in _cache:
        return _cache[site]
    products: list[dict] = []
    try:
        with httpx.Client(timeout=30, follow_redirects=True, headers=_UA) as c:
            for page in range(1, 6):
                r = c.get(f"{site}/products.json?limit=250&page={page}")
                if r.status_code != 200:
                    break
                batch = r.json().get("products") or []
                if not batch:
                    break
                products.extend(batch)
    except Exception as exc:
        logger.warning("index fetch failed | %s | %s", site, exc)
    _cache[site] = products
    logger.info("index | %s | %d products", site, len(products))
    return products


def find_product(brand: str, model: str, site: str | None = None) -> dict | None:
    """The complete-bike product for this brand+model, or None.

    Exact title match only (optionally brand-prefixed or year-suffixed).
    Anything whose `product_type` says frameset/part/outlet/accessory is
    rejected outright, however well the title matches.
    """
    site = site or SITES.get(brand)
    if not site:
        return None

    target = norm(model)
    brand_words = norm(brand).split()
    accepted = {target}
    for w in brand_words + ["fezzari", "bombtrack", "chromag", "brooklyn"]:
        accepted.add(f"{w} {target}")

    fallback = None
    for p in index(site):
        title = p.get("title", "")
        ptype = p.get("product_type", "") or ""
        t = norm(title)
        t_noyear = re.sub(r"\s+", " ", re.sub(r"\b(19|20)\d{2}\b", "", t)).strip()
        if t not in accepted and t_noyear not in accepted:
            continue
        # product_type is authoritative when it is decisive; only fall back to
        # reading the title when the type says nothing useful.
        if COMPLETE_HINT.search(ptype) and not NOT_COMPLETE.search(ptype):
            return p
        if NOT_COMPLETE.search(ptype) or NOT_COMPLETE.search(title):
            continue
        fallback = fallback or p
    return fallback
