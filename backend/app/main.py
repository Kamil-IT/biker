import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()  # must run before anthropic_scorer imports AsyncAnthropic

from fastapi import FastAPI, HTTPException  # noqa: E402
from .schemas import (  # noqa: E402
    SearchRequest, BikeSearchResponse, CategoryResult,
    BikeDetailsRequest, BikeDetailsResponse,
    BikeReviewRequest, BikeReviewResponse,
    BikeOfferRequest, BikeOfferResponse,
)
from .categories import BIKE_CATEGORIES, CATEGORY_PROMPTS  # noqa: E402
from .anthropic_scorer import score_category  # noqa: E402
from .bike_finder import filter_top_categories, allocate_bikes, find_all_bikes  # noqa: E402
from .bike_details_finder import find_bike_details  # noqa: E402
from .bike_description_finder import find_bike_description  # noqa: E402
from .bike_review_finder import find_bike_review  # noqa: E402
from .bike_offer_finder import find_bike_offers  # noqa: E402
from .cache import init_cache, close_cache, get_cached, set_cached  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("biker.search")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_cache()
    yield
    close_cache()


app = FastAPI(title="Biker API", version="1.0.0", lifespan=lifespan)


@app.post("/v1/bike/search", response_model=BikeSearchResponse)
async def bike_search(req: SearchRequest) -> BikeSearchResponse:
    logger.info("search request received | query=%r", req.search)
    _fields = {"search": req.search}
    cached = get_cached("/v1/bike/search", _fields, BikeSearchResponse)
    if cached is not None:
        return cached

    category_results: list[CategoryResult] = []
    t_total = time.perf_counter()

    for name, _ in BIKE_CATEGORIES:
        t_cat = time.perf_counter()
        logger.info("scoring category | category=%r", name)
        try:
            result = await score_category(req.search, name, CATEGORY_PROMPTS[name])
            elapsed = time.perf_counter() - t_cat
            logger.info(
                "category scored   | category=%-20s score=%2d  elapsed=%.2fs  explanation=%r",
                f"{name!r}",
                result.score,
                elapsed,
                result.explanation,
            )
            category_results.append(result)
        except Exception as exc:
            logger.error("scoring failed | category=%r error=%s", name, exc)
            raise HTTPException(
                status_code=502,
                detail=f"Upstream error for category {name!r}: {exc}",
            ) from exc

    category_results.sort(key=lambda r: r.score, reverse=True)

    top = filter_top_categories(category_results)
    allocation = allocate_bikes(top)
    logger.info(
        "allocation | top_categories=%s",
        [(a["category"], a["count"]) for a in allocation],
    )

    bikes = await find_all_bikes(allocation, req.search)
    total_elapsed = time.perf_counter() - t_total
    logger.info(
        "search complete | bikes=%d total_elapsed=%.2fs",
        len(bikes),
        total_elapsed,
    )
    response = BikeSearchResponse(search=req.search, bikes=bikes)
    set_cached("/v1/bike/search", _fields, response)
    return response


@app.post("/v1/bike/details", response_model=BikeDetailsResponse)
async def bike_details(req: BikeDetailsRequest) -> BikeDetailsResponse:
    logger.info("details request | company=%r model=%r", req.company, req.model)
    _fields = {"company": req.company, "model": req.model}
    cached = get_cached("/v1/bike/details", _fields, BikeDetailsResponse)
    if cached is not None:
        return cached

    t_start = time.perf_counter()
    components, description = await asyncio.gather(
        find_bike_details(req.company, req.model),
        find_bike_description(req.company, req.model),
    )
    elapsed = time.perf_counter() - t_start
    logger.info(
        "details complete | categories=%d elapsed=%.2fs",
        len(components),
        elapsed,
    )
    response = BikeDetailsResponse(
        company=req.company,
        model=req.model,
        description=description,
        components=components,
    )
    set_cached("/v1/bike/details", _fields, response)
    return response


@app.post("/v1/bike/review", response_model=BikeReviewResponse)
async def bike_review(req: BikeReviewRequest) -> BikeReviewResponse:
    logger.info("review request | company=%r model=%r", req.company, req.model)
    _fields = {"company": req.company, "model": req.model}
    cached = get_cached("/v1/bike/review", _fields, BikeReviewResponse)
    if cached is not None:
        return cached

    t_start = time.perf_counter()
    result = await find_bike_review(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("review complete | score=%d elapsed=%.2fs", result.score, elapsed)
    set_cached("/v1/bike/review", _fields, result)
    return result


@app.post("/v1/bike/offer", response_model=BikeOfferResponse)
async def bike_offer(req: BikeOfferRequest) -> BikeOfferResponse:
    logger.info("offer request | company=%r model=%r", req.company, req.model)
    _fields = {"company": req.company, "model": req.model}
    cached = get_cached("/v1/bike/offer", _fields, BikeOfferResponse)
    if cached is not None:
        return cached

    t_start = time.perf_counter()
    result = await find_bike_offers(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("offer complete | offers=%d elapsed=%.2fs", len(result.offers), elapsed)
    set_cached("/v1/bike/offer", _fields, result)
    return result
