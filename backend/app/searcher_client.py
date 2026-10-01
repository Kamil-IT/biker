"""HTTP client for the on-demand searcher service (TODO-031 OLX, TODO-032 Decathlon, TODO-033 Allegro, bike photos,
TODO-037 bike review, TODO-041 bike details: `search_details` posts to
/v1/search/details and unwraps {details}; TODO-042 equipment details and photos:
`search_equipment_details` / `search_equipment_photos` post the bike plus the
spec-tree element name to /v1/search/equipment/details and /photos).

The searcher (top-level `searcher/`, port 8100 locally) runs the Claude Code CLI
once per search — plus Playwright once per OLX listing, or once on the
manufacturer page for photos — and writes what it finds into bike_offer /
bike_offer_photos (offers), bike_detail_photos (photos) or bike_review /
bike_review_source (review). The backend only proxies the request, waits, and
hands back the searcher's body — it never calls Claude for OLX, Decathlon,
Allegro, bike photos or the bike review. One client, five routes:
`search_olx` posts to /v1/search/olx, `search_decathlon` to
/v1/search/decathlon, `search_allegro` to /v1/search/allegro,
`search_photos` to /v1/search/photos and `search_review` to
/v1/search/review (see SEARCH_PATHS); the offer routes answer {offers, info},
the photo route {photos}, the review route {review}, each validated into the
route's model. The equipment routes send {bike_company, bike_model,
element_name, category?} instead of {company, model}; their single-flight key
is (path, bike company, bike model, element name), all normalised.

Configuration (backend/.env):
  SEARCHER_URL           base URL, e.g. http://localhost:8100 — unset = not configured
  SEARCHER_API_KEY       shared secret sent as X-Searcher-Key — unset = not configured
  SEARCHER_TIMEOUT       seconds to wait for one search (default 600)
  SEARCHER_MAX_INFLIGHT  concurrent searches this backend lets through (default 10)

Every search is billed to the Claude subscription and takes minutes, so two
guards sit in front of the network call: identical (source, company, model)
requests share one in-flight search (single-flight), and at most
SEARCHER_MAX_INFLIGHT distinct searches run at once across ALL sources — the
semaphore is one process-wide object, not one per source, because it mirrors
the searcher's own capacity rather than anything per marketplace. The default
is 10 since the photo search moved to the searcher: it matches the searcher's
capacity (locally SEARCHER_MAX_CONCURRENT=10; on Cloud Run --max-instances 10
with --concurrency 1, i.e. one CLI per instance, plus a Chromium for an OLX or
photo search) — it must never exceed it. The rest are refused straight away,
as is a request the searcher itself answers 503 (busy) to — and so is a 429
from the searcher's URL: Cloud Run answers 429 "Rate exceeded" when every
instance is at --concurrency and max-instances is reached, which is the same
"no slot" condition seen from the outside. Queueing instead would let a search
outlive SEARCHER_TIMEOUT and end in a second paid run.
"""
import asyncio
import logging
import os
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel

from .schemas import (
    BikeDetailsResponse, BikeOfferResponse, BikePhotosResponse, BikeReviewResponse, UsedBikeResponse,
    EquipmentDetailsResponse, EquipmentPhotosResponse,
)

logger = logging.getLogger("biker.searcher")

SEARCH_PATHS = {
    "olx": "/v1/search/olx",
    "decathlon": "/v1/search/decathlon",
    "allegro": "/v1/search/allegro",
    "photos": "/v1/search/photos",
    "review": "/v1/search/review",
    "details": "/v1/search/details",
    "equipment_details": "/v1/search/equipment/details",
    "equipment_photos": "/v1/search/equipment/photos",
}
_SOURCE_BY_PATH = {path: source for source, path in SEARCH_PATHS.items()}  # for log lines
DEFAULT_TIMEOUT = 600.0  # one CLI search + photo scraping can take minutes
CONNECT_TIMEOUT = 10.0   # an unreachable searcher should fail fast, not after 600 s
DEFAULT_MAX_INFLIGHT = 10  # must not exceed the searcher's capacity (SEARCHER_MAX_CONCURRENT / --max-instances, also 10)
DETAIL_MAX_LEN = 300     # the searcher's error text is relayed to the browser — keep it short
BUSY_STATUSES = (503, 429)  # 503 = the searcher's own "slot taken"; 429 = Cloud Run "Rate exceeded" at max-instances

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class _SearcherPhotosResponse(BikePhotosResponse):
    """The searcher's photo body with `photos` REQUIRED.

    The public BikePhotosResponse defaults `photos` to [], so validating against
    it would turn `{}` or an offers-shaped body into "no photos found" — the UI
    would show a final "Nie znaleziono zdjęć" instead of a retryable 502.
    """

    photos: list[str]


