"""Equipment details and photos (TODO-042): DB reads plus the on-demand searches.

POST /v1/equipment/details and POST /v1/equipment/photos are pure DB reads
(no AI, no generic cache, no TTL). POST /v1/equipment/details/search and
POST /v1/equipment/photos/search proxy to the searcher service through
app/searcher_client.py, after two 404 guards (unknown bike, unknown element of
its stored spec tree). A SearcherLimitReached becomes a 400 through the
app-wide handler in app/main.py. POST /v1/equipment/review stays in main.py.
"""
import logging
import time

from fastapi import APIRouter, HTTPException

from .equipment_repository import bike_component_name, get_equipment_details, get_equipment_photos
from .offers_repository import bike_exists
from .schemas import (
    EquipmentDetailsRequest, EquipmentDetailsResponse,
    EquipmentPhotosRequest, EquipmentPhotosResponse, EquipmentSearchRequest,
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


def _check_equipment_search(req: EquipmentSearchRequest, label: str) -> tuple[str, str]:
    """The 404 guards of the equipment searches, before any searcher call; returns the stored
    (element name, element type = its subcategory, e.g. "Frame").

    Only an element of a known bike's stored spec tree can be searched, so
    anonymous traffic cannot spend subscription runs on arbitrary strings. The
    searcher gets the element name as stored on the bike, never the caller's spelling, and
    the element type, so an element named exactly like the bike (a frame) is searched as
    that part, not as the complete bike.
    """
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
    return found


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

    404 "Bike not found" / "Component not found" before any searcher call;
    then proxies to {SEARCHER_URL}/v1/search/equipment/details and waits
    (SEARCHER_TIMEOUT, default 600 s) — always, whatever is stored: the UI
    offers the search only while nothing is stored. The searcher runs `claude -p`
    once, stores a usable result (creating the equipment row and linking this
    bike's element rows) and returns what is stored, `equipment_id` included.
    503 not configured / unreachable / busy, 502 its detail, 400 subscription
    limit (handler above). Never cached.
    """
    logger.info(
        "equipment details search request | bike=%r %r element=%r category=%r",
        req.bike_company, req.bike_model, req.element_name, req.category,
    )
    element_name, element_type = _check_equipment_search(req, "equipment details")
    t_start = time.perf_counter()
    try:
        result = await search_equipment_details(
            req.bike_company, req.bike_model, element_name, req.category, element_type=element_type,
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
        "equipment photos search request | bike=%r %r element=%r category=%r",
        req.bike_company, req.bike_model, req.element_name, req.category,
    )
    element_name, element_type = _check_equipment_search(req, "equipment photos")
    t_start = time.perf_counter()
    try:
        result = await search_equipment_photos(
            req.bike_company, req.bike_model, element_name, req.category, element_type=element_type,
        )
    except _PROXIED_ERRORS as exc:
        raise _equipment_searcher_error(exc, "equipment photos", "Equipment photos") from exc
    logger.info(
        "equipment photos search complete | equipment_id=%s photos=%d elapsed=%.2fs",
        result.equipment_id, len(result.photos), time.perf_counter() - t_start,
    )
    return result
