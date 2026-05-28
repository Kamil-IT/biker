import logging
import time
from pathlib import Path

from anthropic import AsyncAnthropic

from .schemas import BikeOffer, BikeOfferResponse
from .json_extract import extract_json

logger = logging.getLogger("biker.decathlon")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"


async def find_decathlon_offers(company: str, model: str) -> BikeOfferResponse:
    system_prompt = (PROMPTS_DIR / "bike_offer_decathlon.md").read_text(encoding="utf-8")
    user_message = f"Find current offers on decathlon.pl for: {company} {model}"

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
        "decathlon search done | elapsed=%.2fs input_tokens=%d output_tokens=%d stop_reason=%s",
        elapsed,
        input_tokens,
        output_tokens,
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
    for item in data[:3]:
        try:
            offers.append(BikeOffer(
                brand=str(item.get("brand", "")),
                model=str(item.get("model", "")),
                price=str(item.get("price", "")),
                is_new=bool(item.get("is_new", True)),
                url=str(item.get("url", "")),
                photos=[str(p) for p in item.get("photos", []) if p],
                source=str(item.get("source", "")),
            ))
        except Exception as exc:
            logger.warning("skipping malformed offer: %s | item=%r", exc, item)

    if len(offers) < 1:
        logger.warning("no decathlon offers returned")

    return BikeOfferResponse(offers=offers, info=info_text)