class _SearcherReviewResponse(BaseModel):
    """The searcher's review body: {review: {...}, bike_id, saved}.

    `review` is required and nested — unlike the other routes the payload is not
    the top level — so search_review unwraps it; an offers- or photos-shaped
    body fails validation (502) instead of reading as "no review".
    """

    review: BikeReviewResponse


class _SearcherDetailsResponse(BaseModel):
    """The searcher's details body: {details: {...}, bike_id, saved} (TODO-041).

    `details` is required and nested, so search_details unwraps it; a body of
    another route's shape fails validation (502) instead of reading as "no details".
    """

    details: BikeDetailsResponse


class _SearcherEquipmentDetailsResponse(BaseModel):
    """The searcher's equipment details body: {details: {...}, equipment_id, saved} (TODO-042).

    `details` is required and nested; its own `equipment_id` is kept (the
    frontend links the spec-tree element with it), the wrapper's fields are dropped.
    """

    details: EquipmentDetailsResponse


class _SearcherEquipmentPhotosResponse(BaseModel):
    """The searcher's equipment photos body: {photos, equipment_id, saved} (TODO-042), `photos` REQUIRED.

    Like _SearcherPhotosResponse: `{}` or a details-shaped body must be a
    retryable 502, not "no photos found".
    """

    photos: list[str]
    equipment_id: int | None = None


# Searches in progress, keyed on (path, normalised company, normalised model) —
# plus the normalised element name for the equipment routes. A second click for
# the same bike (or bike element) on the same source awaits the running search
# instead of starting one.
_inflight: dict[tuple[str, ...], asyncio.Task] = {}
_semaphore: asyncio.Semaphore | None = None


class SearcherError(Exception):
    """Base class — the route maps each subclass to its own HTTP status."""


class SearcherNotConfigured(SearcherError):
    """SEARCHER_URL / SEARCHER_API_KEY unset: no searcher wired up here (503)."""


class SearcherUnavailable(SearcherError):
    """The searcher could not be reached or did not answer in time (503)."""


class SearcherBusy(SearcherError):
    """SEARCHER_MAX_INFLIGHT other searches are running, or the searcher's URL answered 503 busy / 429 (503)."""


class SearcherLimitReached(SearcherError):
    """The searcher's CLI run was refused: the Claude subscription limit is used up (TODO-038).

    The searcher answers 400 {"detail": <the CLI's notice>} for this and only
    this (its validation errors are 422). The route relays it as a 400 with
    the same detail — the shape the Anthropic credit-balance 400 has.
    """

    def __init__(self, detail: str):
        super().__init__(f"searcher limit reached: {detail}")
        self.detail = detail


class SearcherFailed(SearcherError):
    """The searcher answered, but not with a usable 200 (502, detail passed through)."""

    def __init__(self, status: int, detail: str):
        super().__init__(f"searcher returned HTTP {status}: {detail}")
        self.status = status
        self.detail = detail


