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
    UsedBikeRequest, UsedBikeResponse,
    EquipmentDetailsRequest, EquipmentDetailsResponse,
    EquipmentReviewRequest, EquipmentReviewResponse,
    ParseRequest, ParseResponse,
    CachedSearchResponse,
)
from .categories import BIKE_CATEGORIES, CATEGORY_PROMPTS  # noqa: E402
from .anthropic_scorer import score_category  # noqa: E402
from .bike_finder import filter_top_categories, allocate_bikes, find_all_bikes  # noqa: E402
from .bike_details_finder import find_bike_details  # noqa: E402
from .bike_description_finder import find_bike_description  # noqa: E402
from .bike_photos_finder import find_bike_photos  # noqa: E402
from .bike_review_finder import find_bike_review  # noqa: E402
from .bike_offer_finder import find_bike_offers  # noqa: E402
from .bike_used_finder import find_used_bikes  # noqa: E402
from .bike_offer_ceneo_finder import find_ceneo_offers  # noqa: E402
from .bike_offer_decathlon_finder import find_decathlon_offers  # noqa: E402
from .equipment_details_finder import find_equipment_details  # noqa: E402
from .equipment_description_finder import find_equipment_description  # noqa: E402
from .equipment_photos_finder import find_equipment_photos  # noqa: E402
from .equipment_review_finder import find_equipment_review  # noqa: E402
from .bike_parser import parse_free_text  # noqa: E402
from .cache import init_cache, close_cache, get_cached, set_cached  # noqa: E402
from .store import (  # noqa: E402
    init_store, save_search, get_search_by_query, find_bikes_by_brand,
    find_bike_by_brand_model, find_offer_prices,
    save_bike_details, get_bike_details,
)
from .models import init_db  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("biker.search")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_cache()
    init_store()
    init_db()
    yield
    close_cache()


app = FastAPI(title="Biker API", version="1.0.0", lifespan=lifespan)


@app.post("/v1/bike/search", response_model=BikeSearchResponse)
async def bike_search(req: SearchRequest) -> BikeSearchResponse:
    _fields = {k: str(v) for k, v in {
        "search": req.search, "brand": req.brand, "model": req.model,
        "year": req.year, "wheel_size": req.wheel_size,
        "is_electric": req.is_electric, "has_suspension": req.has_suspension,
        "is_kids": req.is_kids,
        "bike_type": req.bike_type, "price_max": req.price_max,
        "frame_size": req.frame_size, "rider_height_cm": req.rider_height_cm,
        "rider_weight_kg": req.rider_weight_kg,
        "gender": req.gender, "frame_material": req.frame_material,
        "brake_type": req.brake_type, "drivetrain": req.drivetrain,
        "belt_drive": req.belt_drive, "battery_capacity_wh": req.battery_capacity_wh,
    }.items() if v is not None}
    cached = get_cached("/v1/bike/search", _fields, BikeSearchResponse)
    if cached is not None:
        # Backfill the follow-up table on the hit path too. Without this the
        # semantic tables only ever fill on a generic-cache MISS, so a warm
        # cache.db leaves them permanently empty — see TODO-011.
        save_search(cached.search, cached.bikes)
        return cached

    # TODO-009: a brand+model search can often be answered straight from
    # search_cache, skipping the whole AI pipeline. Only price_max is gated —
    # no other filter has backing data in the cache (see backend/README.md).
    if req.brand and req.model:
        db_bikes = find_bike_by_brand_model(req.brand, req.model)
        if db_bikes and req.price_max is not None:
            kept = []
            for b in db_bikes:
                prices = find_offer_prices(b.brand, b.model)
                # Decision 3: unknown price passes.
                if not prices or min(prices) <= req.price_max:
                    kept.append(b)
            db_bikes = kept
        if db_bikes:
            enriched = req.enriched_query()
            logger.info(
                "search served from DB | brand=%r model=%r bikes=%d",
                req.brand, req.model, len(db_bikes),
            )
            # Decision 5: deliberately no set_cached here — the generic cache
            # has no TTL, so warming it would pin a 24 h result permanently.
            return BikeSearchResponse(search=enriched, bikes=db_bikes)
        # fall through to the AI pipeline

    enriched = req.enriched_query()
    logger.info("search request | enriched_query=%r", enriched)

    t_total = time.perf_counter()

    async def _score_one(name: str) -> CategoryResult:
        t_cat = time.perf_counter()
        logger.info("scoring category | category=%r", name)
        result = await score_category(enriched, name, CATEGORY_PROMPTS[name])
        elapsed = time.perf_counter() - t_cat
        logger.info(
            "category scored   | category=%-20s score=%2d  elapsed=%.2fs  explanation=%r",
            f"{name!r}",
            result.score,
            elapsed,
            result.explanation,
        )
        return result

    scored = await asyncio.gather(
        *(_score_one(name) for name, _ in BIKE_CATEGORIES),
        return_exceptions=True,
    )

    category_results: list[CategoryResult] = []
    for (name, _), result in zip(BIKE_CATEGORIES, scored):
        if isinstance(result, Exception):
            logger.error("scoring failed | category=%r error=%s", name, result)
            raise HTTPException(
                status_code=502,
                detail=f"Upstream error for category {name!r}: {result}",
            ) from result
        category_results.append(result)

    category_results.sort(key=lambda r: r.score, reverse=True)

    top = filter_top_categories(category_results)
    allocation = allocate_bikes(top)
    logger.info(
        "allocation | top_categories=%s",
        [(a["category"], a["count"]) for a in allocation],
    )

    bikes = await find_all_bikes(allocation, enriched)
    total_elapsed = time.perf_counter() - t_total
    logger.info(
        "search complete | bikes=%d total_elapsed=%.2fs",
        len(bikes),
        total_elapsed,
    )
    response = BikeSearchResponse(search=enriched, bikes=bikes)
    set_cached("/v1/bike/search", _fields, response)
    save_search(enriched, bikes)
    return response


