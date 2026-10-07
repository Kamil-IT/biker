"""The parts catalogue (TODO-046) — the frontend's "Wyszukiwanie części" tab (/parts).

POST /v1/parts/parse       free text → filters: one Haiku call, generic cache on the
                           happy path only; nothing extracted → 400 (also on a cache hit).
POST /v1/parts/search      the DB search: `equipment` rows of category 'parts', no AI,
                           no generic cache (parts_repository.find_parts).
POST /v1/parts/search/ai   clicked only, never automatic: one Haiku + web_search call,
                           what it finds is stored in `equipment` (the next similar query
                           is a DB hit) and answered, is_new = created by this call. No
                           generic cache — the result is data, like /v1/bike/search.
                           Identical concurrent queries share one call (single-flight).

An Anthropic 400 (e.g. no credits) reaches the app-wide handler in main.py → 400.
Lives apart from main.py (500-line rule).
"""
import asyncio
import logging
import time

import anthropic
from fastapi import APIRouter, HTTPException

from .cache import get_cached, set_cached
from .models import norm
from .parts_finder import find_parts_ai
from .parts_parser import parse_parts_text
from .parts_repository import find_parts, save_found_parts
from .schemas import PartResult, PartsParseRequest, PartsParseResponse, PartsSearchRequest, PartsSearchResponse

logger = logging.getLogger("biker.parts")
router = APIRouter()

PARSE_NO_MATCH_DETAIL = "Part not available in our database"

# AI searches in progress, keyed on the normalised query: a second identical request joins the first.
_inflight: dict[tuple[str, ...], asyncio.Task] = {}


def _reject_empty_parse(result: PartsParseResponse, text: str) -> None:
    """400 when nothing could be extracted — the UI warns instead of searching (like /v1/bike/parse)."""
    if result.is_empty():
        logger.info("parts parse no match | text=%r", text[:80])
        raise HTTPException(status_code=400, detail=PARSE_NO_MATCH_DETAIL)


@router.post("/v1/parts/parse", response_model=PartsParseResponse)
async def parts_parse(req: PartsParseRequest) -> PartsParseResponse:
    logger.info("parts parse request | text=%r", req.text[:80])
    _fields = {"text": req.text}
    cached = get_cached("/v1/parts/parse", _fields, PartsParseResponse)
    if cached is not None:
        _reject_empty_parse(cached, req.text)  # never cached, but a hit must not serve a 200 the fresh path refuses
        return cached
    t_start = time.perf_counter()
    result = await parse_parts_text(req.text)
    logger.info(
        "parts parse complete | elapsed=%.2fs result=%s", time.perf_counter() - t_start,
        result.model_dump(exclude_none=True),
    )
    _reject_empty_parse(result, req.text)
    set_cached("/v1/parts/parse", _fields, result)  # happy path only
    return result


@router.post("/v1/parts/search", response_model=PartsSearchResponse)
async def parts_search(req: PartsSearchRequest) -> PartsSearchResponse:
    """The catalogue search — a pure DB read: no AI, no generic cache. Nothing found → 200 with []."""
    query = req.enriched_query()
    t_start = time.perf_counter()
    try:
        parts = find_parts(req)
    except Exception as exc:  # noqa: BLE001 — [] would offer a paid AI search for a DB outage
        logger.error("parts search failed | query=%r | %s", query, exc)
        raise HTTPException(status_code=503, detail="Parts search failed") from exc
    logger.info("parts search served from DB | query=%r parts=%d elapsed=%.3fs",
                query, len(parts), time.perf_counter() - t_start)
    return PartsSearchResponse(search=query, parts=parts)


def _ai_key(req: PartsSearchRequest) -> tuple[str, ...]:
    return (req.part_type or "", norm(req.brand), norm(req.model), norm(req.groupset), " ".join(norm(req.search).split()))


async def _run_ai_search(req: PartsSearchRequest) -> list[PartResult]:
    found = await find_parts_ai(req)
    if not found:
        return []
    try:
        return await asyncio.to_thread(save_found_parts, found, req.part_type)
    except Exception as exc:  # noqa: BLE001 — logged in the repository
        raise HTTPException(status_code=503, detail="Could not save the found parts — try again later") from exc


@router.post("/v1/parts/search/ai", response_model=PartsSearchResponse)
async def parts_search_ai(req: PartsSearchRequest) -> PartsSearchResponse:
    """Search the web for parts (one Haiku + web_search call), store them in the catalogue, answer them.

    The frontend offers it only under an empty result list, on a click. Bad JSON from
    the model → 200 with []; an API failure → 502; an Anthropic 400 → 400 (handler);
    the DB write failing → 503. Never cached; identical concurrent queries share one call.
    """
    query = req.enriched_query()
    key = _ai_key(req)
    task = _inflight.get(key)
    if task is None:
        logger.info("parts AI search request | query=%r", query)
        task = asyncio.create_task(_run_ai_search(req))
        _inflight[key] = task
        task.add_done_callback(lambda _t: _inflight.pop(key, None))
    else:
        logger.info("parts AI search joined in-flight search | query=%r", query)
    t_start = time.perf_counter()
    try:
        # Shielded: a caller that disconnects does not cancel the paid call for the others.
        parts = await asyncio.shield(task)
    except (HTTPException, anthropic.BadRequestError):
        raise
    except Exception as exc:  # noqa: BLE001 — upstream API failure, not a parse error
        logger.error("parts AI search failed | query=%r | %s", query, exc)
        raise HTTPException(status_code=502, detail=f"Upstream error: {exc}") from exc
    logger.info("parts AI search complete | query=%r parts=%d new=%d elapsed=%.2fs",
                query, len(parts), sum(p.is_new for p in parts), time.perf_counter() - t_start)
    return PartsSearchResponse(search=query, parts=parts)
