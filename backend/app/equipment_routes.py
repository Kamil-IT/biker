"""Equipment details and photos (TODO-042): DB reads plus the on-demand searches.

POST /v1/equipment/details and POST /v1/equipment/photos are pure DB reads
(no AI, no generic cache, no TTL). POST /v1/equipment/by-id (identity + first
linked bike) and POST /v1/equipment/resolve (the row of a clicked element,
created empty when missing) serve the frontend's /equipment/{id} pages, no AI.
POST /v1/equipment/details/search and POST /v1/equipment/photos/search proxy
to the searcher service through app/searcher_client.py, after the 404 guards
(unknown item / bike / element of its stored spec tree; a catalogue part no bike
links is searched without a bike, TODO-046). A SearcherLimitReached
becomes a 400 through the app-wide handler in app/main.py. POST
/v1/equipment/review stays in main.py.
"""
import logging
import time

from fastapi import APIRouter, HTTPException

from .equipment_lookup import NotFound, SearchContext, get_equipment_item, resolve_equipment, search_context
from .equipment_repository import bike_component_name, get_equipment_details, get_equipment_photos
from .offers_repository import bike_exists
from .schemas import (
    EquipmentByIdRequest, EquipmentDetailsRequest, EquipmentDetailsResponse, EquipmentItemResponse,
    EquipmentPhotosRequest, EquipmentPhotosResponse, EquipmentResolveRequest, EquipmentResolveResponse,
    EquipmentSearchRequest,
)
from .searcher_client import (
    SearcherBusy, SearcherFailed, SearcherNotConfigured, SearcherUnavailable,
    search_equipment_details, search_equipment_photos,
)

logger = logging.getLogger("biker.search")
router = APIRouter()


@router.post("/v1/equipment/details", response_model=EquipmentDetailsResponse)
async def equipment_details(req: EquipmentDetailsRequest) -> EquipmentDetailsResponse:
    """Stored equipment details — a pure DB read (TODO-042): no AI, no generic cache, no TTL.

    Resolved by `equipment_id` when given, else by the normalised (company,
    model), category ignored. Unknown equipment / nothing stored / a DB error →
    200 with the empty response (the frontend shows "Poproś o dane"). The
    on-demand search is /v1/equipment/details/search.
    """
    logger.info(
        "equipment details request | id=%r company=%r model=%r category=%r",
        req.equipment_id, req.company, req.model, req.category,
    )
    t_start = time.perf_counter()
    result = get_equipment_details(req)
    logger.info(
        "equipment details served from DB | equipment_id=%s categories=%d elapsed=%.3fs",
        result.equipment_id, len(result.components), time.perf_counter() - t_start,
    )
    return result


@router.post("/v1/equipment/photos", response_model=EquipmentPhotosResponse)
async def equipment_photos(req: EquipmentPhotosRequest) -> EquipmentPhotosResponse:
    """Stored equipment photos — a pure DB read (TODO-042), same lookup as /v1/equipment/details.

    Unknown equipment / nothing stored / a DB error → 200 {photos: [], equipment_id}.
    """
    logger.info("equipment photos request | id=%r company=%r model=%r", req.equipment_id, req.company, req.model)
    t_start = time.perf_counter()
    result = get_equipment_photos(req)
    logger.info(
        "equipment photos served from DB | equipment_id=%s photos=%d elapsed=%.3fs",
        result.equipment_id, len(result.photos), time.perf_counter() - t_start,
    )
    return result


@router.post("/v1/equipment/by-id", response_model=EquipmentItemResponse)
async def equipment_by_id(req: EquipmentByIdRequest) -> EquipmentItemResponse:
    """One equipment item by its id — the frontend's /equipment/{id} deep link. A pure DB read.

    Answers the item's identity (name, category, researched company / model) and the
    first bike whose spec tree links it (`bike`, null when none — the back target).
    404 "Equipment not found" for an unknown id, 503 when the DB read fails.
    """
    try:
        item = get_equipment_item(req.equipment_id)
    except Exception as exc:  # noqa: BLE001 — a DB error is not "not found"
        logger.error("equipment by id read failed | equipment_id=%d | %s", req.equipment_id, exc)
        raise HTTPException(status_code=503, detail="Equipment lookup failed") from exc
    if item is None:
        raise HTTPException(status_code=404, detail="Equipment not found")
    return item


@router.post("/v1/equipment/resolve", response_model=EquipmentResolveResponse)
async def equipment_resolve(req: EquipmentResolveRequest) -> EquipmentResolveResponse:
    """The equipment row of one element of a bike's spec tree — created empty when missing. No AI, free.

    The bike view's click on a linkable element calls it, then opens /equipment/{id}:
    the row (name = the stored element name, category inferred like the searcher's)
    is reused when the element is already linked or an item of that name exists,
    and THIS bike's rows of the element are linked. 404 "Bike not found" /
    "Component not found" for an unknown bike / element, 503 on a DB error.
    """
    logger.info("equipment resolve request | bike_id=%d element=%r", req.bike_id, req.element_name)
    try:
        return resolve_equipment(req.bike_id, req.element_name)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.error("equipment resolve failed | bike_id=%d element=%r | %s", req.bike_id, req.element_name, exc)
        raise HTTPException(status_code=503, detail="Equipment lookup failed") from exc


