import logging
import time
from pathlib import Path
from urllib.parse import urlparse

from anthropic import AsyncAnthropic

from .schemas import BikeOffer, BikeOfferResponse
from .json_extract import extract_json

logger = logging.getLogger("biker.offers")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"

# Curated allowlist from backend/docs/offer_sources.md (TODO-006).
ALLOWLIST = {
    "allegro.pl",
    "olx.pl",
    "ceneo.pl",
    "decathlon.pl",
    "bike-discount.de",
    "centrumrowerowe.pl",
    "sprzedajemy.pl",
    "bikesalon.pl",
    "rosebikes.pl",
    "canyon.com",
    "trekbikes.com",
    "specialized.com",
}

MAX_OFFERS = 6


def _domain_for(url: str) -> str | None:
    """Return the allowlist domain matching the URL's host, or None if not allowed."""
    host = (urlparse(url).hostname or "").lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    for domain in ALLOWLIST:
        if host == domain or host.endswith("." + domain):
            return domain
    return None


async def find_generic_offers(company: str, model: str) -> BikeOfferResponse:
    system_prompt = (PROMPTS_DIR / "bike_offers_generic.md").read_text(encoding="utf-8")
    user_message = f"Find current offers across the allowlist for: {company} {model}"

    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=3000,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[
            {"role": "user", "content": user_message},
        ],
    )
    elapsed = time.perf_counter() - t

    logger.info(
        "generic offers search done | elapsed=%.2fs input_tokens=%d output_tokens=%d stop_reason=%s",
        elapsed,
        response.usage.input_tokens,
        response.usage.output_tokens,
        response.stop_reason,
    )

    if response.stop_reason != "end_turn":
        logger.error("unexpected stop_reason=%r — response may be incomplete", response.stop_reason)
        return BikeOfferResponse(offers=[], info="")

    texts = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    if not texts:
        logger.error("no text block in response")
        return BikeOfferResponse(offers=[], info="")

    full_text = "".join(texts)
    logger.info("raw anthropic output | text=%r", full_text)

    data = extract_json(full_text)
    if data is None:
        logger.error("JSON decode failed | raw=%r", full_text[:300])
        return BikeOfferResponse(offers=[], info=full_text.strip())

    info_text = ""
    if isinstance(data, dict):
        info_text = str(data.get("info", ""))
        data = data.get("offers", [])

    if not isinstance(data, list):
        logger.error("unexpected JSON type %s", type(data).__name__)
        return BikeOfferResponse(offers=[], info=full_text.strip())

    offers = []
    for item in data:
        if len(offers) >= MAX_OFFERS:
            break
        try:
            url = str(item.get("url", ""))
            domain = _domain_for(url)
            if domain is None:
                logger.warning("dropping off-allowlist offer | url=%r", url)
                continue
            offers.append(BikeOffer(
                brand=str(item.get("brand", "")),
                model=str(item.get("model", "")),
                price=str(item.get("price", "")),
                is_new=bool(item.get("is_new", False)),
                url=url,
                photos=[str(p) for p in item.get("photos", []) if p],
                source=domain,
            ))
        except Exception as exc:
            logger.warning("skipping malformed offer: %s | item=%r", exc, item)

    if not offers:
        logger.warning("no allowlist offers returned")

    return BikeOfferResponse(offers=offers, info=info_text)
