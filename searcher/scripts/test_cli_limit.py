"""Unit tests for TODO-038: a `claude -p` run refused because the Claude
subscription limit is used up raises ClaudeCliLimitError, and every CLI-backed
route answers 400 {"detail": <the CLI's notice>} for it instead of 502.

subprocess.run is replaced by a fake returning a canned CLI result and the DB
reads / finders are monkeypatched — no CLI run, no network, no database.

Run:
    cd searcher
    python -m pytest scripts/test_cli_limit.py -v
"""
import asyncio
import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from app import claude_cli, config
from app import main as searcher_main
from app.claude_cli import ClaudeCliError, ClaudeCliLimitError, limit_message, run_structured
from app.olx_finder import SearcherError, SearcherLimitError, searcher_error

LIMIT = "You've hit your session limit · resets 1am (Europe/Warsaw)"
LIMIT_RESULT = {
    "type": "result", "subtype": "success", "is_error": True, "api_error_status": 429,
    "result": LIMIT, "num_turns": 1, "usage": {},
}


def _fake_cli(monkeypatch, returncode: int, result: dict | None, stdout: str | None = None):
    monkeypatch.setattr(config, "claude_binary", lambda: "claude")

    def run(argv, **kw):
        out = stdout if stdout is not None else json.dumps(result)
        return subprocess.CompletedProcess(argv, returncode, stdout=out, stderr="")

    monkeypatch.setattr(claude_cli.subprocess, "run", run)


# --------------------------------------------------------------------------
# limit_message — the detection rule
# --------------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    LIMIT,
    "You've hit your weekly limit · resets Oct 3, 9am",
    "You’ve reached your usage limit",
    "Claude AI usage limit reached|1759000000",
    "5-hour limit reached ∙ resets 3pm",
])
def test_limit_wording_is_a_limit(text):
    assert limit_message({"is_error": True, "result": text}) == text


def test_429_without_the_wording_is_a_limit_with_a_fixed_message():
    assert limit_message({"is_error": True, "api_error_status": 429, "result": "API Error: 429"}) == \
        claude_cli.LIMIT_FALLBACK_MESSAGE


@pytest.mark.parametrize("data", [
    {"is_error": True, "api_error_status": 500, "result": "API Error: 500 Overloaded"},
    {"is_error": True, "api_error_status": 401, "result": "Invalid API key · Please run /login"},
    {"is_error": True, "result": "No listings found; the price limit in the query was too low"},
    {"is_error": False, "result": LIMIT},            # not an error result → not a limit
    {"subtype": "error_max_turns", "is_error": True},
    None,
])
def test_other_failures_are_not_a_limit(data):
    assert limit_message(data) is None


def test_message_is_collapsed_capped_and_redacted():
    text = "You've hit your session limit   \n resets 1am sk-ant-oat01-SECRET " + "x" * 400
    msg = limit_message({"is_error": True, "result": text})
    assert "\n" not in msg and "  " not in msg
    assert "sk-ant" not in msg and "SECRET" not in msg
    assert len(msg) <= claude_cli.LIMIT_MESSAGE_MAX_LEN


# --------------------------------------------------------------------------
# run_structured — the exception raised
# --------------------------------------------------------------------------


def test_limit_run_raises_limit_error(monkeypatch):
    _fake_cli(monkeypatch, 1, LIMIT_RESULT)
    with pytest.raises(ClaudeCliLimitError) as info:
        run_structured("sys", "msg", {"type": "object"})
    assert str(info.value) == LIMIT


def test_generic_failure_raises_plain_cli_error(monkeypatch):
    _fake_cli(monkeypatch, 1, {"type": "result", "subtype": "success", "is_error": True,
                               "api_error_status": 500, "result": "API Error: 500"})
    with pytest.raises(ClaudeCliError) as info:
        run_structured("sys", "msg", {"type": "object"})
    assert not isinstance(info.value, ClaudeCliLimitError)
    assert str(info.value) == "claude CLI failed: exit 1"


def test_non_json_failure_raises_plain_cli_error(monkeypatch):
    _fake_cli(monkeypatch, 1, None, stdout="Error: something broke")
    with pytest.raises(ClaudeCliError) as info:
        run_structured("sys", "msg", {"type": "object"})
    assert not isinstance(info.value, ClaudeCliLimitError)


def test_success_still_returns_structured_output(monkeypatch):
    _fake_cli(monkeypatch, 0, {"type": "result", "subtype": "success", "is_error": False,
                               "structured_output": {"offers": []}, "usage": {}})
    assert run_structured("sys", "msg", {"type": "object"}) == {"offers": []}


def test_searcher_error_keeps_the_limit_class():
    assert isinstance(searcher_error(ClaudeCliLimitError(LIMIT)), SearcherLimitError)
    plain = searcher_error(ClaudeCliError("claude CLI failed: exit 1"))
    assert type(plain) is SearcherError


# --------------------------------------------------------------------------
# routes — 400 {"detail": notice} for a limit, 502 for anything else
# --------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "SEARCHER_API_KEY", "secret-key")
    monkeypatch.setattr(searcher_main, "_semaphore", asyncio.Semaphore(10))
    monkeypatch.setattr(searcher_main, "_photo_searches", {})
    return TestClient(searcher_main.app)   # no `with`: the lifespan (DB, CLI version) is not run


def _fail_with(monkeypatch, exc: Exception):
    async def finder(*args, **kwargs):
        raise exc

    for name in ("find_used_bikes", "find_decathlon_offers", "find_allegro_offers",
                 "find_bike_photos", "find_bike_review", "find_bike_details",
                 "find_equipment_details", "find_equipment_photos"):
        monkeypatch.setattr(searcher_main, name, finder)


# No route reads the DB before its search, so none needs a stubbed repository here.
BIKE = {"company": "Trek", "model": "Marlin 5"}
EQUIPMENT = {"bike_company": "Trek", "bike_model": "Marlin 5", "element_name": "Bontrager Comp Lock"}
ROUTES = [("/v1/search/olx", BIKE), ("/v1/search/decathlon", BIKE), ("/v1/search/allegro", BIKE),
          ("/v1/search/photos", BIKE), ("/v1/search/review", BIKE), ("/v1/search/details", BIKE),
          ("/v1/search/equipment/details", EQUIPMENT), ("/v1/search/equipment/photos", EQUIPMENT)]


@pytest.mark.parametrize("path,body", ROUTES)
def test_limit_is_400_with_the_notice(client, monkeypatch, path, body):
    _fail_with(monkeypatch, SearcherLimitError(LIMIT))
    resp = client.post(path, json=body, headers={"X-Searcher-Key": "secret-key"})
    assert resp.status_code == 400
    assert resp.json() == {"detail": LIMIT}


@pytest.mark.parametrize("path,body", ROUTES)
def test_other_cli_failure_stays_502(client, monkeypatch, path, body):
    _fail_with(monkeypatch, SearcherError("claude CLI failed: exit 1"))
    resp = client.post(path, json=body, headers={"X-Searcher-Key": "secret-key"})
    assert resp.status_code == 502
    assert resp.json() == {"detail": "claude CLI failed: exit 1"}