def _env_number(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid %s=%r — using %s", name, raw, default)
        return default


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(max(1, int(_env_number("SEARCHER_MAX_INFLIGHT", DEFAULT_MAX_INFLIGHT))))
    return _semaphore


def _error_detail(resp: httpx.Response, source: str) -> str:
    """The searcher's {"detail": ...} when it sent one, else just the status.

    A non-JSON body is not the searcher talking — it is Cloud Run's HTML 403
    when the service is not public, a load balancer page, … — so relaying it
    to the browser only leaks noise; the body goes to the log instead.
    """
    try:
        detail = resp.json().get("detail")
        if detail:
            return str(detail)[:DETAIL_MAX_LEN]
    except (ValueError, AttributeError):
        pass
    logger.error(
        "searcher %s non-JSON error body | status=%d body=%r", source, resp.status_code, resp.text[:DETAIL_MAX_LEN],
    )
    return f"searcher answered HTTP {resp.status_code}"


async def _post_search(path: str, body: dict, response_model: type[ResponseT]) -> ResponseT:
    """One real round trip to the searcher — see _search for the guards around it.

    `body` is the JSON sent: {company, model} for the bike routes,
    {bike_company, bike_model, element_name, category?} for the equipment ones.
    """
    source = _SOURCE_BY_PATH.get(path, path)
    base = os.getenv("SEARCHER_URL", "").strip().rstrip("/")
    if not base:
        raise SearcherNotConfigured("SEARCHER_URL is not set")
    key = os.getenv("SEARCHER_API_KEY", "").strip()
    if not key:
        raise SearcherNotConfigured("SEARCHER_API_KEY is not set")
    url = f"{base}{path}"
    timeout = httpx.Timeout(_env_number("SEARCHER_TIMEOUT", DEFAULT_TIMEOUT), connect=CONNECT_TIMEOUT)

    logger.info("searcher %s request | url=%s body=%r", source, url, body)
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url, json=body, headers={"X-Searcher-Key": key},
            )
    except httpx.TimeoutException as exc:
        elapsed = time.perf_counter() - t0
        logger.error("searcher %s timed out | url=%s elapsed=%.2fs", source, url, elapsed)
        raise SearcherUnavailable(f"searcher timed out after {elapsed:.0f} s") from exc
    except httpx.HTTPError as exc:  # ConnectError, network errors, protocol errors
        logger.error("searcher %s unreachable | url=%s error=%s", source, url, exc)
        raise SearcherUnavailable(f"searcher unreachable: {exc}") from exc
    elapsed = time.perf_counter() - t0

    if resp.status_code in BUSY_STATUSES:
        # The searcher refuses rather than queues when its slots are taken (503);
        # Cloud Run does the same in front of it with 429 once every instance is
        # at --concurrency and --max-instances is reached. Both mean "try later".
        logger.warning(
            "searcher %s busy | status=%d detail=%r elapsed=%.2fs",
            source, resp.status_code, _error_detail(resp, source), elapsed,
        )
        raise SearcherBusy(f"searcher busy (HTTP {resp.status_code})")
    if resp.status_code == 400:
        detail = _error_detail(resp, source)
        logger.error("searcher %s limit reached | detail=%r elapsed=%.2fs", source, detail, elapsed)
        raise SearcherLimitReached(detail)
    if resp.status_code != 200:
        detail = _error_detail(resp, source)
        logger.error(
            "searcher %s failed | status=%d detail=%r elapsed=%.2fs", source, resp.status_code, detail, elapsed,
        )
        raise SearcherFailed(resp.status_code, detail)

    try:
        data = resp.json()
        result = response_model.model_validate(data)  # bike_id / equipment_id / saved are ignored
    except Exception as exc:  # noqa: BLE001 — malformed body from the searcher
        logger.error("searcher %s returned a malformed body | error=%s body=%r", source, exc, resp.text[:300])
        # A pydantic ValidationError lists every failing field with input fragments —
        # kilobytes; the browser gets the fixed summary, the log has the full error.
        raise SearcherFailed(502, "searcher returned a malformed response") from exc

    # Offer routes carry `offers`, the photo route `photos`, the review route `review.ref` — log whichever it is.
    items = getattr(result, "offers", None)
    if items is None:
        items = getattr(result, "photos", None)
    if items is None:
        review = getattr(result, "review", None)
        details = getattr(result, "details", None)
        if review is not None:
            items = review.ref
        elif details is not None:
            items = details.components
        else:
            items = []
    wrapper = data if isinstance(data, dict) else {}
    logger.info(
        "searcher %s done | body=%r items=%d bike_id=%s equipment_id=%s saved=%s elapsed=%.2fs",
        source, body, len(items), wrapper.get("bike_id"), wrapper.get("equipment_id"), wrapper.get("saved"), elapsed,
    )
    return result


async def _guarded_search(
    key: tuple[str, ...], path: str, body: dict, response_model: type[ResponseT],
) -> ResponseT:
    sem = _get_semaphore()
    if sem.locked():
        logger.warning("searcher %s refused: max in-flight searches reached | key=%s", _SOURCE_BY_PATH.get(path, path), key)
        raise SearcherBusy("too many searches running")
    async with sem:
        return await _post_search(path, body, response_model)


async def _search(path: str, company: str, model: str, response_model: type[ResponseT]) -> ResponseT:
    """Run (or join) the search for one bike on one source and return its result.

    Raises SearcherNotConfigured / SearcherUnavailable / SearcherBusy /
    SearcherLimitReached / SearcherFailed (a joined caller gets the same one); never returns a partial result. The searcher's extra
    `bike_id` / `saved` fields are dropped — the backend's contract is the
    plain {offers, info} (or {photos}, or {review}) model. The underlying task is shielded, so a caller
    that disconnects mid-search does not cancel it for the others (or waste
    the CLI run already paid for).
    """
    key = (path, company.strip().lower(), model.strip().lower())
    return await _single_flight(key, path, {"company": company, "model": model}, response_model)


