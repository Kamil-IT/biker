import logging
import time
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()  # must run before the finders construct AsyncAnthropic

import anthropic  # noqa: E402
from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from .schemas import (  # noqa: E402
    SearchRequest, BikeSearchResponse, BikeResult, BikeByIdRequest,
    BikeDetailsRequest, BikeDetailsResponse,
    BikeReviewRequest, BikeReviewResponse,
    BikeOfferRequest, BikeOfferResponse,
    UsedBikeRequest, UsedBikeResponse,
    BikePhotosRequest, BikePhotosResponse,
    EquipmentReviewRequest, EquipmentReviewResponse,
    ParseRequest, ParseResponse,
    MissingDataRequest, MissingDataResponse, PopularBikesResponse,
)
from .bike_finder import find_bikes  # noqa: E402
from .bike_offer_ceneo_finder import find_ceneo_offers  # noqa: E402
from .equipment_review_finder import find_equipment_review  # noqa: E402
from .bike_parser import parse_free_text  # noqa: E402
from .cache import init_cache, close_cache, get_cached, set_cached  # noqa: E402
from .store import (  # noqa: E402
    init_store, save_search,
)
# Details are served from the ORM tables (bike.description / short_description + bike_component),
# not the retired bike_details_cache blob — see TODO-019.
from .repository import (  # noqa: E402
    get_bike_details, find_bikes_by_details, record_missing_request,
    empty_details, fill_bike_results, get_bike_by_id,
)
from .offers_repository import (  # noqa: E402
    get_used_offers, get_decathlon_offers, get_allegro_offers, get_centrumrowerowe_offers,
    bike_exists,
)
from .popular_repository import get_popular_bikes  # noqa: E402
from .photos_repository import get_bike_photos  # noqa: E402
from .reviews_repository import get_review  # noqa: E402
# Equipment details / photos (DB reads) and their on-demand searches, TODO-042.
from .equipment_routes import router as equipment_router  # noqa: E402
# The Kontakt tab's "Napisz do nas" form → contact_message.
from .contact_routes import router as contact_router  # noqa: E402
# The OLX used-bike search (TODO-031), the Decathlon search (TODO-032), the
# Allegro search (TODO-033), the bike photo search and the bike review search
# (TODO-037), the bike details search (TODO-041) and the equipment details / photo
# searches (TODO-042, routes in equipment_routes.py) live in the separate searcher
# service; the backend reads the DB and proxies the on-demand searches to it.
from .searcher_client import (  # noqa: E402
    search_olx, search_decathlon, search_allegro, search_photos, search_review, search_details,
    SearcherNotConfigured, SearcherUnavailable, SearcherBusy, SearcherFailed, SearcherLimitReached,
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
app.include_router(equipment_router)
app.include_router(contact_router)


@app.exception_handler(anthropic.BadRequestError)
async def anthropic_bad_request(request: Request, exc: anthropic.BadRequestError) -> JSONResponse:
    # A 400 from the Anthropic API (e.g. "Your credit balance is too low …") is
    # returned as a 400 carrying Anthropic's own message, not an unhandled 500.
    body = exc.body if isinstance(exc.body, dict) else {}
    error = body.get("error") if isinstance(body.get("error"), dict) else {}
    message = error.get("message") or exc.message
    logger.error("anthropic bad request | path=%s error=%s", request.url.path, message)
    return JSONResponse(status_code=400, content={"detail": message})


@app.exception_handler(SearcherLimitReached)
async def searcher_limit_reached(request: Request, exc: SearcherLimitReached) -> JSONResponse:
    # TODO-038: the searcher's `claude -p` hit the Claude subscription limit. It
    # reaches the browser in the same shape as anthropic_bad_request above —
    # 400 {"detail": <the CLI's own notice>} — not as a 502 / 503.
    logger.error("searcher limit reached | path=%s detail=%s", request.url.path, exc.detail)
    return JSONResponse(status_code=400, content={"detail": exc.detail})


@app.post("/v1/bike/search", response_model=BikeSearchResponse)
async def bike_search(req: SearchRequest) -> BikeSearchResponse:
    # No generic cache (endpoint_req_to_body_cache) here, neither read nor write.
    # It has no TTL and first write wins, so it kept serving answers frozen by
    # older builds (the 5-bike cap removed in TODO-025) for the same request body.
    enriched = req.enriched_query()

    # TODO-024: DB first — brand, model, bike_type (bike.category), wheel / frame
    # size, e-bike. [] straight away when none of those is set (only year / free
    # text) or when nothing matches; both go to the AI call.
    db_bikes = find_bikes_by_details(req)
    if db_bikes:
        logger.info("search served from DB | enriched_query=%r bikes=%d", enriched, len(db_bikes))
        return BikeSearchResponse(search=enriched, bikes=db_bikes)

    logger.info("search request (AI) | enriched_query=%r", enriched)
    t_total = time.perf_counter()
    try:
        bikes = await find_bikes(enriched)
    except anthropic.BadRequestError:
        raise  # → anthropic_bad_request: 400 with Anthropic's message
    except Exception as exc:  # noqa: BLE001 — upstream API failure, not a parse error
        logger.error("bike search failed | error=%s", exc)
        raise HTTPException(status_code=502, detail=f"Upstream error: {exc}") from exc
    logger.info(
        "search complete | bikes=%d total_elapsed=%.2fs",
        len(bikes), time.perf_counter() - t_total,
    )
    # save_search is not a response cache: it only makes sure the found bikes
    # exist in `bike`, a NULL category set from bike_type (a later search finds
    # them in the DB). Nothing per-search is stored (TODO-043).
    if bikes:
        save_search(enriched, bikes, bike_type=req.bike_type)
        # explanation / accessories come from the bikes' stored details (TODO-041),
        # never from the AI: a bike found only by the AI has none → "" / [].
        bikes = fill_bike_results(bikes)
    return BikeSearchResponse(search=enriched, bikes=bikes)


@app.post("/v1/bike/details", response_model=BikeDetailsResponse)
async def bike_details(req: BikeDetailsRequest) -> BikeDetailsResponse:
    """Stored bike details — a pure DB read (TODO-041): no AI, no generic cache.

    Unknown bike / nothing stored → 200 with the empty response (the frontend
    shows "Poproś o dane"). The on-demand search is /v1/bike/details/search.
    """
    logger.info("details request | company=%r model=%r", req.company, req.model)
    stored = get_bike_details(req.company, req.model)
    if stored is None:
        return empty_details(req.company, req.model)
    return stored.model_copy(update={"company": req.company, "model": req.model})


@app.post("/v1/bike/by-id", response_model=BikeResult)
async def bike_by_id(req: BikeByIdRequest) -> BikeResult:
    """One bike by its id — the frontend's /bike/{id} deep link. A pure DB read, no AI, no cache.

    Answers the search-result shape (stored casing, short description, chips); 404
    "Bike not found" for an unknown id, 503 when the DB read fails.
    """
    try:
        bike = get_bike_by_id(req.bike_id)
    except Exception as exc:  # noqa: BLE001 — a DB error is not "not found"
        logger.error("bike by id read failed | bike_id=%d | %s", req.bike_id, exc)
        raise HTTPException(status_code=503, detail="Bike lookup failed") from exc
    if bike is None:
        raise HTTPException(status_code=404, detail="Bike not found")
    return bike


@app.post("/v1/bike/details/search", response_model=BikeDetailsResponse)
async def bike_details_search(req: BikeDetailsRequest) -> BikeDetailsResponse:
    """Run the bike-details search on demand through the searcher service (TODO-041).

    Proxies to {SEARCHER_URL}/v1/search/details and waits for it
    (SEARCHER_TIMEOUT, default 600 s) — always, whatever is stored: whether a
    search is worth paying for is the caller's decision (the UI offers it only
    while nothing is stored). The searcher runs `claude -p` once, stores the result only when
    usable, and returns what is now stored (the empty response when nothing usable
    was found). Shares SEARCHER_MAX_INFLIGHT with the other searches. 503 when the
    searcher is not configured, unreachable or busy, 502 (its detail passed
    through) when it fails. Never cached.
    """
    logger.info("details search request | company=%r model=%r", req.company, req.model)
    if not bike_exists(req.company, req.model):
        logger.warning("details search refused: unknown bike | company=%r model=%r", req.company, req.model)
        raise HTTPException(status_code=404, detail="Bike not found")
    t_start = time.perf_counter()
    try:
        result = await search_details(req.company, req.model)
    except SearcherNotConfigured as exc:
        logger.error("details search: searcher not configured | %s", exc)
        raise HTTPException(status_code=503, detail="Details searcher is not configured") from exc
    except SearcherUnavailable as exc:
        logger.error("details search: searcher unavailable | %s", exc)
        raise HTTPException(status_code=503, detail="Details searcher unavailable") from exc
    except SearcherBusy as exc:
        logger.warning("details search: searcher busy | %s", exc)
        raise HTTPException(status_code=503, detail="Details searcher is busy — try again in a moment") from exc
    except SearcherFailed as exc:
        logger.error("details search failed | status=%d detail=%r", exc.status, exc.detail)
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    logger.info(
        "details search complete | categories=%d elapsed=%.2fs",
        len(result.components), time.perf_counter() - t_start,
    )
    return result


@app.post("/v1/bike/missing", response_model=MissingDataResponse)
async def bike_missing(req: MissingDataRequest) -> MissingDataResponse:
    """Count a user's "Request data" click for an empty details section (TODO-026).

    No AI call and no generic cache — just an upsert on bike_missing_request.
    An unknown bike is still a 200, with bike_id null and counter 0.
    """
    logger.info("missing request | company=%r model=%r type=%r", req.company, req.model, req.missing_type)
    return record_missing_request(req.company, req.model, req.missing_type)


@app.get("/v1/bike/popular", response_model=PopularBikesResponse)
async def bike_popular() -> PopularBikesResponse:
    """Curated home-page bikes from bike_popular (TODO-034) — a pure DB read: no AI call, no generic cache."""
    logger.info("popular bikes request")
    return get_popular_bikes()


@app.post("/v1/bike/photos", response_model=BikePhotosResponse)
async def bike_photos(req: BikePhotosRequest) -> BikePhotosResponse:
    """Stored photos for the bike — a pure DB read.

    No AI call, no generic cache, no TTL: bike_detail_photos is filled only by
    the searcher service, triggered through /v1/bike/photos/search. Unknown
    bike, nothing stored or a DB error → 200 with an empty list.
    """
    logger.info("photos request | company=%r model=%r", req.company, req.model)
    t_start = time.perf_counter()
    result = get_bike_photos(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("photos served from DB | photos=%d elapsed=%.3fs", len(result.photos), elapsed)
    return result


@app.post("/v1/bike/photos/search", response_model=BikePhotosResponse)
async def bike_photos_search(req: BikePhotosRequest) -> BikePhotosResponse:
    """Run the photo search on demand through the searcher service.

    Proxies to {SEARCHER_URL}/v1/search/photos and waits for it
    (SEARCHER_TIMEOUT, default 600 s). The searcher finds the manufacturer
    page with `claude -p`, scrapes it with Playwright and stores the photos —
    only for a bike that has none; otherwise it returns the stored ones without
    a search. 503 when the searcher is not configured, unreachable or busy, 502
    (its detail passed through) when it fails. Never cached.
    """
    logger.info("photos search request | company=%r model=%r", req.company, req.model)
    # Same guard as the offer proxies: only bikes the app already knows, or
    # anonymous traffic could mint `bike` rows and spend subscription runs.
    if not bike_exists(req.company, req.model):
        logger.warning("photos search refused: unknown bike | company=%r model=%r", req.company, req.model)
        raise HTTPException(status_code=404, detail="Bike not found")
    t_start = time.perf_counter()
    try:
        result = await search_photos(req.company, req.model)
    except SearcherNotConfigured as exc:
        logger.error("photos search: searcher not configured | %s", exc)
        raise HTTPException(status_code=503, detail="Photos searcher is not configured") from exc
    except SearcherUnavailable as exc:
        logger.error("photos search: searcher unavailable | %s", exc)
        raise HTTPException(status_code=503, detail="Photos searcher unavailable") from exc
    except SearcherBusy as exc:
        logger.warning("photos search: searcher busy | %s", exc)
        raise HTTPException(status_code=503, detail="Photos searcher is busy — try again in a moment") from exc
    except SearcherFailed as exc:
        logger.error("photos search failed | status=%d detail=%r", exc.status, exc.detail)
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    elapsed = time.perf_counter() - t_start
    logger.info("photos search complete | photos=%d elapsed=%.2fs", len(result.photos), elapsed)
    return result


@app.post("/v1/bike/review", response_model=BikeReviewResponse)
async def bike_review(req: BikeReviewRequest) -> BikeReviewResponse:
    """The stored expert review of the bike — a pure DB read (TODO-037).

    No AI call, no generic cache, no TTL: bike_review / bike_review_source are
    filled only by the searcher service, triggered through
    /v1/bike/review/search. Unknown bike, nothing stored or a DB error → 200
    with the empty review (score 0, explanation "", ref [], rating 0.0,
    sources_used 0). (The generic-cache rows the old web_search finder wrote
    under /v1/bike/review are not read any more.)
    """
    logger.info("review request | company=%r model=%r", req.company, req.model)
    t_start = time.perf_counter()
    result = get_review(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info(
        "review served from DB | rating=%.1f sources_used=%d refs=%d elapsed=%.3fs",
        result.rating, result.sources_used, len(result.ref), elapsed,
    )
    return result


@app.post("/v1/bike/review/search", response_model=BikeReviewResponse)
async def bike_review_search(req: BikeReviewRequest) -> BikeReviewResponse:
    """Run the expert-review search on demand through the searcher service (TODO-037).

    Proxies to {SEARCHER_URL}/v1/search/review and waits for it
    (SEARCHER_TIMEOUT, default 600 s) — always, whatever is stored: whether a
    search is worth paying for is the caller's decision (the UI offers it only
    while nothing is stored). The searcher runs `claude -p` once,
    stores the review only when it has sources, and returns what is now stored
    for the bike (the empty review when nothing usable was found). Shares
    SEARCHER_MAX_INFLIGHT with the other searches. 503 when the searcher is not
    configured, unreachable or busy, 502 (its detail passed through) when it
    fails. Never cached.
    """
    logger.info("review search request | company=%r model=%r", req.company, req.model)
    # Same guard as the other proxies: only bikes the app already knows, or
    # anonymous traffic could mint `bike` rows and spend subscription runs.
    if not bike_exists(req.company, req.model):
        logger.warning("review search refused: unknown bike | company=%r model=%r", req.company, req.model)
        raise HTTPException(status_code=404, detail="Bike not found")
    t_start = time.perf_counter()
    try:
        result = await search_review(req.company, req.model)
    except SearcherNotConfigured as exc:
        logger.error("review search: searcher not configured | %s", exc)
        raise HTTPException(status_code=503, detail="Review searcher is not configured") from exc
    except SearcherUnavailable as exc:
        logger.error("review search: searcher unavailable | %s", exc)
        raise HTTPException(status_code=503, detail="Review searcher unavailable") from exc
    except SearcherBusy as exc:
        logger.warning("review search: searcher busy | %s", exc)
        raise HTTPException(status_code=503, detail="Review searcher is busy — try again in a moment") from exc
    except SearcherFailed as exc:
        logger.error("review search failed | status=%d detail=%r", exc.status, exc.detail)
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    elapsed = time.perf_counter() - t_start
    logger.info(
        "review search complete | rating=%.1f sources_used=%d refs=%d elapsed=%.2fs",
        result.rating, result.sources_used, len(result.ref), elapsed,
    )
    return result


@app.post("/v1/bike/allegro", response_model=BikeOfferResponse)
async def bike_allegro(req: BikeOfferRequest) -> BikeOfferResponse:
    """Stored allegro.pl offers for the bike — a pure DB read (TODO-033).

    No AI call and no generic cache: the bike's 'allegro.pl' rows in
    bike_offer / bike_offer_photos are filled only by the searcher service,
    triggered through /v1/bike/allegro/search. Nothing stored → 200 with an
    empty list. (The generic-cache rows the old web_search finder wrote under
    the key /v1/bike/offer are not read any more — see TODO-033 decision 5.)
    """
    logger.info("allegro request | company=%r model=%r", req.company, req.model)
    t_start = time.perf_counter()
    result = get_allegro_offers(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("allegro served from DB | offers=%d elapsed=%.3fs", len(result.offers), elapsed)
    return result


@app.post("/v1/bike/allegro/search", response_model=BikeOfferResponse)
async def bike_allegro_search(req: BikeOfferRequest) -> BikeOfferResponse:
    """Run the Allegro search on demand through the searcher service (TODO-033).

    Proxies to {SEARCHER_URL}/v1/search/allegro and waits for it
    (SEARCHER_TIMEOUT, default 600 s). The searcher writes the offers to the
    DB (no photos — allegro.pl blocks scraping), so a later /v1/bike/allegro
    returns them. The "Nowe" card's button fires this together with
    /v1/bike/decathlon/search; both share SEARCHER_MAX_INFLIGHT (default 10)
    with the other searches. 503 when the searcher is not configured,
    unreachable or busy, 502 (its detail passed through) when it fails.
    Never cached.
    """
    logger.info("allegro search request | company=%r model=%r", req.company, req.model)
    # Same guard as the other two proxies: only bikes the app already knows, or
    # anonymous traffic could mint `bike` rows and spend subscription runs.
    if not bike_exists(req.company, req.model):
        logger.warning("allegro search refused: unknown bike | company=%r model=%r", req.company, req.model)
        raise HTTPException(status_code=404, detail="Bike not found")
    t_start = time.perf_counter()
    try:
        result = await search_allegro(req.company, req.model)
    except SearcherNotConfigured as exc:
        logger.error("allegro search: searcher not configured | %s", exc)
        raise HTTPException(status_code=503, detail="Allegro searcher is not configured") from exc
    except SearcherUnavailable as exc:
        logger.error("allegro search: searcher unavailable | %s", exc)
        raise HTTPException(status_code=503, detail="Allegro searcher unavailable") from exc
    except SearcherBusy as exc:
        logger.warning("allegro search: searcher busy | %s", exc)
        raise HTTPException(status_code=503, detail="Allegro searcher is busy — try again in a moment") from exc
    except SearcherFailed as exc:
        logger.error("allegro search failed | status=%d detail=%r", exc.status, exc.detail)
        raise HTTPException(status_code=502, detail=exc.detail) from exc
    elapsed = time.perf_counter() - t_start
    logger.info("allegro search complete | offers=%d elapsed=%.2fs", len(result.offers), elapsed)
    return result


@app.post("/v1/bike/used/olx", response_model=UsedBikeResponse)
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
    /v1/bike/used/olx returns them. 503 when the searcher is not configured or
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


# DEPRECATED — not used: no frontend or searcher caller since the UI dropped Ceneo; kept only until removal.
@app.post("/v1/bike/ceneo", response_model=BikeOfferResponse, deprecated=True)
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


@app.post("/v1/bike/centrumrowerowe", response_model=BikeOfferResponse)
async def bike_centrumrowerowe(req: BikeOfferRequest) -> BikeOfferResponse:
    """Stored centrumrowerowe.pl offers for the bike — a pure DB read.

    No AI call, no generic cache and no search route: the bike's
    'centrumrowerowe.pl' rows in bike_offer are written only by the local
    discovery enrichment (webscraper/centrumrowerowe/enrich.py). Nothing
    stored → 200 with an empty list.
    """
    logger.info("centrumrowerowe request | company=%r model=%r", req.company, req.model)
    t_start = time.perf_counter()
    result = get_centrumrowerowe_offers(req.company, req.model)
    elapsed = time.perf_counter() - t_start
    logger.info("centrumrowerowe served from DB | offers=%d elapsed=%.3fs", len(result.offers), elapsed)
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
    _fields = {"text": req.text, "v": "2"}  # v2 = with bike_type: older rows never had it
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