@app.get("/v1/bike/search-cache", response_model=CachedSearchResponse)
async def bike_search_cache(query: str | None = None, brand: str | None = None) -> CachedSearchResponse:
    """Follow-up query served purely from the search cache — no web/Claude call.

    Pass `query` for an exact (normalised) repeat of a prior search, or `brand`
    to pull every cached bike from that brand across all stored searches.
    """
    if not query and not brand:
        raise HTTPException(status_code=422, detail="Provide either 'query' or 'brand'")

    if query:
        bikes = get_search_by_query(query)
        if bikes is None:
            raise HTTPException(status_code=404, detail="No cached search for that query")
        return CachedSearchResponse(query=query, cached=True, bikes=bikes)

    assert brand is not None
    bikes = find_bikes_by_brand(brand)
    return CachedSearchResponse(query=f"brand:{brand}", cached=bool(bikes), bikes=bikes)


@app.get("/v1/bike/details-cache", response_model=BikeDetailsResponse)
async def bike_details_cache_lookup(company: str, model: str) -> BikeDetailsResponse:
    """Follow-up details lookup served purely from cache — no web/Claude call."""
    cached = get_bike_details(company, model)
    if cached is None:
        raise HTTPException(status_code=404, detail="No cached details for that bike")
    return cached


@app.post("/v1/bike/details", response_model=BikeDetailsResponse)
async def bike_details(req: BikeDetailsRequest) -> BikeDetailsResponse:
    logger.info("details request | company=%r model=%r", req.company, req.model)
    _fields = {"company": req.company, "model": req.model}
    cached = get_cached("/v1/bike/details", _fields, BikeDetailsResponse)
    if cached is not None:
        # Backfill on the hit path — see the note in /v1/bike/search above.
        save_bike_details(req.company, req.model, cached)
        return cached

    t_start = time.perf_counter()
    components, description, photos = await asyncio.gather(
        find_bike_details(req.company, req.model),
        find_bike_description(req.company, req.model),
        find_bike_photos(req.company, req.model),
    )
    elapsed = time.perf_counter() - t_start
    logger.info(
        "details complete | categories=%d photos=%d elapsed=%.2fs",
        len(components),
        len(photos),
        elapsed,
    )
    response = BikeDetailsResponse(
        company=req.company,
        model=req.model,
        description=description,
        components=components,
        photos=photos,
    )
    set_cached("/v1/bike/details", _fields, response)
    save_bike_details(req.company, req.model, response)
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
    logger.info(
        "review complete | score=%d rating=%.1f sources_used=%d elapsed=%.2fs",
        result.score,
        result.rating,
        result.sources_used,
        elapsed,
    )
    # Require a usable aggregate too, not just links: caching a rating=0 /
    # sources_used=0 row would pin that degenerate result for this bike forever.
    if result.ref and result.sources_used >= 1:
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
    if result.offers:
        set_cached("/v1/bike/offer", _fields, result)
    return result


