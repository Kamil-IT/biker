"""Unit tests for the search by category (SearchRequest.bike_type -> bike.category):
the mapping in app/bike_categories.py, the DB filter in repository.find_bikes_by_details,
the category stamp of store.save_search, the /v1/bike/search route with the AI finder
mocked, and the parser's bike_type (+ the v2 cache key of /v1/bike/parse) —
each on a fresh temp SQLite database, no server, no network, no AI call.
Run: cd backend && pytest   (collected via pytest.ini)"""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import bike_parser, main, models, repository, store  # noqa: E402
from app.bike_categories import (  # noqa: E402
    BIKE_CATEGORIES, LEGACY_CATEGORIES, POLISH_TO_CATEGORY, SEARCH_BIKE_TYPES, categories_for_search,
    category_for_ai_result, category_from_discovery, category_from_shop_path, search_type_from_parse,
)
from app.cache import set_cached  # noqa: E402
from app.schemas import BikeResult, ParseResponse, SearchRequest  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(tmp_path / "category.db")
    models.init_db()
    yield tmp_path / "category.db"
    models.dispose_engine()
    models._db_url = None


@pytest.fixture
def client(db):
    return TestClient(main.app)  # no `with`: the lifespan (init against the real DB) is not run


def _add(brand: str, model: str, category=None) -> int:
    with models.get_session() as s:
        bike = models.Bike(brand=brand, model=model, category=category)
        s.add(bike)
        s.commit()
        return bike.id


def _category(brand: str, model: str):
    with models.get_session() as s:
        return s.query(models.Bike.category).filter_by(brand=brand, model=model).scalar()


def _names(bikes) -> list[str]:
    return [b.model for b in bikes]


def _fail_ai(monkeypatch):
    async def boom(_query):
        raise AssertionError("the AI finder must not run on a DB hit")
    monkeypatch.setattr(main, "find_bikes", boom)


# ── bike_categories mapping ────────────────────────────────────────────────

CCH = "City/Cross/Hybrid"


def test_form_values_are_the_categories():
    assert SEARCH_BIKE_TYPES == BIKE_CATEGORIES == (
        "Road", "MTB", "Gravel", CCH, "Touring", "BMX", "Folding", "Kids")
    assert all(len(c) <= 32 for c in BIKE_CATEGORIES), "bike.category is VARCHAR(32)"
    assert set(LEGACY_CATEGORIES.values()) <= set(BIKE_CATEGORIES)
    assert set(POLISH_TO_CATEGORY.values()) <= set(BIKE_CATEGORIES)


@pytest.mark.parametrize("bike_type, expected", [
    ("Road", {"road", "triathlon"}), ("MTB", {"mtb", "dirt/street"}), ("Gravel", {"gravel", "cyclocross"}),
    ("BMX", {"bmx"}), ("Folding", {"folding"}), ("Kids", {"kids", "youth", "balance"}),
    (CCH, {"city/cross/hybrid", "city", "cross", "hybrid/commuter", "cruiser"}),
    ("Touring", {"touring", "trekking"}),
    ("touring", {"touring", "trekking"}),                        # an edited address: casing does not matter
    ("Hybrid/Commuter", {"city/cross/hybrid", "city", "cross", "hybrid/commuter", "cruiser"}),  # an old address
    ("Unknown thing", {"unknown thing"}),                        # matches nothing -> AI fallback
    ("Electric", {"electric"}),                                  # not a type any more
    (None, set()), ("", set()), ("  ", set()),
])
def test_categories_for_search(bike_type, expected):
    assert categories_for_search(bike_type) == expected


@pytest.mark.parametrize("bike_type, expected", [
    (CCH, CCH), ("Hybrid/Commuter", CCH), ("Touring", "Touring"), ("Trekking", "Touring"), ("MTB", "MTB"),
    ("road", "Road"), ("Cruiser", CCH), ("kids", "Kids"), ("Electric", None), ("Unknown thing", None),
    (None, None), ("", None),
])
def test_category_for_ai_result(bike_type, expected):
    assert category_for_ai_result(bike_type) == expected


@pytest.mark.parametrize("value, expected", [
    ("Road", "Road"), ("mtb", "MTB"), (" City/Cross/Hybrid ", CCH), ("Hybrid/Commuter", CCH),
    ("Trekking", "Touring"), ("Kids", "Kids"), ("Electric", None), ("", None), (None, None), (3, None),
])
def test_search_type_from_parse(value, expected):
    assert search_type_from_parse(value) == expected


