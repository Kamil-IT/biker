"""HTTP client for the on-demand searcher service (TODO-031 OLX, TODO-032 Decathlon).

The searcher (top-level `searcher/`, port 8100 locally) runs the Claude Code CLI
once per search — plus Playwright once per OLX listing — and writes what it
finds into bike_offer / bike_offer_photos. The backend only proxies the
request, waits, and hands back the searcher's {offers, info} — it never calls
Claude for OLX or Decathlon. One client, two sources: `search_olx` posts to
/v1/search/olx, `search_decathlon` to /v1/search/decathlon (see SEARCH_PATHS);
both responses have the same shape and are validated into the route's model.

Configuration (backend/.env):
  SEARCHER_URL           base URL, e.g. http://localhost:8100 — unset = not configured
  SEARCHER_API_KEY       shared secret sent as X-Searcher-Key — unset = not configured
  SEARCHER_TIMEOUT       seconds to wait for one search (default 600)
  SEARCHER_MAX_INFLIGHT  concurrent searches this backend lets through (default 1)

Every search is billed to the Claude subscription and takes minutes, so two
guards sit in front of the network call: identical (source, company, model)
requests share one in-flight search (single-flight), and at most
SEARCHER_MAX_INFLIGHT distinct searches run at once across BOTH sources — the
searcher has a single CLI slot, so the semaphore is one process-wide object,
not one per source — and the rest are refused straight away, as is a request
the searcher itself answers 503 (busy) to. Queueing instead would let a search
outlive SEARCHER_TIMEOUT and end in a second paid run.
"""
import asyncio
import logging
import os
import time
from typing import TypeVar

import httpx
from pydantic import BaseModel

from .schemas import BikeOfferResponse, UsedBikeResponse

logger = logging.getLogger("biker.searcher")

SEARCH_PATHS = {"olx": "/v1/search/olx", "decathlon": "/v1/search/decathlon"}
_SOURCE_BY_PATH = {path: source for source, path in SEARCH_PATHS.items()}  # for log lines
DEFAULT_TIMEOUT = 600.0  # one CLI search + photo scraping can take minutes
CONNECT_TIMEOUT = 10.0   # an unreachable searcher should fail fast, not after 600 s
DEFAULT_MAX_INFLIGHT = 1  # must not exceed the searcher's SEARCHER_MAX_CONCURRENT (also 1)
DETAIL_MAX_LEN = 300     # the searcher's error text is relayed to the browser — keep it short

ResponseT = TypeVar("ResponseT", bound=BaseModel)

# Searches in progress, keyed on (path, normalised company, normalised model) —
# a second click for the same bike on the same source awaits the running
# search instead of starting one.
_inflight: dict[tuple[str, str, str], asyncio.Task] = {}
_semaphore: asyncio.Semaphore | None = None


class SearcherError(Exception):
    """Base class — the route maps each subclass to its own HTTP status."""


class SearcherNotConfigured(SearcherError):
    """SEARCHER_URL / SEARCHER_API_KEY unset: no searcher wired up here (503)."""


class SearcherUnavailable(SearcherError):
    """The searcher could not be reached or did not answer in time (503)."""


class SearcherBusy(SearcherError):
    """SEARCHER_MAX_INFLIGHT other searches are running, or the searcher said 503 busy (503)."""


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


async def _post_search(path: str, company: str, model: str, response_model: type[ResponseT]) -> ResponseT:
    """One real round trip to the searcher — see _search for the guards around it."""
    source = _SOURCE_BY_PATH.get(path, path)
    base = os.getenv("SEARCHER_URL", "").strip().rstrip("/")
    if not base:
        raise SearcherNotConfigured("SEARCHER_URL is not set")
    key = os.getenv("SEARCHER_API_KEY", "").strip()
    if not key:
        raise SearcherNotConfigured("SEARCHER_API_KEY is not set")
    url = f"{base}{path}"
    timeout = httpx.Timeout(_env_number("SEARCHER_TIMEOUT", DEFAULT_TIMEOUT), connect=CONNECT_TIMEOUT)

    logger.info("searcher %s request | url=%s company=%r model=%r", source, url, company, model)
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url, json={"company": company, "model": model}, headers={"X-Searcher-Key": key},
            )
    except httpx.TimeoutException as exc:
        elapsed = time.perf_counter() - t0
        logger.error("searcher %s timed out | url=%s elapsed=%.2fs", source, url, elapsed)
        raise SearcherUnavailable(f"searcher timed out after {elapsed:.0f} s") from exc
    except httpx.HTTPError as exc:  # ConnectError, network errors, protocol errors
        logger.error("searcher %s unreachable | url=%s error=%s", source, url, exc)
        raise SearcherUnavailable(f"searcher unreachable: {exc}") from exc
    elapsed = time.perf_counter() - t0

    if resp.status_code == 503:
        # The searcher refuses rather than queues when its one slot is taken.
        logger.warning("searcher %s busy | detail=%r elapsed=%.2fs", source, _error_detail(resp, source), elapsed)
        raise SearcherBusy("searcher busy")
    if resp.status_code != 200:
        detail = _error_detail(resp, source)
        logger.error(
            "searcher %s failed | status=%d detail=%r elapsed=%.2fs", source, resp.status_code, detail, elapsed,
        )
        raise SearcherFailed(resp.status_code, detail)

    try:
        data = resp.json()
        result = response_model.model_validate(data)  # bike_id / saved are ignored
    except Exception as exc:  # noqa: BLE001 — malformed body from the searcher
        logger.error("searcher %s returned a malformed body | error=%s body=%r", source, exc, resp.text[:300])
        # A pydantic ValidationError lists every failing field with input fragments —
        # kilobytes; the browser gets the fixed summary, the log has the full error.
        raise SearcherFailed(502, "searcher returned a malformed response") from exc

    logger.info(
        "searcher %s done | company=%r model=%r offers=%d bike_id=%s saved=%s elapsed=%.2fs",
        source, company, model, len(result.offers),
        data.get("bike_id") if isinstance(data, dict) else None,
        data.get("saved") if isinstance(data, dict) else None,
        elapsed,
    )
    return result


async def _guarded_search(
    key: tuple[str, str, str], path: str, company: str, model: str, response_model: type[ResponseT],
) -> ResponseT:
    sem = _get_semaphore()
    if sem.locked():
        logger.warning("searcher %s refused: max in-flight searches reached | key=%s", _SOURCE_BY_PATH.get(path, path), key)
        raise SearcherBusy("too many searches running")
    async with sem:
        return await _post_search(path, company, model, response_model)


async def _search(path: str, company: str, model: str, response_model: type[ResponseT]) -> ResponseT:
    """Run (or join) the search for one bike on one source and return its offers.

    Raises SearcherNotConfigured / SearcherUnavailable / SearcherBusy /
    SearcherFailed; never returns a partial result. The searcher's extra
    `bike_id` / `saved` fields are dropped — the backend's contract is the
    plain {offers, info} model. The underlying task is shielded, so a caller
    that disconnects mid-search does not cancel it for the others (or waste
    the CLI run already paid for).
    """
    key = (path, company.strip().lower(), model.strip().lower())
    task = _inflight.get(key)
    if task is None:
        task = asyncio.create_task(_guarded_search(key, path, company, model, response_model))
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