@app.post("/v1/bike/used", response_model=UsedBikeResponse)
async def bike_used(req: UsedBikeRequest) -> UsedBikeResponse:
    logger.info("used bikes request | company=%r model=%r", req.company, req.model)
    _fields = {"company": req.company, "model": req.model}
    cached = get_cached("/v1/bike/used", _fields, UsedBikeResponse)
    if cached is not None:
        return cached

    t_start = time.perf_counter()
    result = await find_used_bikes(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("used bikes complete | offers=%d elapsed=%.2fs", len(result.offers), elapsed)
    if result.offers:
        set_cached("/v1/bike/used", _fields, result)
    return result


@app.post("/v1/bike/ceneo", response_model=BikeOfferResponse)
async def bike_ceneo(req: BikeOfferRequest) -> BikeOfferResponse:
    logger.info("ceneo request | company=%r model=%r", req.company, req.model)
    _fields = {"company": req.company, "model": req.model}
    cached = get_cached("/v1/bike/ceneo", _fields, BikeOfferResponse)
    if cached is not None:
        return cached

    t_start = time.perf_counter()
    result = await find_ceneo_offers(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("ceneo complete | offers=%d elapsed=%.2fs", len(result.offers), elapsed)
    if result.offers:
        set_cached("/v1/bike/ceneo", _fields, result)
    return result


@app.post("/v1/bike/decathlon", response_model=BikeOfferResponse)
async def bike_decathlon(req: BikeOfferRequest) -> BikeOfferResponse:
    logger.info("decathlon request | company=%r model=%r", req.company, req.model)
    _fields = {"company": req.company, "model": req.model}
    cached = get_cached("/v1/bike/decathlon", _fields, BikeOfferResponse)
    if cached is not None:
        return cached

    t_start = time.perf_counter()
    result = await find_decathlon_offers(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("decathlon complete | offers=%d elapsed=%.2fs", len(result.offers), elapsed)
    if result.offers:
        set_cached("/v1/bike/decathlon", _fields, result)
    return result


@app.post("/v1/equipment/details", response_model=EquipmentDetailsResponse)
async def equipment_details(req: EquipmentDetailsRequest) -> EquipmentDetailsResponse:
    logger.info(
        "equipment details request | company=%r model=%r category=%r",
        req.company, req.model, req.category,
    )
    _fields = {"company": req.company, "model": req.model, "category": req.category or ""}
    cached = get_cached("/v1/equipment/details", _fields, EquipmentDetailsResponse)
    if cached is not None:
        return cached

    t_start = time.perf_counter()
    (category_components, description, photos) = await asyncio.gather(
        find_equipment_details(req.company, req.model, req.category),
        find_equipment_description(req.company, req.model),
        find_equipment_photos(req.company, req.model),
    )
    category_slug, components = category_components
    elapsed = time.perf_counter() - t_start
    logger.info(
        "equipment details complete | category=%r categories=%d photos=%d elapsed=%.2fs",
        category_slug, len(components), len(photos), elapsed,
    )
    response = EquipmentDetailsResponse(
        company=req.company,
        model=req.model,
        category=category_slug,
        description=description,
        components=components,
        photos=photos,
    )
    set_cached("/v1/equipment/details", _fields, response)
    return response


@app.post("/v1/equipment/review", response_model=EquipmentReviewResponse)
async def equipment_review(req: EquipmentReviewRequest) -> EquipmentReviewResponse:
    logger.info("equipment review request | company=%r model=%r", req.company, req.model)
    _fields = {"company": req.company, "model": req.model}
    cached = get_cached("/v1/equipment/review", _fields, EquipmentReviewResponse)
    if cached is not None:
        return cached

    t_start = time.perf_counter()
    result = await find_equipment_review(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("equipment review complete | score=%d elapsed=%.2fs", result.score, elapsed)
    if result.ref:
        set_cached("/v1/equipment/review", _fields, result)
    return result


@app.post("/v1/bike/parse", response_model=ParseResponse)
async def bike_parse(req: ParseRequest) -> ParseResponse:
    logger.info("parse request | text=%r", req.text[:80])
    _fields = {"text": req.text}
    cached = get_cached("/v1/bike/parse", _fields, ParseResponse)
    if cached is not None:
        return cached

    t_start = time.perf_counter()
    result = await parse_free_text(req.text)
    elapsed = time.perf_counter() - t_start
    logger.info("parse complete | elapsed=%.2fs result=%s", elapsed, result.model_dump(exclude_none=True))
    set_cached("/v1/bike/parse", _fields, result)
    return result