def _check_equipment_search(req: EquipmentSearchRequest, label: str) -> SearchContext:
    """The 404 guards of the equipment searches, before any searcher call; returns what the searcher gets.

    By `equipment_id`: 404 "Equipment not found"; the context bike is `bike_id` when
    it links the item, else the first bike linking it — none for a catalogue part no
    bike links (TODO-046), which is searched without a bike, its part type as the
    element type — and the item's stored name and category are sent, so the
    searcher stores into this very row. By bike + element name: only an element of
    a known bike's stored spec tree can be searched, so anonymous traffic cannot
    spend subscription runs on arbitrary strings; the searcher gets the element name
    as stored on the bike, never the caller's spelling. Either way the element type
    (its subcategory, e.g. "Frame") goes along, so an element named exactly like the
    bike (a frame) is searched as that part, not as the complete bike.
    """
    if req.equipment_id is not None:
        try:
            return search_context(req.equipment_id, req.bike_id)
        except NotFound as exc:
            logger.warning("%s search refused: %s | equipment_id=%d", label, exc, req.equipment_id)
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not bike_exists(req.bike_company, req.bike_model):
        logger.warning("%s search refused: unknown bike | bike=%r %r", label, req.bike_company, req.bike_model)
        raise HTTPException(status_code=404, detail="Bike not found")
    found = bike_component_name(req.bike_company, req.bike_model, req.element_name)
    if found is None:
        logger.warning(
            "%s search refused: unknown component | bike=%r %r element=%r",
            label, req.bike_company, req.bike_model, req.element_name,
        )
        raise HTTPException(status_code=404, detail="Component not found")
    return SearchContext(req.bike_company, req.bike_model, found[0], found[1], req.category)


def _equipment_searcher_error(exc: Exception, label: str, name: str) -> HTTPException:
    """Map a searcher error to the route's 503 / 502 (SearcherLimitReached is left to its handler)."""
    if isinstance(exc, SearcherNotConfigured):
        logger.error("%s search: searcher not configured | %s", label, exc)
        return HTTPException(status_code=503, detail=f"{name} searcher is not configured")
    if isinstance(exc, SearcherUnavailable):
        logger.error("%s search: searcher unavailable | %s", label, exc)
        return HTTPException(status_code=503, detail=f"{name} searcher unavailable")
    if isinstance(exc, SearcherBusy):
        logger.warning("%s search: searcher busy | %s", label, exc)
        return HTTPException(status_code=503, detail=f"{name} searcher is busy — try again in a moment")
    assert isinstance(exc, SearcherFailed)
    logger.error("%s search failed | status=%d detail=%r", label, exc.status, exc.detail)
    return HTTPException(status_code=502, detail=exc.detail)


_PROXIED_ERRORS = (SearcherNotConfigured, SearcherUnavailable, SearcherBusy, SearcherFailed)


@router.post("/v1/equipment/details/search", response_model=EquipmentDetailsResponse)
async def equipment_details_search(req: EquipmentSearchRequest) -> EquipmentDetailsResponse:
    """Run the equipment details search on demand through the searcher service (TODO-042).

    404 "Equipment not found" (by id) / "Bike not found" / "Component not found" (by
    bike + element name) before any searcher call;
    then proxies to {SEARCHER_URL}/v1/search/equipment/details and waits
    (SEARCHER_TIMEOUT, default 600 s) — always, whatever is stored: the UI
    offers the search only while nothing is stored. The searcher runs `claude -p`
    once, stores a usable result (creating the equipment row and linking this
    bike's element rows) and returns what is stored, `equipment_id` included.
    503 not configured / unreachable / busy, 502 its detail, 400 subscription
    limit (handler above). Never cached.
    """
    logger.info(
        "equipment details search request | id=%r bike_id=%r bike=%r %r element=%r category=%r",
        req.equipment_id, req.bike_id, req.bike_company, req.bike_model, req.element_name, req.category,
    )
    ctx = _check_equipment_search(req, "equipment details")
    t_start = time.perf_counter()
    try:
        result = await search_equipment_details(
            ctx.bike_company, ctx.bike_model, ctx.element_name, ctx.category, element_type=ctx.element_type,
        )
    except _PROXIED_ERRORS as exc:
        raise _equipment_searcher_error(exc, "equipment details", "Equipment details") from exc
    logger.info(
        "equipment details search complete | equipment_id=%s categories=%d elapsed=%.2fs",
        result.equipment_id, len(result.components), time.perf_counter() - t_start,
    )
    return result


@router.post("/v1/equipment/photos/search", response_model=EquipmentPhotosResponse)
async def equipment_photos_search(req: EquipmentSearchRequest) -> EquipmentPhotosResponse:
    """Run the equipment photo search on demand through the searcher service (TODO-042).

    Same guards and error mapping as /v1/equipment/details/search; proxies to
    {SEARCHER_URL}/v1/search/equipment/photos, which finds the manufacturer
    page with `claude -p`, scrapes it with Playwright and stores the photos only
    for equipment that has none. Returns {photos, equipment_id} as stored. Never cached.
    """
    logger.info(
        "equipment photos search request | id=%r bike_id=%r bike=%r %r element=%r category=%r",
        req.equipment_id, req.bike_id, req.bike_company, req.bike_model, req.element_name, req.category,
    )
    ctx = _check_equipment_search(req, "equipment photos")
    t_start = time.perf_counter()
    try:
        result = await search_equipment_photos(
            ctx.bike_company, ctx.bike_model, ctx.element_name, ctx.category, element_type=ctx.element_type,
        )
    except _PROXIED_ERRORS as exc:
        raise _equipment_searcher_error(exc, "equipment photos", "Equipment photos") from exc
    logger.info(
        "equipment photos search complete | equipment_id=%s photos=%d elapsed=%.2fs",
        result.equipment_id, len(result.photos), time.perf_counter() - t_start,
    )
    return result
