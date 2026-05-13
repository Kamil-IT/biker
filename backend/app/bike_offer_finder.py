import json
import logging
import time
from pathlib import Path

from anthropic import AsyncAnthropic

from .schemas import BikeOffer, BikeOfferResponse
from .allegro_image_fetcher import fetch_images_for_offers

logger = logging.getLogger("biker.offer")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"

_FALLBACK = BikeOfferResponse(offers=[], info="")


def _extract_fenced_json(text: str) -> str:
    start_marker = "```json"
    start = text.find(start_marker)
    if start != -1:
        after = text[start + len(start_marker):]
        end = after.find("```")
        return (after[:end] if end != -1 else after).strip()
    return text.strip()


async def find_bike_offers(company: str, model: str) -> BikeOfferResponse:
    system_prompt = (PROMPTS_DIR / "bike_offer_allegro.md").read_text(encoding="utf-8")
    user_message = f"Find current offers on allegro for: {company} {model}"

    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[
            {"role": "user", "content": user_message},
        ],
    )
    elapsed = time.perf_counter() - t

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    logger.info(
        "offer search done | elapsed=%.2fs input_tokens=%d output_tokens=%d stop_reason=%s",
        elapsed,
        input_tokens,
        output_tokens,
        response.stop_reason,
    )

    if response.stop_reason != "end_turn":
        logger.error("unexpected stop_reason=%r — response may be incomplete", response.stop_reason)
        return _FALLBACK

    texts = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    if not texts:
        logger.error("no text block in response")
        return _FALLBACK

    full_text = "".join(texts)
    logger.info("raw anthropic output | text=%r", full_text)

    raw = _extract_fenced_json(full_text)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("JSON decode failed: %s | raw=%r", exc, raw[:300])
        return BikeOfferResponse(offers=[], info=full_text.strip())

    info_text = ""
    if isinstance(data, dict):
        info_text = str(data.get("info", ""))
        data = data.get("offers", [])

    if not isinstance(data, list):
        logger.error("unexpected JSON type %s", type(data).__name__)
        return BikeOfferResponse(offers=[], info=full_text.strip())

    offers = []
    for item in data[:3]:
        try:
            offers.append(BikeOffer(
                brand=str(item.get("brand", "")),
                model=str(item.get("model", "")),
                price=str(item.get("price", "")),
                is_new=bool(item.get("is_new", False)),
                url=str(item.get("url", "")),
                photos=[str(p) for p in item.get("photos", []) if p],
                source=str(item.get("source", "")),
            ))
        except Exception as exc:
            logger.warning("skipping malformed offer: %s | item=%r", exc, item)

    if len(offers) < 1:
        logger.warning("no offers returned")

    offers = await fetch_images_for_offers(offers)
    return BikeOfferResponse(offers=offers, info=info_text)
