"""Biker Searcher — FastAPI entry point (TODO-031, TODO-032, TODO-033, photos).

Five routes: POST /v1/search/olx (X-Searcher-Key required) runs the OLX
search through the Claude Code CLI, scrapes listing photos with Playwright and
writes the result into bike_offer / bike_offer_photos; POST /v1/search/decathlon
(same key) runs the Decathlon search through the CLI — no Playwright — and
writes bike_offer rows with source 'decathlon.pl'; POST /v1/search/allegro
(same key) runs the Allegro search through the CLI — no Playwright either,
allegro.pl answers 403 to browsers — and writes rows with source 'allegro.pl';
POST /v1/search/photos (same key) finds the manufacturer product page through
the CLI, scrapes up to 8 photos with Playwright and stores them in
bike_detail_photos — only for a bike that has none; GET /health is open.
The FOUR searches share one semaphore of SEARCHER_MAX_CONCURRENT slots
(default 10); a slot is one CLI run plus, for OLX and photos, one browser
(browser launches are capped separately by BROWSER_MAX_CONCURRENCY, default 2).
The next request is refused with 503, never queued. On Cloud Run each
instance still serves one request (--concurrency 1); the parallelism there
comes from --max-instances.
"""
import asyncio
import logging
import secrets
import time
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException
from sqlalchemy import text

from . import config
from .allegro_finder import ALLEGRO_SOURCE, find_allegro_offers
from .claude_cli import cli_version
from .decathlon_finder import DECATHLON_SOURCE, find_decathlon_offers
from .models import dispose_engine, get_engine, init_db
from .olx_finder import OLX_SOURCE, SearcherError, find_used_bikes
from .photos_finder import find_bike_photos
from .repository import get_stored_photos, save_offers, save_photos
from .schemas import BikeOffer, HealthResponse, PhotosResponse, SearchRequest, SearchResponse

Finder = Callable[[str, str], Awaitable[tuple[list[BikeOffer], str]]]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("searcher.main")

