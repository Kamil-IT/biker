"""Unit tests for TODO-046: equipment searches WITHOUT a bike — a catalogue part from the backend's parts
search, linked to no bike. The request contract (bike optional, both or neither), the prompt without bike
context, the saves that link nothing, and the init_db() check of the new equipment columns. Throwaway
SQLite, stubbed finders — no CLI run, no network.

Run:
    cd searcher
    python -m pytest scripts/test_equipment_catalogue.py -v
"""
import asyncio

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from app import config, models
from app import main as searcher_main
from app.details_finder import build_details
from app.equipment_details_finder import build_equipment_details, is_named_after_bike, user_message
from app.equipment_photos_finder import user_message as photos_user_message
from app.equipment_repository import save_equipment_details, save_equipment_photos
from app.repository import save_details
from app.schemas import EquipmentSearchRequest

KEY = {"X-Searcher-Key": "secret-key"}
PART = "Shimano Deore CS-M6100-12"
BODY = {"element_name": PART, "category": "parts", "element_type": "Cassette"}


def _data():
    return {
        "found": True, "description": "Kaseta 12-rzędowa. Zakres 10-51T. Bębenek Micro Spline. Do MTB.",
        "short_description": "Kaseta MTB. Zakres 10-51T.", "sources": [], "company": "Shimano",
        "model": "Deore CS-M6100-12",
        "components": [{"category": "Bike parts & components", "subcategories": [{"subcategory": "Drivetrain",
                        "elements": [{"name": "CS-M6100-12", "description": "", "specs": [{"key": "Speeds", "value": "12"}]}]}]}],
    }


# ── request contract ──────────────────────────────────────────────────────

def test_request_bike_is_optional_both_or_neither():
    req = EquipmentSearchRequest(**BODY)
    assert (req.bike_company, req.bike_model, req.has_bike) == ("", "", False)
    assert EquipmentSearchRequest(**BODY, bike_company=" Canyon ", bike_model="Grizl").has_bike
    for half in ({"bike_company": "Canyon"}, {"bike_model": "Grizl"}, {"bike_company": "Canyon", "bike_model": "  "}):
        with pytest.raises(ValidationError, match="both bike_company and bike_model"):
            EquipmentSearchRequest(**BODY, **half)
    with pytest.raises(ValidationError):
        EquipmentSearchRequest(element_name="  ")


# ── prompt ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("build", [user_message, photos_user_message])
def test_message_without_a_bike(build):
    m = build("", "", PART, "parts", "Cassette")
    assert f'"{PART}"' in m and '(part type: "Cassette")' in m and "parts catalogue" in m
    assert "spec sheet —" in m and "bicycle's spec sheet" not in m and "bike only as context" not in m
    assert "identify the exact product by its name" in m
    assert '"  "' not in build("", "", PART, "parts", None) and "part type" not in build("", "", PART, "parts", None)


def test_details_message_without_a_bike_asks_for_found_true():
    assert "answer found: true" in user_message("", "", PART, "parts", "Cassette")


def test_message_with_a_bike_is_unchanged():
    m = user_message("Canyon", "Grizl", PART, "parts", "Cassette")
    assert '"Canyon Grizl" bicycle\'s spec sheet' in m and 'listed under "Cassette"' in m


def test_not_named_after_a_missing_bike():
    assert is_named_after_bike("", "", PART) is False
    assert is_named_after_bike("", "", "") is False


# ── saves (throwaway SQLite) ──────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    models.dispose_engine()
    models.Base.metadata.create_all(models.get_engine())
    yield
    models.dispose_engine()


def _q(sql: str, **params):
    with models.get_engine().connect() as conn:
        return conn.execute(text(sql), params).all()


def _catalogue_row() -> int:
    """The row the backend's AI parts search stores: category 'parts', researched company / model, no details."""
    with models.get_engine().begin() as conn:
        conn.execute(text(
            "INSERT INTO equipment (category, name, name_norm, company, company_norm, model, model_norm, "
            "short_description, part_type, groupset, key_specs) VALUES ('parts', :n, :nn, 'Shimano', 'shimano', "
            "'Deore CS-M6100-12', 'deore cs-m6100-12', '', 'cassette', 'Deore', '[\"12 rz.\"]')"),
            {"n": PART, "nn": PART.lower()})
    return _q("SELECT id FROM equipment")[0][0]


