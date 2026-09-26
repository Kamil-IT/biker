"""HTTP client for the on-demand OLX searcher service (TODO-031).

The searcher (top-level `searcher/`, port 8100 locally) runs the Claude Code CLI
once plus Playwright once per listing and writes what it finds into
bike_offer / bike_offer_photos. The backend only proxies the request, waits,
and hands back the searcher's {offers, info} — it never calls Claude for OLX.

Configuration (backend/.env):
  SEARCHER_URL           base URL, e.g. http://localhost:8100 — unset = not configured
  SEARCHER_API_KEY       shared secret sent as X-Searcher-Key — unset = not configured
  SEARCHER_TIMEOUT       seconds to wait for one search (default 600)
  SEARCHER_MAX_INFLIGHT  concurrent searches this backend lets through (default 1)

Every search is billed to the Claude subscription and takes minutes, so two
guards sit in front of the network call: identical (company, model) requests
share one in-flight search (single-flight), and at most SEARCHER_MAX_INFLIGHT
distinct searches run at once — the rest are refused straight away, as is a
request the searcher itself answers 503 (busy) to. Queueing instead would let
a search outlive SEARCHER_TIMEOUT and end in a second paid run.
"""
import asyncio
import logging
import os
import time

import httpx

from .schemas import UsedBikeResponse

logger = logging.getLogger("biker.searcher")

SEARCH_PATH = "/v1/search/olx"
DEFAULT_TIMEOUT = 600.0  # one CLI search + photo scraping can take minutes
CONNECT_TIMEOUT = 10.0   # an unreachable searcher should fail fast, not after 600 s
DEFAULT_MAX_INFLIGHT = 1  # must not exceed the searcher's SEARCHER_MAX_CONCURRENT (also 1)
DETAIL_MAX_LEN = 300     # the searcher's error text is relayed to the browser — keep it short

# Searches in progress, keyed on the normalised (company, model) — a second
# click for the same bike awaits the running search instead of starting one.
_inflight: dict[tuple[str, str], asyncio.Task] = {}
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


def _error_detail(resp: httpx.Response) -> str:
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
    logger.error("searcher olx non-JSON error body | status=%d body=%r", resp.status_code, resp.text[:DETAIL_MAX_LEN])
    return f"searcher answered HTTP {resp.status_code}"


async def _post_search(company: str, model: str) -> UsedBikeResponse:
    """One real round trip to the searcher — see search_olx for the guards around it."""
    base = os.getenv("SEARCHER_URL", "").strip().rstrip("/")
    if not base:
        raise SearcherNotConfigured("SEARCHER_URL is not set")
    key = os.getenv("SEARCHER_API_KEY", "").strip()
    if not key:
        raise SearcherNotConfigured("SEARCHER_API_KEY is not set")
    url = f"{base}{SEARCH_PATH}"
    timeout = httpx.Timeout(_env_number("SEARCHER_TIMEOUT", DEFAULT_TIMEOUT), connect=CONNECT_TIMEOUT)

    logger.info("searcher olx request | url=%s company=%r model=%r", url, company, model)
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                url, json={"company": company, "model": model}, headers={"X-Searcher-Key": key},
            )
    except httpx.TimeoutException as exc:
        elapsed = time.perf_counter() - t0
        logger.error("searcher olx timed out | url=%s elapsed=%.2fs", url, elapsed)
        raise SearcherUnavailable(f"searcher timed out after {elapsed:.0f} s") from exc
    except httpx.HTTPError as exc:  # ConnectError, network errors, protocol errors
        logger.error("searcher olx unreachable | url=%s error=%s", url, exc)
        raise SearcherUnavailable(f"searcher unreachable: {exc}") from exc
    elapsed = time.perf_counter() - t0

    if resp.status_code == 503:
        # The searcher refuses rather than queues when its one slot is taken.
        logger.warning("searcher olx busy | detail=%r elapsed=%.2fs", _error_detail(resp), elapsed)
        raise SearcherBusy("searcher busy")
    if resp.status_code != 200:
        detail = _error_detail(resp)
        logger.error(
            "searcher olx failed | status=%d detail=%r elapsed=%.2fs", resp.status_code, detail, elapsed,
        )
        raise SearcherFailed(resp.status_code, detail)

    try:
        data = resp.json()
        result = UsedBikeResponse.model_validate(data)  # bike_id / saved are ignored
    except Exception as exc:  # noqa: BLE001 — malformed body from the searcher
        logger.error("searcher olx returned a malformed body | error=%s body=%r", exc, resp.text[:300])
        raise SearcherFailed(502, f"searcher returned a malformed response: {exc}") from exc

    logger.info(
        "searcher olx done | company=%r model=%r offers=%d bike_id=%s saved=%s elapsed=%.2fs",
        company, model, len(result.offers),
        data.get("bike_id") if isinstance(data, dict) else None,
        data.get("saved") if isinstance(data, dict) else None,
        elapsed,
    )
    return result


async def _guarded_search(key: tuple[str, str], company: str, model: str) -> UsedBikeResponse:
    sem = _get_semaphore()
    if sem.locked():
        logger.warning("searcher olx refused: max in-flight searches reached | key=%s", key)
        raise SearcherBusy("too many OLX searches running")
    async with sem:
        return await _post_search(company, model)


async def search_olx(company: str, model: str) -> UsedBikeResponse:
    """Run (or join) the OLX search for one bike and return its offers.

    Raises SearcherNotConfigured / SearcherUnavailable / SearcherBusy /
    SearcherFailed; never returns a partial result. The searcher's extra
    `bike_id` / `saved` fields are dropped — the backend's contract is the
    plain UsedBikeResponse. The underlying task is shielded, so a caller that
    disconnects mid-search does not cancel it for the others (or waste the
    CLI run already paid for).
    """
    key = (company.strip().lower(), model.strip().lower())
    task = _inflight.get(key)
    if task is None:
        task = asyncio.create_task(_guarded_search(key, company, model))
        _inflight[key] = task
        task.add_done_callback(lambda _t: _inflight.pop(key, None))
    else:
        logger.info("searcher olx joined in-flight search | key=%s", key)
    return await asyncio.shield(task)