# SEARCHER_MAX_CONCURRENT slots (default 10) shared by the four search routes:
# one CLI process (+ one browser for OLX / photos) per slot. Locally / in compose
# that is up to ten CLI runs in this one process; on Cloud Run each instance
# serves one request (--concurrency 1) and every further search gets its own
# instance (--max-instances). A request that finds no slot free is refused
# (503), never queued — see _run_search.
_semaphore: asyncio.Semaphore | None = None
_cli_version: str | None = None
# Photo searches in flight, keyed on the normalised bike: an identical request
# joins the running search instead of paying for a second one.
_photo_searches: dict[tuple[str, str], asyncio.Task] = {}


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
    # Every slot holds one worker thread at a time (the CLI subprocess, then the
    # browser, then the DB write); the default pool (cpu + 4) could be smaller than
    # the slot count and would make searches wait on each other for a thread.
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=config.MAX_CONCURRENT + 8, thread_name_prefix="searcher")
    )
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
    """The body all three search routes share: busy check, one finder run under
    the semaphore, one DB write, the stored rows back.

    `label` prefixes the log lines ("olx" / "decathlon" / "allegro"), `source`
    is the bike_offer.source the rows are stored under, `finder(company, model)`
    returns (offers, info) or raises SearcherError. 502 with a short
    sanitised detail when the CLI fails (exit code, timeout, no structured
    output); a run that finds nothing is a 200 with offers: []. 500 when the
    DB write fails. 503 "searcher busy" straight away when
    SEARCHER_MAX_CONCURRENT searches (default 10, counted across the four
    routes) are already running — queueing behind a multi-minute search would
    outlive the caller's timeout and end in a second paid run for the same
    bike. The offers returned are exactly the rows now stored under this bike
    for this source (see repository.save_offers).
    """
    logger.info("%s search request | company=%r model=%r", label, req.company, req.model)
    assert _semaphore is not None  # set in lifespan
    # Semaphore.locked() is true only when every slot is taken, so this busy
    # check is correct for any SEARCHER_MAX_CONCURRENT, not just 1.
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

    Same status mapping as /v1/search/olx and the SAME semaphore: the
    SEARCHER_MAX_CONCURRENT slots (default 10) are counted across the four
    routes whatever the source, so with every slot taken a Decathlon search
    answers 503 "searcher busy". Rows are
    stored with source 'decathlon.pl', is_new as the shop page says, no photos.
    """
    return await _run_search("decathlon", DECATHLON_SOURCE, find_decathlon_offers, req)


@app.post("/v1/search/allegro", response_model=SearchResponse, dependencies=[Depends(require_api_key)])
async def search_allegro(req: SearchRequest) -> SearchResponse:
    """Search allegro.pl for the bike (CLI only, no Playwright), store the offers, return them.

    Same status mapping as /v1/search/olx and the SAME semaphore as the other
    routes (SEARCHER_MAX_CONCURRENT slots, default 10 — the UI fires this
    search together with the Decathlon one). Rows are stored with source
    'allegro.pl', is_new as the listing says (default false: an Allegro
    listing is used unless the result says new), no photos (allegro.pl
    answers 403 to every automated fetch, so nothing scrapes it).
    """
    return await _run_search("allegro", ALLEGRO_SOURCE, find_allegro_offers, req)


async def _photo_search(company: str, model: str) -> PhotosResponse:
    """One photo search in a slot the caller already acquired; releases it when done."""
    assert _semaphore is not None
    t_start = time.perf_counter()
    try:
        # Re-check inside the slot: a search for this bike that finished between the
        # route's read and here (another process / instance) already paid for its photos.
        try:
            bike_id, stored = await asyncio.to_thread(get_stored_photos, company, model)
        except Exception as exc:  # noqa: BLE001 — a read failure must not start a paid run
            logger.error("photos read failed | company=%r model=%r | %s", company, model, exc)
            raise HTTPException(status_code=500, detail="database read failed") from exc
        if stored:
            logger.info("photos stored meanwhile — no search | bike_id=%s count=%d", bike_id, len(stored))
            return PhotosResponse(photos=stored, bike_id=bike_id, saved=0)
        try:
            photos, product_url = await find_bike_photos(company, model)
        except SearcherError as exc:
            logger.error("photos search failed | company=%r model=%r | %s", company, model, exc)
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        try:
            bike_id, stored, saved = await asyncio.to_thread(save_photos, company, model, photos)
        except Exception as exc:  # noqa: BLE001 — logged in the repository; callers get a summary only
            raise HTTPException(status_code=500, detail="database write failed") from exc
    finally:
        _semaphore.release()
    logger.info(
        "photos search complete | company=%r model=%r product_url=%r found=%d saved=%d bike_id=%s elapsed=%.2fs",
        company, model, product_url, len(photos), saved, bike_id, time.perf_counter() - t_start,
    )
    return PhotosResponse(photos=stored, bike_id=bike_id, saved=saved)


@app.post("/v1/search/photos", response_model=PhotosResponse, dependencies=[Depends(require_api_key)])
async def search_photos(req: SearchRequest) -> PhotosResponse:
    """Photos of the bike: the stored ones, or — only when it has none — a new search.

    A bike with photo rows gets them back straight from bike_detail_photos
    (display order), with no CLI run and no busy check. Otherwise: the CLI finds
    the manufacturer product page → Playwright scrapes ≤ 8 photos → stored
    with display_order 0..n-1 under the bike (created if missing). Photos are
    never deleted or replaced; a search that finds nothing writes nothing and
    is a 200 with photos: []. An identical request arriving while that search
    runs joins it (one paid run). Same 401 / 422 / 502 / 503 / 500 mapping as
    the offer routes, and the SAME SEARCHER_MAX_CONCURRENT slots.
    """
    logger.info("photos search request | company=%r model=%r", req.company, req.model)
    try:
        bike_id, stored = await asyncio.to_thread(get_stored_photos, req.company, req.model)
    except Exception as exc:  # noqa: BLE001 — a read failure must not start a paid run
        logger.error("photos read failed | company=%r model=%r | %s", req.company, req.model, exc)
        raise HTTPException(status_code=500, detail="database read failed") from exc
    if stored:
        logger.info("photos already stored — no search | bike_id=%s count=%d", bike_id, len(stored))
        return PhotosResponse(photos=stored, bike_id=bike_id, saved=0)

    key = (req.company.strip().lower(), req.model.strip().lower())
    task = _photo_searches.get(key)
    if task is not None:
        logger.info("photos search joined the one in flight | company=%r model=%r", req.company, req.model)
    else:
        assert _semaphore is not None  # set in lifespan
        if _semaphore.locked():
            logger.warning("photos search refused: busy | company=%r model=%r", req.company, req.model)
            raise HTTPException(status_code=503, detail="searcher busy")
        await _semaphore.acquire()  # a free slot is taken without yielding; _photo_search releases it
        task = asyncio.create_task(_photo_search(req.company, req.model))
        _photo_searches[key] = task

        def _done(t: asyncio.Task) -> None:
            if _photo_searches.get(key) is t:
                del _photo_searches[key]
            if not t.cancelled():
                t.exception()  # mark retrieved: a search whose callers all left must not log "never retrieved"

        task.add_done_callback(_done)
    # shield: a caller that disconnects must not cancel the search others (and the DB write) wait on.
    return await asyncio.shield(task)