@pytest.mark.parametrize("path, expected", [
    ("Rowery > Elektryczne > Trekkingowe", "Touring"),
    ("Rowery > Elektryczne > SUV", "Touring"),
    ("Rowery > Elektryczne > Miejskie", CCH),
    ("Rowery > Elektryczne > Crossowe", CCH),
    ("Rowery > Elektryczne > Cargo", CCH),
    ("Rowery > Elektryczne > Szosowe i gravelowe", "Gravel"),
    ("Rowery > Elektryczne > Górskie MTB > MTB Hardtail", "MTB"),
    ("Rowery > Elektryczne > Młodzieżowe", "Kids"),
    ('Rowery > Górskie MTB > MTB 29"', "MTB"),
    ("Rowery > Trekkingowe", "Touring"),
    ("Rowery > Triathlonowe i czasowe", "Road"),
    ("Rowery > Dirt/Street", "MTB"),
    ("Rowery > Biegowe > Jeździki", "Kids"),
    ("Rowery > Elektryczne", None), ("", None), (None, None),
])
def test_category_from_shop_path(path, expected):
    assert category_from_shop_path(path) == expected


def test_category_from_discovery_name_first_then_path():
    assert category_from_discovery("trekkingowy") == "Touring"
    assert category_from_discovery("Jeździk dziecięcy") == "Kids"
    assert category_from_discovery("elektryczny") is None, "an e-bike's name names no type"
    assert category_from_discovery("elektryczny", "Rowery > Elektryczne > Górskie MTB") == "MTB"
    assert category_from_discovery("szosowy", "Rowery > Elektryczne > Miejskie") == "Road", "the name wins"
    assert category_from_discovery("elektryczny cargo") == CCH


# ── repository.find_bikes_by_details ───────────────────────────────────────

@pytest.fixture
def bikes(db):
    _add("Kross", "Level", "MTB")
    _add("Kross", "Vento", "Road")
    _add("Kross", "Evado", CCH)
    _add("Kross", "Trans", "Touring")
    _add("Kross", "Unknown", None)
    _add("Kross", "Lea JR", "Kids")
    _add("Romet", "Rambler", "MTB")
    _add("Romet", "Gazela", CCH)


def test_category_only_search_reads_the_db(bikes):
    assert _names(repository.find_bikes_by_details(SearchRequest(bike_type="MTB"))) == ["Level", "Rambler"]
    assert _names(repository.find_bikes_by_details(SearchRequest(bike_type="Kids"))) == ["Lea JR"]


def test_category_search_by_code_and_old_value(bikes):
    found = repository.find_bikes_by_details(SearchRequest(bike_type=CCH))
    assert _names(found) == ["Evado", "Gazela"] and {b.category for b in found} == {CCH}
    assert _names(repository.find_bikes_by_details(SearchRequest(bike_type="Hybrid/Commuter"))) == ["Evado", "Gazela"]
    assert _names(repository.find_bikes_by_details(SearchRequest(bike_type="Touring"))) == ["Trans"]


def test_unknown_category_matches_nothing(bikes):
    assert repository.find_bikes_by_details(SearchRequest(bike_type="Electric")) == []


def test_old_values_are_refused_by_the_constraint(db):
    with pytest.raises(Exception):
        _add("Kross", "Old", "Trekking")


def test_category_is_anded_with_brand(bikes):
    assert _names(repository.find_bikes_by_details(SearchRequest(brand="kross", bike_type="MTB"))) == ["Level"]
    assert repository.find_bikes_by_details(SearchRequest(brand="Kross", bike_type="BMX")) == []


def test_null_category_never_matches_a_category(bikes):
    found = repository.find_bikes_by_details(SearchRequest(brand="Kross", model="Unknown", bike_type="MTB"))
    assert found == []


def test_without_category_null_bikes_are_still_found(bikes):
    assert "Unknown" in _names(repository.find_bikes_by_details(SearchRequest(brand="Kross")))


def test_year_and_free_text_alone_still_skip_the_db(bikes):
    assert repository.find_bikes_by_details(SearchRequest(year=2024, search="MTB")) == []


# ── store.save_search stamp ────────────────────────────────────────────────

def test_save_search_stamps_only_null_categories(db):
    _add("Trek", "FX 2", None)
    _add("Trek", "Marlin 5", "MTB")
    store.save_search("Type: City/Cross/Hybrid", [
        BikeResult(brand="trek", model="fx 2", accessories=[], explanation=""),
        BikeResult(brand="Trek", model="Marlin 5", accessories=[], explanation=""),
        BikeResult(brand="Trek", model="Dual Sport", accessories=[], explanation=""),
    ], bike_type=CCH)
    assert _category("Trek", "FX 2") == CCH, "an existing NULL category gets the stamp"
    assert _category("Trek", "Marlin 5") == "MTB", "a stored category is never overwritten"
    assert _category("Trek", "Dual Sport") == CCH, "a new bike gets the stamp"