def _bike_with_element(element=PART) -> int:
    data = {"found": True, "description": "Rower.", "short_description": "Rower.", "sources": [],
            "components": [{"category": "Drivetrain", "subcategories": [{"subcategory": "Cassette", "elements": [
                {"name": element, "description": "", "specs": []}]}]}]}
    bike_id, saved = save_details("Kross", "Esker", build_details("Kross", "Esker", data))
    assert saved
    return bike_id


def test_details_save_without_a_bike_fills_the_catalogue_row_and_links_nothing(db):
    eid = _catalogue_row()
    bike = _bike_with_element()  # a bike with an element of the same name must NOT get linked
    got, saved = save_equipment_details("", "", PART, "parts", build_equipment_details(PART, "parts", _data()))
    assert (got, saved) == (eid, True)
    row = _q("SELECT company, model, description IS NOT NULL, part_type, groupset, key_specs FROM equipment")
    assert row == [("Shimano", "Deore CS-M6100-12", 1, "cassette", "Deore", '["12 rz."]')], "catalogue columns kept"
    assert _q("SELECT COUNT(*) FROM equipment_component WHERE equipment_id = :e", e=eid)[0][0] == 1
    assert _q("SELECT equipment_id FROM bike_component WHERE bike_id = :b", b=bike) == [(None,)]


def test_photos_save_without_a_bike_answers_the_id(db):
    eid = _catalogue_row()
    assert save_equipment_photos("", "", PART, "parts", ["https://a/1.jpg"]) == (eid, ["https://a/1.jpg"], 1)
    assert save_equipment_photos("", "", PART, "parts", ["https://b/2.jpg"]) == (eid, ["https://a/1.jpg"], 0), \
        "never replaced; the id is answered even though nothing was written or linked"


def test_init_db_refuses_without_the_catalogue_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'old.db'}")
    monkeypatch.delenv("SEARCHER_CREATE_TABLES", raising=False)
    models.dispose_engine()
    try:
        engine = models.get_engine()
        models.Base.metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE equipment DROP COLUMN key_specs"))
        with pytest.raises(RuntimeError, match="migrate_equipment_part_search.py"):
            models.init_db()
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE equipment ADD COLUMN key_specs TEXT"))
        models.init_db()  # migrated -> starts
    finally:
        models.dispose_engine()


# ── routes (stubbed finders) ──────────────────────────────────────────────

@pytest.fixture()
def client(db, monkeypatch):
    monkeypatch.setattr(config, "SEARCHER_API_KEY", "secret-key")
    monkeypatch.setattr(searcher_main, "_semaphore", asyncio.Semaphore(2))
    return TestClient(searcher_main.app)


def test_routes_without_a_bike(client, monkeypatch):
    eid = _catalogue_row()
    seen = []

    async def details(bike_company, bike_model, element_name, category, element_type=None):
        seen.append((bike_company, bike_model, element_name, category, element_type))
        return "parts", build_equipment_details(element_name, "parts", _data())

    async def photos(bike_company, bike_model, element_name, category, element_type=None):
        seen.append((bike_company, bike_model, element_name, category, element_type))
        return "parts", ["https://a/1.jpg"], "https://bike.shimano.com/x"

    monkeypatch.setattr(searcher_main, "find_equipment_details", details)
    monkeypatch.setattr(searcher_main, "find_equipment_photos", photos)
    r = client.post("/v1/search/equipment/details", json=BODY, headers=KEY)
    assert r.status_code == 200, r.text
    assert r.json()["equipment_id"] == eid and r.json()["saved"] == 1
    r = client.post("/v1/search/equipment/photos", json=BODY, headers=KEY)
    assert r.status_code == 200 and r.json() == {"photos": ["https://a/1.jpg"], "equipment_id": eid, "saved": 1}
    assert seen == [("", "", PART, "parts", "Cassette")] * 2
    assert client.post("/v1/search/equipment/details", json={**BODY, "bike_company": "Canyon"},
                       headers=KEY).status_code == 422
