"""Decathlon new-bike offer search — the backend's old bike_offer_decathlon_finder, moved here (TODO-032).

Same prompt (prompts/bike_offer_decathlon.md), same user message and the same
≤ 3 offers; only the transport changed: the Claude Code CLI with a JSON
schema instead of the Anthropic SDK plus prose parsing. No Playwright — the
old endpoint never scraped Decathlon photos either, so `photos` stay [].
"""
import asyncio
import logging
import time

from . import config
from .claude_cli import ClaudeCliError, run_structured
from .olx_finder import OLX_SCHEMA, PRICE_MAX_LEN, TEXT_MAX_LEN, URL_MAX_LEN, SearcherError
from .schemas import BikeOffer

logger = logging.getLogger("searcher.decathlon")

PROMPT_FILE = config.PROMPTS_DIR / "bike_offer_decathlon.md"
DECATHLON_SOURCE = "decathlon.pl"
DECATHLON_URL_PREFIX = "https://www.decathlon.pl/"
MAX_OFFERS = 3  # the old finder's data[:3]

# The CLI validates the answer against the OLX schema: it is the same
# {info, offers[]} shape and the prompt's "Output format" block matches it
# field-for-field (`city` is optional there and is never stored for a shop).
OFFERS_SCHEMA = OLX_SCHEMA


def _to_offers(items: list) -> list[BikeOffer]:
    """Coerce the model's offers into BikeOffer rows the DB read path will find.

    source is always 'decathlon.pl' — the backend selects bike_offer rows by
    that exact string — and is_new is the model's flag, default True (Decathlon
    sells new bikes; the prompt only clears it for an outlet / refurbished
    page). An offer without a real decathlon.pl URL cannot be linked or stored
    (url is UNIQUE, NOT NULL) and is dropped, as is a repeated URL or one
    longer than the column. Text fields are cut to their column widths so
    PostgreSQL cannot reject the write after the CLI run was already paid
    for. `photos` are always empty (nothing scrapes Decathlon) and `city` is
    None (a shop page, not a listing).
    """
    offers: list[BikeOffer] = []
    seen: set[str] = set()
    for item in items[:MAX_OFFERS]:
        try:
            url = str(item.get("url", "")).strip()
            if not url.startswith(DECATHLON_URL_PREFIX) or len(url) > URL_MAX_LEN:
                logger.warning("skipping offer without a usable decathlon.pl url | url=%r", url[:120])
                continue
            if url in seen:
                logger.warning("skipping duplicate offer url | url=%r", url)
                continue
            seen.add(url)
            offers.append(BikeOffer(
                brand=str(item.get("brand", ""))[:TEXT_MAX_LEN],
                model=str(item.get("model", ""))[:TEXT_MAX_LEN],
                price=str(item.get("price", ""))[:PRICE_MAX_LEN],
                is_new=bool(item.get("is_new", True)),
                url=url,
                photos=[],
                source=DECATHLON_SOURCE,
                city=None,
            ))
        except Exception as exc:  # noqa: BLE001 — one bad offer must not sink the rest
            logger.warning("skipping malformed offer: %s | item=%r", exc, item)
    return offers


async def find_decathlon_offers(company: str, model: str) -> tuple[list[BikeOffer], str]:
    """One CLI search on decathlon.pl for the bike — no photo scrape.

    Returns (offers, info). Raises SearcherError when the CLI run fails —
    a search that simply finds nothing is ([], info), not an error.
    """
    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    user_message = f"Find current offers on decathlon.pl for: {company} {model}"

    t = time.perf_counter()
    try:
        # Blocking subprocess → worker thread, so /health keeps answering meanwhile.
        data = await asyncio.to_thread(run_structured, system_prompt, user_message, OFFERS_SCHEMA)
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
        "decathlon search done | company=%r model=%r listed=%d kept=%d elapsed=%.2fs info=%r",
        company, model, len(items), len(offers), elapsed, info_text,
    )
    if not offers:
        logger.warning("no decathlon offers returned | company=%r model=%r", company, model)
    return offers, info_text
