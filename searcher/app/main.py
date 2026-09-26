"""Biker Searcher — FastAPI entry point (TODO-031, TODO-032).

Three routes: POST /v1/search/olx (X-Searcher-Key required) runs the OLX
search through the Claude Code CLI, scrapes listing photos with Playwright and
writes the result into bike_offer / bike_offer_photos; POST /v1/search/decathlon
(same key) runs the Decathlon search through the CLI — no Playwright — and
writes bike_offer rows with source 'decathlon.pl'; GET /health is open. Both
searches share ONE busy slot: one CLI run per instance whatever the source.
"""
import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import text

from . import config
from .claude_cli import cli_version
from .decathlon_finder import DECATHLON_SOURCE, find_decathlon_offers
from .models import dispose_engine, get_engine, init_db
from .olx_finder import OLX_SOURCE, SearcherError, find_used_bikes
from .repository import save_offers
from .schemas import BikeOffer, HealthResponse, SearchRequest, SearchResponse

Finder = Callable[[str, str], Awaitable[tuple[list[BikeOffer], str]]]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("searcher.main")

# One CLI process + one browser per slot; later requests wait their turn.
_semaphore: asyncio.Semaphore | None = None
_cli_version: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _semaphore, _cli_version
    init_db()  # raises RuntimeError when DATABASE_URL is unset — no SQLite fallback
    logger.info("database | url=%s", config.safe_database_url())
    _cli_version = await asyncio.to_thread(cli_version)
    if _cli_version:
        logger.info("claude CLI | binary=%s version=%s model=%s", config.claude_binary(), _cli_version, config.CLAUDE_MODEL)
    else:
        logger.error("claude CLI NOT FOUND — every search will fail (set CLAUDE_BIN or put `claude` on PATH)")
    if not config.SEARCHER_API_KEY:
        logger.error("SEARCHER_API_KEY is not set — every /v1/search/* request will be refused (401)")
    logger.info(
        "searcher ready | max_concurrent=%d cli_timeout=%.0fs headless=%s",
        config.MAX_CONCURRENT, config.CLI_TIMEOUT, config.playwright_headless(),
    )
    _semaphore = asyncio.Semaphore(config.MAX_CONCURRENT)
    yield
    dispose_engine()


app = FastAPI(title="Biker Searcher", version="1.0.0", lifespan=lifespan)


def require_api_key(x_searcher_key: str | None = Header(default=None, alias="X-Searcher-Key")) -> None:
    """Shared-secret auth. Fails closed: no configured key means nobody gets in."""
    if not config.SEARCHER_API_KEY:
        raise HTTPException(status_code=401, detail="searcher API key is not configured")
    given = (x_searcher_key or "").encode("utf-8")
    if not given or not secrets.compare_digest(given, config.SEARCHER_API_KEY.encode("utf-8")):
        raise HTTPException(status_code=401, detail="invalid or missing X-Searcher-Key")


def _database_ok() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 — health must answer, whatever broke
        logger.warning("health: database check failed | %s", exc)
        return False


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Open liveness check: CLI version (probed again if it was missing at startup) + DB ping."""
    global _cli_version
    if _cli_version is None:
        _cli_version = await asyncio.to_thread(cli_version)
    database = await asyncio.to_thread(_database_ok)
    return HealthResponse(status="ok", claude_cli=_cli_version, database=database)


async def _run_search(label: str, source: str, finder: Finder, req: SearchRequest) -> SearchResponse:
    """The body both search routes share: busy check, one finder run under the
    semaphore, one DB write, the stored rows back.

    `label` prefixes the log lines ("olx" / "decathlon"), `source` is the
    bike_offer.source the rows are stored under, `finder(company, model)`
    returns (offers, info) or raises SearcherError. 502 with a short
    sanitised detail when the CLI fails (exit code, timeout, no structured
    output); a run that finds nothing is a 200 with offers: []. 500 when the
    DB write fails. 503 "searcher busy" straight away when
    SEARCHER_MAX_CONCURRENT searches are already running — queueing behind a
    multi-minute search would outlive the caller's timeout and end in a
    second paid run for the same bike. The offers returned are exactly the
    rows now stored under this bike for this source (see repository.save_offers).
    """
    logger.info("%s search request | company=%r model=%r", label, req.company, req.model)
    assert _semaphore is not None  # set in lifespan
    if _semaphore.locked():
        logger.warning("%s search refused: busy | company=%r model=%r", label, req.company, req.model)
        raise HTTPException(status_code=503, detail="searcher busy")
    t_start = time.perf_counter()
    async with _semaphore:
        try:
            offers, info = await finder(req.company, req.model)
        except SearcherError as exc:
            logger.error("%s search failed | company=%r model=%r | %s", label, req.company, req.model, exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        try:
            bike_id, saved = await asyncio.to_thread(save_offers, req.company, req.model, offers, source)
        except Exception as exc:  # noqa: BLE001 — logged in the repository; callers get a summary only
            raise HTTPException(status_code=500, detail="database write failed") from exc
    elapsed = time.perf_counter() - t_start
    logger.info(
        "%s search complete | company=%r model=%r found=%d saved=%d bike_id=%d elapsed=%.2fs",
        label, req.company, req.model, len(offers), len(saved), bike_id, elapsed,
    )
    return SearchResponse(offers=saved, info=info, bike_id=bike_id, saved=len(saved))


@app.post("/v1/search/olx", response_model=SearchResponse, dependencies=[Depends(require_api_key)])
async def search_olx(req: SearchRequest) -> SearchResponse:
    """Search OLX for the bike (CLI + Playwright photos), store the listings, return them.

    Status mapping and busy slot: see _run_search. Rows are stored with
    source 'olx.pl', is_new false.
    """
    return await _run_search("olx", OLX_SOURCE, find_used_bikes, req)


@app.post("/v1/search/decathlon", response_model=SearchResponse, dependencies=[Depends(require_api_key)])
async def search_decathlon(req: SearchRequest) -> SearchResponse:
    """Search decathlon.pl for the bike (CLI only, no Playwright), store the offers, return them.

    Same status mapping as /v1/search/olx and the SAME semaphore: one CLI run
    per instance whatever the source, so a Decathlon search answers 503
    "searcher busy" while an OLX search is running and vice versa. Rows are
    stored with source 'decathlon.pl', is_new as the shop page says, no photos.
    """
    return await _run_search("decathlon", DECATHLON_SOURCE, find_decathlon_offers, req)