async def _single_flight(
    key: tuple[str, ...], path: str, body: dict, response_model: type[ResponseT],
) -> ResponseT:
    """Start the search for `key`, or join the one already running — see _search."""
    task = _inflight.get(key)
    if task is None:
        task = asyncio.create_task(_guarded_search(key, path, body, response_model))
        _inflight[key] = task
        task.add_done_callback(lambda _t: _inflight.pop(key, None))
    else:
        logger.info("searcher %s joined in-flight search | key=%s", _SOURCE_BY_PATH.get(path, path), key)
    return await asyncio.shield(task)


async def search_olx(company: str, model: str) -> UsedBikeResponse:
    """Run (or join) the OLX search for one bike (TODO-031) — see _search."""
    return await _search(SEARCH_PATHS["olx"], company, model, UsedBikeResponse)


async def search_decathlon(company: str, model: str) -> BikeOfferResponse:
    """Run (or join) the Decathlon search for one bike (TODO-032) — see _search."""
    return await _search(SEARCH_PATHS["decathlon"], company, model, BikeOfferResponse)


async def search_allegro(company: str, model: str) -> BikeOfferResponse:
    """Run (or join) the Allegro search for one bike (TODO-033) — see _search."""
    return await _search(SEARCH_PATHS["allegro"], company, model, BikeOfferResponse)


async def search_photos(company: str, model: str) -> BikePhotosResponse:
    """Run (or join) the manufacturer-page photo search for one bike — see _search."""
    return await _search(SEARCH_PATHS["photos"], company, model, _SearcherPhotosResponse)


async def search_review(company: str, model: str) -> BikeReviewResponse:
    """Run (or join) the expert-review search for one bike (TODO-037) — see _search.

    Returns the review the searcher now has stored for the bike (the empty
    review when it found nothing usable); the wrapper's bike_id / saved are dropped.
    """
    result = await _search(SEARCH_PATHS["review"], company, model, _SearcherReviewResponse)
    return result.review


async def search_details(company: str, model: str) -> BikeDetailsResponse:
    """Run (or join) the bike-details search for one bike (TODO-041) — see _search.

    Returns the details the searcher now has stored for the bike (the empty
    response when it found nothing usable); the wrapper's bike_id / saved are dropped.
    """
    result = await _search(SEARCH_PATHS["details"], company, model, _SearcherDetailsResponse)
    return result.details


def _equipment_body(bike_company: str, bike_model: str, element_name: str, category: str | None) -> dict:
    body = {"bike_company": bike_company, "bike_model": bike_model, "element_name": element_name}
    if category:
        body["category"] = category
    return body


def _equipment_key(path: str, bike_company: str, bike_model: str, element_name: str) -> tuple[str, ...]:
    """Single-flight key: the category is not part of it — the searcher infers it when absent."""
    return (path, bike_company.strip().lower(), bike_model.strip().lower(), element_name.strip().lower())


async def search_equipment_details(
    bike_company: str, bike_model: str, element_name: str, category: str | None = None,
) -> EquipmentDetailsResponse:
    """Run (or join) the details search for one element of a bike's spec tree (TODO-042) — see _search.

    Returns the details the searcher now has stored for that equipment (the
    empty response when it found nothing usable), `details.equipment_id`
    included; the wrapper's equipment_id / saved are dropped.
    """
    path = SEARCH_PATHS["equipment_details"]
    result = await _single_flight(
        _equipment_key(path, bike_company, bike_model, element_name), path,
        _equipment_body(bike_company, bike_model, element_name, category), _SearcherEquipmentDetailsResponse,
    )
    return result.details


async def search_equipment_photos(
    bike_company: str, bike_model: str, element_name: str, category: str | None = None,
) -> EquipmentPhotosResponse:
    """Run (or join) the photo search for one element of a bike's spec tree (TODO-042) — see _search.

    Returns {photos, equipment_id} as the searcher now has them stored; `saved` is dropped.
    """
    path = SEARCH_PATHS["equipment_photos"]
    result = await _single_flight(
        _equipment_key(path, bike_company, bike_model, element_name), path,
        _equipment_body(bike_company, bike_model, element_name, category), _SearcherEquipmentPhotosResponse,
    )
    return EquipmentPhotosResponse(photos=result.photos, equipment_id=result.equipment_id)
