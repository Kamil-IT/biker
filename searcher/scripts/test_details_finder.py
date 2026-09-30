"""Unit tests for the TODO-041 details search: parse/validation (details_finder.build_details) and the DB
logic (repository.save_details / get_stored_details) on a throwaway SQLite file. No CLI run, no network.

Run:
    cd searcher
    python -m pytest scripts/test_details_finder.py -v
"""
import pytest
from sqlalchemy import text

from app import config, models
from app.details_finder import (
    CATEGORIES,
    ELEMENT_NAME_MAX,
    build_details,
    empty_details,
    has_components,
    is_usable_details,
)
from app.repository import get_stored_details, save_details
from app.schemas import BikeDetails


def _data(**over):
    data = {
        "description": "Rower do jazdy po szutrze. Ma lekka rame.",
        "short_description": "Lekki gravel. Dobry na wyprawy.",
        "sources": [
            {"url": "https://example.com/bike", "title": "Example"},
            {"url": "https://example.com/bike", "title": "Dup"},
            {"url": "javascript:alert(1)", "title": "Bad"},
            {"url": "ftp://example.com/x", "title": "Bad"},
        ],
        "components": [
            {"category": "Frame", "subcategories": [
                {"subcategory": "Frame", "elements": [
                    {"name": "Carbon", "description": "Rama.", "specs": [{"key": "Material", "value": "Carbon"}]},
                    {"name": "", "description": "", "specs": []},
                ]},
                {"subcategory": "Fork", "elements": []},
            ]},
            {"category": "Brakes", "subcategories": [
                {"subcategory": "Brake Rotor", "elements": [
                    {"name": "Shimano RT-MT800", "description": "", "specs": []},
                ]},
            ]},
        ],
    }
    data.update(over)
    return data


# ── build_details ─────────────────────────────────────────────────────────

def test_shape_and_description_from_sources():
    d = build_details("Canyon", "Grizl", _data())
    assert d.company == "Canyon" and d.model == "Grizl"
    assert d.short_description == "Lekki gravel. Dobry na wyprawy."
    assert d.description.text.startswith("Rower do jazdy")
    assert [c.url for c in d.description.citations] == ["https://example.com/bike"]  # dup, js:, ftp: dropped
    assert d.description.citations[0].cited_text == ""
    assert len(d.description.segments) == 1
    assert d.description.segments[0].text == d.description.text
    assert d.description.segments[0].citations == d.description.citations
    dumped = d.model_dump()
    assert set(dumped) == {"company", "model", "description", "components", "short_description"}
    assert set(dumped["description"]) == {"text", "segments", "citations"}


def test_eight_category_shells_in_order_and_empty_subcategories_dropped():
    d = build_details("A", "B", _data())
    assert [c.category for c in d.components] == list(CATEGORIES)
    frame = d.components[0]
    assert [s.subcategory for s in frame.subcategories] == ["Frame"]  # empty Fork dropped
    assert [e.name for e in frame.subcategories[0].elements] == ["Carbon"]  # nameless element dropped
    assert d.components[6].subcategories == []  # Lighting stays an empty shell
    assert has_components(d)


def test_unknown_category_appended_and_repeat_merged():
    raw = _data(components=[
        {"category": "Frame", "subcategories": [{"subcategory": "Frame", "elements": [{"name": "X", "description": "", "specs": []}]}]},
        {"category": "Frame", "subcategories": [{"subcategory": "Fork", "elements": [{"name": "Y", "description": "", "specs": []}]}]},
        {"category": "Extras", "subcategories": [{"subcategory": "Bell", "elements": [{"name": "Z", "description": "", "specs": []}]}]},
    ])
    d = build_details("A", "B", raw)
    assert [c.category for c in d.components] == list(CATEGORIES) + ["Extras"]
    assert [s.subcategory for s in d.components[0].subcategories] == ["Frame", "Fork"]


def test_strings_capped_and_keyless_spec_dropped():
    raw = _data(components=[{"category": "Frame", "subcategories": [{"subcategory": "Frame", "elements": [
        {"name": "N" * 900, "description": "", "specs": [{"key": "", "value": "v"}, {"key": "k", "value": "v" * 5000}]},
    ]}]}])
    el = build_details("A", "B", raw).components[0].subcategories[0].elements[0]
    assert len(el.name) == ELEMENT_NAME_MAX
    assert len(el.specs) == 1 and len(el.specs[0].value) == 1024


@pytest.mark.parametrize("bad", [None, "x", [], 5])
def test_non_object_answer_is_empty(bad):
    d = build_details("A", "B", bad)
    assert not is_usable_details(d)
    assert d == empty_details("A", "B")


