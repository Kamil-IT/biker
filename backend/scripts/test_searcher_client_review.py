"""Unit tests for app/searcher_client.py search_review (TODO-037): the request it
sends, the guards around it (single-flight, busy mapping, shared in-flight cap),
the unwrapping of the searcher's {review, bike_id, saved} body and the error
mapping. httpx is replaced by a MockTransport, so no network, no DB and no paid
searcher run.
Run: cd backend && pytest   (collected via pytest.ini)"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import searcher_client as sc  # noqa: E402

_REAL_ASYNC_CLIENT = httpx.AsyncClient

REVIEW = {
    "score": 8,
    "explanation": "Solidny rower.",
    "ref": ["https://www.bikeradar.com/r/1", "https://www.reddit.com/r/2"],
    "rating": 7.9,
    "sources_used": 2,
}
EMPTY = {"score": 0, "explanation": "", "ref": [], "rating": 0.0, "sources_used": 0}


@pytest.fixture
def searcher(monkeypatch):
    """A fake searcher: `searcher.reply` builds the response, `searcher.calls` records the requests."""

    class _Fake:
        def __init__(self):
            self.calls: list[httpx.Request] = []
            self.reply = lambda req: httpx.Response(200, json={"review": EMPTY, "bike_id": 1, "saved": 0})

        async def handle(self, req: httpx.Request) -> httpx.Response:
            self.calls.append(req)
            await asyncio.sleep(0.05)   # long enough for a second identical call to join
            return self.reply(req)

    fake = _Fake()
    monkeypatch.setenv("SEARCHER_URL", "http://fake-searcher/")
    monkeypatch.setenv("SEARCHER_API_KEY", "secret-key")
    monkeypatch.delenv("SEARCHER_MAX_INFLIGHT", raising=False)
    monkeypatch.setattr(sc, "_semaphore", None)   # rebuilt per test, inside that test's event loop
    monkeypatch.setattr(sc, "_inflight", {})
    monkeypatch.setattr(
        sc.httpx, "AsyncClient",
        lambda **kw: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(fake.handle), **kw),
    )
    return fake


def test_posts_to_review_path_and_unwraps_review(searcher):
    searcher.reply = lambda req: httpx.Response(200, json={"review": REVIEW, "bike_id": 7, "saved": 1})
    result = asyncio.run(sc.search_review("Trek", "Marlin 5"))
    assert result.model_dump() == REVIEW, "the nested review is returned; bike_id / saved are dropped"
    (req,) = searcher.calls
    assert req.method == "POST" and str(req.url) == "http://fake-searcher/v1/search/review"
    assert req.headers["X-Searcher-Key"] == "secret-key"
    assert json.loads(req.content) == {"company": "Trek", "model": "Marlin 5"}


def test_empty_review_is_a_valid_result(searcher):
    assert asyncio.run(sc.search_review("Trek", "Marlin 5")).model_dump() == EMPTY


def test_identical_concurrent_calls_share_one_request(searcher):
    async def both():
        return await asyncio.gather(sc.search_review("Trek", "Marlin 5"), sc.search_review(" trek", "MARLIN 5 "))

    first, second = asyncio.run(both())
    assert len(searcher.calls) == 1, "the second click must join the running search"
    assert first == second


def test_review_and_photos_for_same_bike_are_separate_searches(searcher):
    searcher.reply = lambda req: httpx.Response(
        200, json={"review": EMPTY} if req.url.path.endswith("/review") else {"photos": []},
    )

    async def both():
        return await asyncio.gather(sc.search_review("Trek", "Marlin 5"), sc.search_photos("Trek", "Marlin 5"))

    asyncio.run(both())
    assert sorted(r.url.path for r in searcher.calls) == ["/v1/search/photos", "/v1/search/review"]


@pytest.mark.parametrize("status", [429, 503])
def test_busy_statuses_raise_searcher_busy(searcher, status):
    searcher.reply = lambda req: httpx.Response(status, json={"detail": "searcher busy"})
    with pytest.raises(sc.SearcherBusy):
        asyncio.run(sc.search_review("Trek", "Marlin 5"))


def test_inflight_cap_is_shared_with_other_sources(searcher, monkeypatch):
    monkeypatch.setenv("SEARCHER_MAX_INFLIGHT", "1")
    searcher.reply = lambda req: httpx.Response(
        200, json={"review": EMPTY} if req.url.path.endswith("/review") else {"offers": [], "info": ""},
    )

    async def both():
        return await asyncio.gather(
            sc.search_allegro("Trek", "Marlin 5"), sc.search_review("Trek", "Marlin 5"), return_exceptions=True,
        )

    allegro, review = asyncio.run(both())
    assert not isinstance(allegro, Exception)
    assert isinstance(review, sc.SearcherBusy), "one process-wide cap across all sources"
    assert len(searcher.calls) == 1


def test_searcher_error_passes_detail_through(searcher):
    searcher.reply = lambda req: httpx.Response(502, json={"detail": "claude CLI failed: exit 1"})
    with pytest.raises(sc.SearcherFailed) as info:
        asyncio.run(sc.search_review("Trek", "Marlin 5"))
    assert info.value.status == 502 and info.value.detail == "claude CLI failed: exit 1"


@pytest.mark.parametrize("body", [
    {},
    {"score": 8, "explanation": "x", "ref": []},
    {"photos": []},
    {"review": {"explanation": "no score"}},
], ids=["empty-object", "flat-review", "photos-shaped", "review-missing-score"])
def test_malformed_review_bodies_fail(searcher, body):
    # `review` is required and nested: a flat or foreign body must be a retryable
    # 502, not an empty review that the UI would show as "Nie znaleziono recenzji".
    searcher.reply = lambda req: httpx.Response(200, json=body)
    with pytest.raises(sc.SearcherFailed) as info:
        asyncio.run(sc.search_review("Trek", "Marlin 5"))
    assert info.value.status == 502 and info.value.detail == "searcher returned a malformed response"


@pytest.mark.parametrize("unset", ["SEARCHER_URL", "SEARCHER_API_KEY"])
def test_not_configured(searcher, monkeypatch, unset):
    monkeypatch.delenv(unset)
    with pytest.raises(sc.SearcherNotConfigured):
        asyncio.run(sc.search_review("Trek", "Marlin 5"))
    assert searcher.calls == []


def test_unreachable_searcher_is_unavailable(searcher):
    def boom(req):
        raise httpx.ConnectError("connection refused", request=req)

    searcher.reply = boom
    with pytest.raises(sc.SearcherUnavailable):
        asyncio.run(sc.search_review("Trek", "Marlin 5"))