def test_save_search_stamps_the_code_of_an_old_value(db):
    store.save_search("Type: Touring", [BikeResult(brand="Trek", model="520", accessories=[], explanation="")],
                      bike_type="Trekking")
    assert _category("Trek", "520") == "Touring"


def test_save_search_without_or_unknown_category_stamps_nothing(db):
    store.save_search("q", [BikeResult(brand="A", model="One", accessories=[], explanation="")])
    store.save_search("q", [BikeResult(brand="A", model="Two", accessories=[], explanation="")], bike_type="Nonsense")
    assert _category("A", "One") is None and _category("A", "Two") is None


# ── POST /v1/bike/search ───────────────────────────────────────────────────

def test_route_category_db_hit_makes_no_ai_call(client, bikes, monkeypatch):
    _fail_ai(monkeypatch)
    resp = client.post("/v1/bike/search", json={"bike_type": "Touring"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [(b["model"], b["category"]) for b in body["bikes"]] == [("Trans", "Touring")]
    assert body["search"] == "Type: Touring"


def test_route_category_miss_falls_back_to_ai_and_stamps(client, db, monkeypatch):
    _add("Haibike", "Old", None)
    seen = []

    async def fake_find_bikes(query):
        seen.append(query)
        return [
            BikeResult(brand="Haibike", model="Old", accessories=[], explanation=""),
            BikeResult(brand="Mongoose", model="Legion", accessories=[], explanation=""),
        ]
    monkeypatch.setattr(main, "find_bikes", fake_find_bikes)

    resp = client.post("/v1/bike/search", json={"bike_type": "BMX"})
    assert resp.status_code == 200, resp.text
    assert seen == ["Type: BMX"], "no BMX in the DB -> one AI call"
    assert [(b["model"], b["category"]) for b in resp.json()["bikes"]] == [("Old", "BMX"), ("Legion", "BMX")]

    _fail_ai(monkeypatch)
    again = client.post("/v1/bike/search", json={"bike_type": "BMX"})
    assert again.status_code == 200, again.text
    assert [b["model"] for b in again.json()["bikes"]] == ["Old", "Legion"], \
        "the stamped bikes are found in the DB next time (sorted by brand)"


# ── parser: bike_type + /v1/bike/parse cache key ───────────────────────────

class _FakeMessages:
    def __init__(self, text):
        self._text = text

    async def create(self, **_kwargs):
        return SimpleNamespace(content=[SimpleNamespace(text=self._text)])


def _parse_with(monkeypatch, payload: dict) -> ParseResponse:
    monkeypatch.setattr(bike_parser, "_client", SimpleNamespace(messages=_FakeMessages(json.dumps(payload))))
    return asyncio.run(bike_parser.parse_free_text("anything"))


def test_parser_keeps_a_form_bike_type(monkeypatch):
    parsed = _parse_with(monkeypatch, {"bike_type": "mtb", "brand": "Kross"})
    assert parsed.bike_type == "MTB" and parsed.brand == "Kross"


def test_parser_maps_an_old_value_and_drops_any_other(monkeypatch):
    assert _parse_with(monkeypatch, {"bike_type": "Trekking"}).bike_type == "Touring"
    parsed = _parse_with(monkeypatch, {"bike_type": "Electric"})
    assert parsed.bike_type is None and parsed.is_empty()


def test_parse_route_serves_a_cached_old_value_as_its_code(client, monkeypatch):
    text = "rower miejski"
    set_cached("/v1/bike/parse", {"text": text, "v": "2"}, ParseResponse(bike_type="Hybrid/Commuter"))

    async def must_not_run(_text):
        raise AssertionError("the cached row must be served")
    monkeypatch.setattr(main, "parse_free_text", must_not_run)
    resp = client.post("/v1/bike/parse", json={"text": text})
    assert resp.status_code == 200 and resp.json()["bike_type"] == CCH


def test_type_only_parse_is_not_empty():
    assert not ParseResponse(bike_type="Road").is_empty()


def test_parse_route_ignores_pre_v2_cache_rows(client, monkeypatch):
    text = "rower szosowy"
    # A row an older build stored under the old key: no bike_type in it.
    set_cached("/v1/bike/parse", {"text": text}, ParseResponse(wheel_size='28"'))

    async def fake_parse(_text):
        return ParseResponse(bike_type="Road")
    monkeypatch.setattr(main, "parse_free_text", fake_parse)

    resp = client.post("/v1/bike/parse", json={"text": text})
    assert resp.status_code == 200, resp.text
    assert resp.json()["bike_type"] == "Road" and resp.json()["wheel_size"] is None

    async def must_not_run(_text):
        raise AssertionError("the v2 row must be served from the cache")
    monkeypatch.setattr(main, "parse_free_text", must_not_run)
    assert client.post("/v1/bike/parse", json={"text": text}).json()["bike_type"] == "Road"
