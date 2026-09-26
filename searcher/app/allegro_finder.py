"""Allegro offer search — the backend's old bike_offer_finder, moved here (TODO-033).

Same user message, the same ≤ 3 offers and the same Playwright photo scrape
(allegro_image_fetcher, moved with it), but NOT the same prompt: allegro.pl
answers HTTP 403 (DataDome) to every automated fetch — the CLI's WebFetch and
Chromium alike — so the SDK-era prompt ("open the listing, open the offer")
either burned the whole 300 s CLI timeout or gave up with no offers (probes
2026-09-26). prompts/bike_offer_allegro.md is a CLI-tuned rewrite of the same
role/rules/output that works from WebSearch results only: listing URLs, price
and condition come from the result title/snippet (a price the snippet does
not show stays ""). Probes with it: Kross Level 3.0 → 3 offers in 67 s,
Trek Marlin 4 → 3 offers in 75 s. The result is stored under source
'allegro.pl' — the backend's /v1/bike/allegro is now a pure DB read.
"""
import asyncio
import logging
import re
import time

from . import config
from .allegro_image_fetcher import fetch_images_for_offers
from .claude_cli import ClaudeCliError, run_structured
from .olx_finder import OLX_SCHEMA, PRICE_MAX_LEN, TEXT_MAX_LEN, URL_MAX_LEN, SearcherError
from .schemas import BikeOffer

logger = logging.getLogger("searcher.allegro")

PROMPT_FILE = config.PROMPTS_DIR / "bike_offer_allegro.md"
ALLEGRO_SOURCE = "allegro.pl"
# Only a single listing (/oferta/…) or a product page pointing at one offer
# (/produkt/…) is an offer. A /listing?string=… search page or a category page
# would be stored as an "offer" and its recommendation tiles scraped as photos.
ALLEGRO_OFFER_URL_RE = re.compile(r"^https://(www\.)?allegro\.pl/(oferta|produkt)/")
MAX_OFFERS = 3  # the old finder's data[:3] (the prompt asks for 1–3)

# The CLI validates the answer against the OLX schema: it is the same
# {info, offers[]} shape and the prompt's "Output format" block matches it
# field-for-field (`city` is optional there and never given for Allegro).
OFFERS_SCHEMA = OLX_SCHEMA


def _to_offers(items: list) -> list[BikeOffer]:
    """Coerce the model's offers into BikeOffer rows the DB read path will find.

    source is always 'allegro.pl' — the backend selects bike_offer rows by
    that exact string — and is_new is the model's flag (the prompt derives it
    from the result title/snippet: "używany" → False, "nowy"/shop listing →
    True; the flag decides whether the UI shows the offer in the "Nowe" or the
    "Używane" card; the schema requires it, the False default only covers a
    malformed item). An offer whose URL is not an allegro.pl /oferta/ or
    /produkt/ page cannot be linked or stored (url is UNIQUE, NOT NULL) and is
    dropped, as is a repeated URL or one longer than the column. Text fields
    are cut to their column widths so PostgreSQL cannot reject the write after
    the CLI run was already paid for. `price` may be "" when no search snippet
    showed one (the UI then says "cena w ofercie"). `photos` start empty: the
    Playwright scrape is the only trusted source of image URLs. `city` is None
    (a shop listing, the prompt never asks for one).
    """
    offers: list[BikeOffer] = []
    seen: set[str] = set()
    for item in items[:MAX_OFFERS]:
        try:
            url = str(item.get("url", "")).strip()
            if not ALLEGRO_OFFER_URL_RE.match(url) or len(url) > URL_MAX_LEN:
                logger.warning("skipping offer without a usable allegro.pl offer url | url=%r", url[:120])
                continue
            if url in seen:
                logger.warning("skipping duplicate offer url | url=%r", url)
                continue
            seen.add(url)
            offers.append(BikeOffer(
                brand=str(item.get("brand", ""))[:TEXT_MAX_LEN],
                model=str(item.get("model", ""))[:TEXT_MAX_LEN],
                price=str(item.get("price", ""))[:PRICE_MAX_LEN],
                is_new=bool(item.get("is_new", False)),
                url=url,
                photos=[],
                source=ALLEGRO_SOURCE,
                city=None,
            ))
        except Exception as exc:  # noqa: BLE001 — one bad offer must not sink the rest
            logger.warning("skipping malformed offer: %s | item=%r", exc, item)
    return offers


async def find_allegro_offers(company: str, model: str) -> tuple[list[BikeOffer], str]:
    """One CLI search on allegro.pl for the bike, then photos for each offer.

    Returns (offers, info). Raises SearcherError when the CLI run fails —
    a search that simply finds nothing is ([], info), not an error. A photo
    scrape failure (DataDome may block a server IP) is non-fatal: the offers
    come back with `photos: []`.
    """
    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    user_message = f"Find current offers on allegro for: {company} {model}"

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
        "allegro search done | company=%r model=%r listed=%d kept=%d elapsed=%.2fs info=%r",
        company, model, len(items), len(offers), elapsed, info_text,
    )
    if not offers:
        logger.warning("no allegro offers returned | company=%r model=%r", company, model)

    offers = await fetch_images_for_offers(offers)
    return offers, info_text
