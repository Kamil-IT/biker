import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()  # must run before the finders construct AsyncAnthropic

from fastapi import FastAPI, HTTPException  # noqa: E402
from .schemas import (  # noqa: E402
    SearchRequest, BikeSearchResponse,
    BikeDetailsRequest, BikeDetailsResponse,
    BikeReviewRequest, BikeReviewResponse,
    BikeOfferRequest, BikeOfferResponse,
    UsedBikeRequest, UsedBikeResponse,
    EquipmentDetailsRequest, EquipmentDetailsResponse,
    EquipmentReviewRequest, EquipmentReviewResponse,
    ParseRequest, ParseResponse,
    CachedSearchResponse,
    MissingDataRequest, MissingDataResponse,
)
from .bike_finder import find_bikes  # noqa: E402
from .bike_details_finder import find_bike_details  # noqa: E402
from .bike_description_finder import find_bike_description  # noqa: E402
from .bike_photos_finder import find_bike_photos  # noqa: E402
from .bike_review_finder import find_bike_review  # noqa: E402
from .bike_offer_finder import find_bike_offers  # noqa: E402
from .bike_offer_ceneo_finder import find_ceneo_offers  # noqa: E402
from .equipment_details_finder import find_equipment_details  # noqa: E402
from .equipment_description_finder import find_equipment_description  # noqa: E402
from .equipment_photos_finder import find_equipment_photos  # noqa: E402
from .equipment_review_finder import find_equipment_review  # noqa: E402
from .bike_parser import parse_free_text  # noqa: E402
from .cache import init_cache, close_cache, get_cached, set_cached  # noqa: E402
from .store import (  # noqa: E402
    init_store, save_search, get_search_by_query, find_bikes_by_brand,
)
# Details are served from the ORM tables (bike_detail + bike_detail_component),
# not the retired bike_details_cache blob — see TODO-019.
from .repository import (  # noqa: E402
    save_bike_details, get_bike_details, find_bikes_by_details, record_missing_request,
)
from .offers_repository import get_used_offers, get_decathlon_offers, bike_exists  # noqa: E402
# The OLX used-bike search (TODO-031) and the Decathlon search (TODO-032) live in
# the separate searcher service; the backend reads bike_offer and proxies the
# on-demand searches to it.
from .searcher_client import (  # noqa: E402
    search_olx, search_decathlon, SearcherNotConfigured, SearcherUnavailable, SearcherBusy, SearcherFailed,
)
from .decathlon_brands import is_decathlon_brand, not_sold_info  # noqa: E402
from .models import init_db  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("biker.search")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # first: creates every table, incl. the generic cache table
    init_cache()
    init_store()
    yield
    close_cache()


app = FastAPI(title="Biker API", version="1.0.0", lifespan=lifespan)


