"""Unit tests for app/searcher_client.py search_photos: the request it sends, the
guards around it (single-flight, busy mapping, in-flight cap) and the validation of
the searcher's photo body. httpx is replaced by a MockTransport, so no network, no
DB and no paid searcher run.
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


@pytest.fixture
def searcher(monkeypatch):
    """A fake searcher: `searcher.reply` builds the response, `searcher.calls` records the requests."""

    class _Fake:
        def __init__(self):
            self.calls: list[httpx.Request] = []
            self.reply = lambda req: httpx.Response(200, json={"photos": [], "bike_id": 1, "saved": 0})

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


def test_posts_to_photos_path_with_key(searcher):
    searcher.reply = lambda req: httpx.Response(200, json={"photos": ["https://a/1.jpg"], "bike_id": 7, "saved": 1})
    result = asyncio.run(sc.search_photos("Romet", "Aspre"))
    assert result.photos == ["https://a/1.jpg"]
    assert result.model_dump() == {"photos": ["https://a/1.jpg"]}, "bike_id / saved must be dropped"
    (req,) = searcher.calls
    assert req.method == "POST" and str(req.url) == "http://fake-searcher/v1/search/photos"
    assert req.headers["X-Searcher-Key"] == "secret-key"
    assert json.loads(req.content) == {"company": "Romet", "model": "Aspre"}


def test_identical_concurrent_calls_share_one_request(searcher):
    async def both():
        return await asyncio.gather(sc.search_photos("Romet", "Aspre"), sc.search_photos(" romet", "ASPRE "))

    first, second = asyncio.run(both())
    assert len(searcher.calls) == 1, "the second click must join the running search"
    assert first == second


@pytest.mark.parametrize("status", [429, 503])
def test_busy_statuses_raise_searcher_busy(searcher, status):
    searcher.reply = lambda req: httpx.Response(status, json={"detail": "searcher busy"})
    with pytest.raises(sc.SearcherBusy):
        asyncio.run(sc.search_photos("Romet", "Aspre"))


def test_default_inflight_cap_is_ten(searcher):
    assert sc.DEFAULT_MAX_INFLIGHT == 10
    assert sc._get_semaphore()._value == 10


@pytest.mark.parametrize("body,expected", [
    ({"photos": [], "bike_id": 1, "saved": 0}, []),
    ({"photos": ["https://a/1.jpg", "https://a/2.jpg"], "bike_id": 1, "saved": 2}, ["https://a/1.jpg", "https://a/2.jpg"]),
], ids=["empty-list", "two-photos"])
def test_valid_photo_bodies(searcher, body, expected):
    searcher.reply = lambda req: httpx.Response(200, json=body)
    assert asyncio.run(sc.search_photos("Romet", "Aspre")).photos == expected


@pytest.mark.parametrize("body", [
    {},
    {"photos": "https://a/1.jpg"},
    {"offers": [], "info": ""},
], ids=["empty-object", "photos-not-a-list", "offers-shaped"])
def test_malformed_photo_bodies_fail(searcher, body):
    # `photos` is required on the searcher's body: a default [] here would read as
    # "no photos found" in the UI instead of a retryable failure.
    searcher.reply = lambda req: httpx.Response(200, json=body)
    with pytest.raises(sc.SearcherFailed) as info:
        asyncio.run(sc.search_photos("Romet", "Aspre"))
    assert info.value.status == 502 and info.value.detail == "searcher returned a malformed response"