def test_malformed_members_do_not_raise():
    d = build_details("A", "B", {"description": 5, "short_description": None, "sources": "x", "components": [1, {"category": 3}]})
    assert d.description.text == "" and d.description.segments == [] and d.description.citations == []
    assert not is_usable_details(d)


def test_usable_needs_components_or_description():
    assert is_usable_details(build_details("A", "B", _data()))
    assert is_usable_details(build_details("A", "B", _data(components=[])))  # description only
    assert is_usable_details(build_details("A", "B", _data(description="", short_description="")))  # components only
    assert not is_usable_details(build_details("A", "B", _data(description="  ", components=[])))


def test_found_false_is_unusable_even_with_an_apology_text():
    d = build_details("A", "B", _data(found=False, description="Model B nie został znaleziony.", short_description="Nie ma."))
    assert not is_usable_details(d)
    assert d == empty_details("A", "B")


def test_found_true_or_missing_is_kept():
    assert is_usable_details(build_details("A", "B", _data(found=True)))
    assert is_usable_details(build_details("A", "B", _data()))  # older answers without the key


def test_schema_requires_found():
    from app.details_finder import DETAILS_SCHEMA
    assert DETAILS_SCHEMA["properties"]["found"] == {"type": "boolean"}
    assert "found" in DETAILS_SCHEMA["required"]


# ── repository (throwaway SQLite) ─────────────────────────────────────────

@pytest.fixture()
def db(tmp_path, monkeypatch):
    # config.DATABASE_URL is read once at import (from searcher/.env = the real local PostgreSQL): patch the constant.
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    models.dispose_engine()
    assert models.get_engine().dialect.name == "sqlite"
    models.Base.metadata.create_all(models.get_engine())
    yield
    models.dispose_engine()


def _count(table: str) -> int:
    with models.get_engine().connect() as conn:
        return conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


def test_save_creates_bike_and_roundtrips(db):
    details = build_details("Canyon", "Grizl", _data())
    bike_id, saved = save_details("Canyon", "Grizl", details)
    assert saved and bike_id is not None
    got_id, stored = get_stored_details("canyon", " GRIZL ")  # normalised lookup, caller's casing echoed
    assert got_id == bike_id
    assert stored.company == "canyon" and stored.model == " GRIZL "
    assert stored.short_description == details.short_description
    assert stored.description == details.description
    names = [(c.category, s.subcategory, [(e.name, [(p.key, p.value) for p in e.specs]) for e in s.elements])
             for c in stored.components for s in c.subcategories]
    assert names == [
        ("Frame", "Frame", [("Carbon", [("Material", "Carbon")])]),
        ("Brakes", "Brake Rotor", [("Shimano RT-MT800", [])]),  # no specs -> one NULL-spec row, round-trips as []
    ]


def test_resave_updates_in_place_and_keeps_photos(db):
    bike_id, _ = save_details("Canyon", "Grizl", build_details("Canyon", "Grizl", _data()))
    with models.get_engine().begin() as conn:
        conn.execute(text("INSERT INTO bike_detail_photos (bike_id, url, display_order) VALUES (:b, 'https://x/p.jpg', 0)"), {"b": bike_id})
        detail_id = conn.execute(text("SELECT id FROM bike_detail")).scalar_one()
    second = _data(short_description="Nowy opis.", components=[{"category": "Wheels", "subcategories": [
        {"subcategory": "Tyres", "elements": [{"name": "Schwalbe", "description": "", "specs": []}]}]}])
    _, saved = save_details("Canyon", "Grizl", build_details("Canyon", "Grizl", second))
    assert saved
    assert _count("bike") == 1 and _count("bike_detail") == 1
    with models.get_engine().connect() as conn:
        assert conn.execute(text("SELECT id FROM bike_detail")).scalar_one() == detail_id  # in place
        assert conn.execute(text("SELECT short_description FROM bike_detail")).scalar_one() == "Nowy opis."
    assert _count("bike_detail_component") == 1  # replaced, not appended
    assert _count("bike_detail_photos") == 1  # photos untouched


def test_unusable_result_writes_and_deletes_nothing(db):
    empty = build_details("Canyon", "Grizl", _data(description="", short_description="", components=[]))
    assert save_details("Canyon", "Grizl", empty) == (None, False)
    assert _count("bike") == 0  # not even a bike row
    bike_id, _ = save_details("Canyon", "Grizl", build_details("Canyon", "Grizl", _data()))
    rows = _count("bike_detail_component")
    assert save_details("Canyon", "Grizl", empty) == (bike_id, False)
    assert _count("bike_detail") == 1 and _count("bike_detail_component") == rows  # stored details kept


