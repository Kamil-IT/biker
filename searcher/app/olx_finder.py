"""OLX used-bike search — the backend's old bike_used_finder, moved here (TODO-031).

Same prompt (prompts/bike_offer_olx.md), same user message, same ≤ 5 listings
and the same Playwright photo scrape; only the transport changed: the Claude
Code CLI with a JSON schema instead of the Anthropic SDK plus prose parsing.
"""
import asyncio
import logging
import time

from . import config
from .claude_cli import ClaudeCliError, run_structured
from .olx_image_fetcher import fetch_images_for_offers
from .schemas import BikeOffer

logger = logging.getLogger("searcher.olx")

PROMPT_FILE = config.PROMPTS_DIR / "bike_offer_olx.md"
OLX_SOURCE = "olx.pl"
OLX_URL_PREFIX = "https://www.olx.pl/"
MAX_OFFERS = 5
# Column widths of bike_offer (models.py): price String(100), city/brand/model String(255), url String(2048).
PRICE_MAX_LEN, TEXT_MAX_LEN, URL_MAX_LEN = 100, 255, 2048

# What the CLI validates the model's answer against (--json-schema). Mirrors the
# "Output format" block of the prompt; `city` may be null when OLX shows none.
OLX_SCHEMA = {
    "type": "object",
    "properties": {
        "info": {"type": "string"},
        "offers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "brand": {"type": "string"},
                    "model": {"type": "string"},
                    "price": {"type": "string"},
                    "is_new": {"type": "boolean"},
                    "url": {"type": "string"},
                    "photos": {"type": "array", "items": {"type": "string"}},
                    "source": {"type": "string"},
                    "city": {"type": ["string", "null"]},
                },
                "required": ["brand", "model", "price", "is_new", "url", "photos", "source"],
            },
        },
    },
    "required": ["info", "offers"],
}


class SearcherError(Exception):
    """The search could not produce a result; str(exc) is safe to send to callers."""


def _to_offers(items: list) -> list[BikeOffer]:
    """Coerce the model's listings into BikeOffer rows the DB read path will find.

    is_new is always False and source always 'olx.pl' — the backend selects
    bike_offer rows by that exact source string. A listing without a real
    olx.pl URL cannot be linked or stored (url is UNIQUE, NOT NULL) and is
    dropped, as is a repeated URL or one longer than the column. Text fields
    are cut to their column widths so PostgreSQL cannot reject the write
    after the CLI run was already paid for. `photos` start empty: the
    Playwright scrape is the only trusted source of image URLs.
    """
    offers: list[BikeOffer] = []
    seen: set[str] = set()
    for item in items[:MAX_OFFERS]:
        try:
            url = str(item.get("url", "")).strip()
            if not url.startswith(OLX_URL_PREFIX) or len(url) > URL_MAX_LEN:
                logger.warning("skipping offer without a usable olx.pl url | url=%r", url[:120])
                continue
            if url in seen:
                logger.warning("skipping duplicate offer url | url=%r", url)
                continue
            seen.add(url)
            city = item.get("city")
            offers.append(BikeOffer(
                brand=str(item.get("brand", ""))[:TEXT_MAX_LEN],
                model=str(item.get("model", ""))[:TEXT_MAX_LEN],
                price=str(item.get("price", ""))[:PRICE_MAX_LEN],
                is_new=False,
                url=url,
                photos=[],
                source=OLX_SOURCE,
                city=str(city)[:TEXT_MAX_LEN] if city else None,
            ))
        except Exception as exc:  # noqa: BLE001 — one bad listing must not sink the rest
            logger.warning("skipping malformed offer: %s | item=%r", exc, item)
    return offers


async def find_used_bikes(company: str, model: str) -> tuple[list[BikeOffer], str]:
    """One CLI search on OLX for the bike, then photos for each listing.

    Returns (offers, info). Raises SearcherError when the CLI run fails —
    a search that simply finds nothing is ([], info), not an error.
    """
    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    user_message = f"Find current used bike offers on OLX for: {company} {model}"

    t = time.perf_counter()
    try:
        # Blocking subprocess → worker thread, so /health keeps answering meanwhile.
        data = await asyncio.to_thread(run_structured, system_prompt, user_message, OLX_SCHEMA)
    except ClaudeCliError as exc:
        raise SearcherError(str(exc)) from exc
    elapsed = time.perf_counter() - t

    info_text = str(data.get("info", ""))
    items = data.get("offers", [])
    if not isinstance(items, list):
        logger.error("unexpected offers type %s — treating as none", type(items).__name__)
        items = []
    offers = _to_offers(items)
    logger.info(
        "used bike search done | company=%r model=%r listed=%d kept=%d elapsed=%.2fs info=%r",
        company, model, len(items), len(offers), elapsed, info_text,
    )
    if not offers:
        logger.warning("no used bike offers returned | company=%r model=%r", company, model)

    offers = await fetch_images_for_offers(offers)
    return offers, info_text