@app.post("/v1/bike/search", response_model=BikeSearchResponse)
async def bike_search(req: SearchRequest) -> BikeSearchResponse:
    _fields = {k: str(v) for k, v in {
        "search": req.search, "brand": req.brand, "model": req.model,
        "year": req.year, "wheel_size": req.wheel_size,
        "is_electric": req.is_electric,
        "bike_type": req.bike_type, "frame_size": req.frame_size,
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

    enriched = req.enriched_query()

    # TODO-024: DB first. find_bikes_by_details returns [] straight away when no
    # DB-checkable field is set (only bike_type / year / free text), so those
    # requests go straight to the AI call.
    db_bikes = find_bikes_by_details(req)
    if db_bikes:
        logger.info("search served from DB | enriched_query=%r bikes=%d", enriched, len(db_bikes))
        # Deliberately no set_cached: the generic cache has no TTL, so warming it
        # from the DB would pin this answer even after the DB changes.
        return BikeSearchResponse(search=enriched, bikes=db_bikes)

    logger.info("search request (AI) | enriched_query=%r", enriched)
    t_total = time.perf_counter()
    try:
        bikes = await find_bikes(enriched)
    except Exception as exc:  # noqa: BLE001 — upstream API failure, not a parse error
        logger.error("bike search failed | error=%s", exc)
        raise HTTPException(status_code=502, detail=f"Upstream error: {exc}") from exc
    logger.info(
        "search complete | bikes=%d total_elapsed=%.2fs",
        len(bikes), time.perf_counter() - t_total,
    )
    response = BikeSearchResponse(search=enriched, bikes=bikes)
    if bikes:
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


@app.post("/v1/bike/missing", response_model=MissingDataResponse)
async def bike_missing(req: MissingDataRequest) -> MissingDataResponse:
    """Count a user's "Request data" click for an empty details section (TODO-026).

    No AI call and no generic cache — just an upsert on bike_missing_request.
    An unknown bike is still a 200, with bike_id null and counter 0.
    """
    logger.info("missing request | company=%r model=%r type=%r", req.company, req.model, req.missing_type)
    return record_missing_request(req.company, req.model, req.missing_type)


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
    """Stored OLX listings for the bike — a pure DB read (TODO-031).

    No AI call and no generic cache: bike_offer / bike_offer_photos are filled
    only by the searcher service, triggered through /v1/bike/used/search.
    Nothing stored → 200 with an empty list.
    """
    logger.info("used bikes request | company=%r model=%r", req.company, req.model)
    t_start = time.perf_counter()
    result = get_used_offers(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("used bikes served from DB | offers=%d elapsed=%.3fs", len(result.offers), elapsed)
    return result


@app.post("/v1/bike/used/search", response_model=UsedBikeResponse)
async def bike_used_search(req: UsedBikeRequest) -> UsedBikeResponse:
    """Run the OLX search on demand through the searcher service (TODO-031).

    Proxies to {SEARCHER_URL}/v1/search/olx and waits for it (SEARCHER_TIMEOUT,
    default 600 s). The searcher writes the listings to the DB, so a later
    /v1/bike/used returns them. 503 when the searcher is not configured or
    unreachable, 502 (its detail passed through) when it fails. Never cached.
    """
    logger.info("used bikes search request | company=%r model=%r", req.company, req.model)
    # Only bikes the app already knows (save_search writes them before the details
    # view can open): the searcher would otherwise mint a `bike` row for any string
    # an anonymous caller sends, and every run costs a subscription search.
    if not bike_exists(req.company, req.model):
        logger.warning("used bikes search refused: unknown bike | company=%r model=%r", req.company, req.model)
        raise HTTPException(status_code=404, detail="Bike not found")
    t_start = time.perf_counter()
    try:
        result = await search_olx(req.company, req.model)
    except SearcherNotConfigured as exc:
        logger.error("used bikes search: searcher not configured | %s", exc)
        raise HTTPException(status_code=503, detail="OLX searcher is not configured") from exc
    except SearcherUnavailable as exc:
        logger.error("used bikes search: searcher unavailable | %s", exc)
        raise HTTPException(status_code=503, detail="OLX searcher unavailable") from exc
    except SearcherBusy as exc:
        logger.warning("used bikes search: searcher busy | %s", exc)
        raise HTTPException(status_code=503, detail="OLX searcher is busy — try again in a moment") from exc
    except SearcherFailed as exc:
        logger.error("used bikes search failed | status=%d detail=%r", exc.status, exc.detail)
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    elapsed = time.perf_counter() - t_start
    logger.info("used bikes search complete | offers=%d elapsed=%.2fs", len(result.offers), elapsed)
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
    """Stored decathlon.pl offers for the bike — a pure DB read (TODO-032).

    No AI call and no generic cache: the bike's 'decathlon.pl' rows in
    bike_offer are filled only by the searcher service, triggered through
    /v1/bike/decathlon/search. Nothing stored → 200 with an empty list.
    """
    logger.info("decathlon request | company=%r model=%r", req.company, req.model)
    t_start = time.perf_counter()
    result = get_decathlon_offers(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("decathlon served from DB | offers=%d elapsed=%.3fs", len(result.offers), elapsed)
    return result


@app.post("/v1/bike/decathlon/search", response_model=BikeOfferResponse)
async def bike_decathlon_search(req: BikeOfferRequest) -> BikeOfferResponse:
    """Run the Decathlon search on demand through the searcher service (TODO-032).

    Proxies to {SEARCHER_URL}/v1/search/decathlon and waits for it
    (SEARCHER_TIMEOUT, default 600 s). The searcher writes the offers to the
    DB, so a later /v1/bike/decathlon returns them. Decathlon sells only its
    house brands, so a foreign brand gets a 200 with an empty list and an
    explanatory `info` straight away — no searcher run (closes
    TODO_ISSUE_010). 503 when the searcher is not configured, unreachable or
    busy, 502 (its detail passed through) when it fails. Never cached.
    """
    logger.info("decathlon search request | company=%r model=%r", req.company, req.model)
    # Same guard as /v1/bike/used/search: only bikes the app already knows, or
    # anonymous traffic could mint `bike` rows and spend subscription runs.
    if not bike_exists(req.company, req.model):
        logger.warning("decathlon search refused: unknown bike | company=%r model=%r", req.company, req.model)
        raise HTTPException(status_code=404, detail="Bike not found")
    if not is_decathlon_brand(req.company):
        logger.info("decathlon search skipped: not a Decathlon house brand | company=%r model=%r", req.company, req.model)
        return BikeOfferResponse(offers=[], info=not_sold_info(req.company))
    t_start = time.perf_counter()
    try:
        result = await search_decathlon(req.company, req.model)
    except SearcherNotConfigured as exc:
        logger.error("decathlon search: searcher not configured | %s", exc)
        raise HTTPException(status_code=503, detail="Decathlon searcher is not configured") from exc
    except SearcherUnavailable as exc:
        logger.error("decathlon search: searcher unavailable | %s", exc)
        raise HTTPException(status_code=503, detail="Decathlon searcher unavailable") from exc
    except SearcherBusy as exc:
        logger.warning("decathlon search: searcher busy | %s", exc)
        raise HTTPException(status_code=503, detail="Decathlon searcher is busy — try again in a moment") from exc
    except SearcherFailed as exc:
        logger.error("decathlon search failed | status=%d detail=%r", exc.status, exc.detail)
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    elapsed = time.perf_counter() - t_start
    logger.info("decathlon search complete | offers=%d elapsed=%.2fs", len(result.offers), elapsed)
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


PARSE_NO_MATCH_DETAIL = "Bike not available in our database"


def _reject_empty_parse(result: ParseResponse, text: str) -> None:
    """400 when nothing could be extracted from the free text.

    An all-None payload is useless to the caller — the UI would populate no
    filters and show an unchanged form. Failing loudly lets it warn the user
    instead. Note this fires for a genuine "no attributes mentioned" text and
    for `parse_free_text`'s exception fallback alike: both mean no fields.
    """
    if result.is_empty():
        logger.info("parse no match | text=%r", text[:80])
        raise HTTPException(status_code=400, detail=PARSE_NO_MATCH_DETAIL)


@app.post("/v1/bike/parse", response_model=ParseResponse)
async def bike_parse(req: ParseRequest) -> ParseResponse:
    logger.info("parse request | text=%r", req.text[:80])
    _fields = {"text": req.text}
    cached = get_cached("/v1/bike/parse", _fields, ParseResponse)
    if cached is not None:
        # Older builds cached all-None results; reject those on the hit path too
        # so a warm cache.db cannot serve a 200 the fresh path would refuse.
        _reject_empty_parse(cached, req.text)
        return cached

    t_start = time.perf_counter()
    result = await parse_free_text(req.text)
    elapsed = time.perf_counter() - t_start
    logger.info("parse complete | elapsed=%.2fs result=%s", elapsed, result.model_dump(exclude_none=True))
    _reject_empty_parse(result, req.text)
    # Only the happy path is cached — an empty parse is now an error response.
    set_cached("/v1/bike/parse", _fields, result)
    return result