def test_description_only_is_stored(db):
    d = build_details("Kross", "Esker", _data(components=[]))
    bike_id, saved = save_details("Kross", "Esker", d)
    assert saved
    _, stored = get_stored_details("Kross", "Esker")
    assert stored.description.text and not has_components(stored)


def test_placeholder_casing_upgraded_but_real_casing_kept(db):
    with models.get_engine().begin() as conn:
        conn.execute(text("INSERT INTO bike (brand, model) VALUES ('canyon', 'grizl cf 7')"))
        conn.execute(text("INSERT INTO bike (brand, model) VALUES ('Trek', 'Marlin 5')"))
    save_details("Canyon", "Grizl CF 7", build_details("Canyon", "Grizl CF 7", _data()))
    save_details("TREK", "MARLIN 5", build_details("TREK", "MARLIN 5", _data()))
    with models.get_engine().connect() as conn:
        rows = {tuple(r) for r in conn.execute(text("SELECT brand, model FROM bike"))}
    assert rows == {("Canyon", "Grizl CF 7"), ("Trek", "Marlin 5")}


def test_unknown_bike_reads_nothing(db):
    assert get_stored_details("No", "Such") == (None, None)
    assert _count("bike") == 0


def test_init_db_refuses_bike_detail_without_short_description(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATABASE_URL", f"sqlite:///{tmp_path / 'old.db'}")
    monkeypatch.delenv("SEARCHER_CREATE_TABLES", raising=False)
    models.dispose_engine()
    try:
        assert models.get_engine().dialect.name == "sqlite"
        models.Base.metadata.create_all(models.get_engine())
        with models.get_engine().begin() as conn:
            conn.execute(text("ALTER TABLE bike_detail DROP COLUMN short_description"))
        with pytest.raises(RuntimeError, match="short_description"):
            models.init_db()
    finally:
        models.dispose_engine()


def test_details_model_default():
    assert BikeDetails(company="a", model="b").short_description == ""


# ── partial runs keep the other half ──────────────────────────────────────

def test_components_only_run_keeps_stored_description(db):
    save_details("Canyon", "Grizl", build_details("Canyon", "Grizl", _data()))
    second = _data(description="", short_description="", components=[{"category": "Wheels", "subcategories": [
        {"subcategory": "Tyres", "elements": [{"name": "Schwalbe", "description": "", "specs": []}]}]}])
    _, saved = save_details("Canyon", "Grizl", build_details("Canyon", "Grizl", second))
    assert saved
    _, stored = get_stored_details("Canyon", "Grizl")
    assert stored.description.text.startswith("Rower do jazdy") and stored.short_description.startswith("Lekki gravel")
    assert [c.category for c in stored.components] == ["Wheels"]


def test_description_only_run_keeps_stored_components(db):
    save_details("Canyon", "Grizl", build_details("Canyon", "Grizl", _data(description="", short_description="")))
    rows = _count("bike_detail_component")
    assert rows > 0
    _, saved = save_details("Canyon", "Grizl", build_details("Canyon", "Grizl", _data(components=[])))
    assert saved
    assert _count("bike_detail_component") == rows
    _, stored = get_stored_details("Canyon", "Grizl")
    assert stored.description.text.startswith("Rower do jazdy") and has_components(stored)


# ── route: response equals the DB read ────────────────────────────────────

def test_route_returns_stored_details_without_shells(db, monkeypatch):
    import asyncio
    from fastapi.testclient import TestClient
    from app import main as searcher_main

    async def finder(company, model):
        return build_details(company, model, _data(components=[]))  # description only -> 8 empty shells in the result

    monkeypatch.setattr(config, "SEARCHER_API_KEY", "secret-key")
    monkeypatch.setattr(searcher_main, "_semaphore", asyncio.Semaphore(2))
    monkeypatch.setattr(searcher_main, "find_bike_details", finder)
    client = TestClient(searcher_main.app)
    r = client.post("/v1/search/details", json={"company": "Kross", "model": "Esker"}, headers={"X-Searcher-Key": "secret-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] == 1 and body["bike_id"] is not None
    _, stored = get_stored_details("Kross", "Esker")
    assert body["details"] == stored.model_dump(mode="json")
    assert body["details"]["components"] == []

    async def nothing(company, model):
        return empty_details(company, model)

    monkeypatch.setattr(searcher_main, "find_bike_details", nothing)
    r = client.post("/v1/search/details", json={"company": "Unknown", "model": "Bike"}, headers={"X-Searcher-Key": "secret-key"})
    assert r.status_code == 200 and r.json()["saved"] == 0 and r.json()["details"]["components"] == []
