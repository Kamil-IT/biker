"""Unit tests for TODO-038: a searcher 400 (its `claude -p` hit the Claude
subscription limit) becomes SearcherLimitReached in app/searcher_client.py and
a 400 {"detail": <the searcher's detail>} from every /v1/bike/*/search route —
the shape the Anthropic credit-balance 400 has. httpx is replaced by a
MockTransport and the DB reads are monkeypatched, so no network, no DB and no
paid searcher run.
Run: cd backend && pytest   (collected via pytest.ini)"""
import asyncio
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import main  # noqa: E402
from app import searcher_client as sc  # noqa: E402
from app.schemas import BikeReviewResponse  # noqa: E402

_REAL_ASYNC_CLIENT = httpx.AsyncClient

LIMIT = "You've hit your session limit · resets 1am (Europe/Warsaw)"
BIKE = {"company": "Rockrider", "model": "ST 100"}  # a Decathlon house brand, so that route calls the searcher too


@pytest.fixture
def searcher(monkeypatch):
    """A fake searcher: `searcher.reply` builds the response, `searcher.calls` records the requests."""

    class _Fake:
        def __init__(self):
            self.calls: list[httpx.Request] = []
            self.reply = lambda req: httpx.Response(400, json={"detail": LIMIT})

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


def test_searcher_400_is_limit_reached_with_its_detail(searcher):
    with pytest.raises(sc.SearcherLimitReached) as info:
        asyncio.run(sc.search_review("Trek", "Marlin 5"))
    assert info.value.detail == LIMIT
    assert not isinstance(info.value, (sc.SearcherBusy, sc.SearcherFailed)), "a limit is neither busy nor failed"


def test_other_statuses_keep_their_mapping(searcher):
    searcher.reply = lambda req: httpx.Response(502, json={"detail": "claude CLI failed: exit 1"})
    with pytest.raises(sc.SearcherFailed):
        asyncio.run(sc.search_olx("Trek", "Marlin 5"))
    searcher.reply = lambda req: httpx.Response(503, json={"detail": "searcher busy"})
    with pytest.raises(sc.SearcherBusy):
        asyncio.run(sc.search_olx("Trek", "Marlin 5"))


def test_joined_waiter_gets_the_same_limit_error(searcher):
    async def both():
        return await asyncio.gather(
            sc.search_allegro("Trek", "Marlin 5"), sc.search_allegro(" trek", "MARLIN 5 "), return_exceptions=True,
        )

    first, second = asyncio.run(both())
    assert len(searcher.calls) == 1, "the second click must join the running search"
    assert isinstance(first, sc.SearcherLimitReached) and first is second


@pytest.fixture
def client(searcher, monkeypatch):
    monkeypatch.setattr(main, "bike_exists", lambda company, model: True)
    monkeypatch.setattr(main, "get_review", lambda company, model: BikeReviewResponse(
        score=0, explanation="", ref=[], rating=0.0, sources_used=0,
    ))
    return TestClient(main.app)   # no `with`: the lifespan (DB init) is not run


@pytest.mark.parametrize("path", [
    "/v1/bike/review/search",
    "/v1/bike/used/search",
    "/v1/bike/decathlon/search",
    "/v1/bike/allegro/search",
    "/v1/bike/photos/search",
])
def test_search_routes_answer_400_with_the_searcher_detail(client, searcher, path):
    resp = client.post(path, json=BIKE)
    assert resp.status_code == 400
    assert resp.json() == {"detail": LIMIT}, "same shape as the Anthropic credit-balance 400"
    assert len(searcher.calls) == 1
