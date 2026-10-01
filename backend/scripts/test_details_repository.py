"""Unit tests for the stored bike details (TODO-041): short_description round-trip,
accessory_chips / the search-result fill, save_search,
scripts/migrate_short_description.py and scripts/purge_details_cache.py,
each on a fresh temp SQLite database — no server, no network, no AI call.
Run: cd backend && pytest   (collected via pytest.ini)"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import insert, inspect, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import models, repository, store  # noqa: E402
from app.models import endpoint_req_to_body_cache  # noqa: E402
from app.schemas import (  # noqa: E402
    BikeCategory, BikeDescription, BikeDetailsResponse, BikeResult, BikeSubcategory, ComponentElement, SpecItem,
)
from migrate_short_description import migrate  # noqa: E402
from purge_details_cache import purge  # noqa: E402


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(tmp_path / "details.db")
    models.init_db()
    yield tmp_path / "details.db"
    models.dispose_engine()
    models._db_url = None


def _el(category, sub, name, specs=()):
    return BikeCategory(category=category, subcategories=[BikeSubcategory(subcategory=sub, elements=[
        ComponentElement(name=name, description="", specs=[SpecItem(key=k, value=v) for k, v in specs]),
    ])])


def _details(brand, model, components, short="Krótko. Dwa zdania.", text="Opis."):
    return BikeDetailsResponse(
        company=brand, model=model,
        description=BikeDescription(text=text, segments=[], citations=[]),
        components=components, short_description=short,
    )


FULL = [
    _el("Frame", "Frame", "Frame X", [("Weight", "1 kg"), ("Material", "Carbon (CF)")]),
    _el("Drivetrain", "Rear Derailleur", "Shimano GRX RD-RX822"),
    _el("Brakes", "Brake Lever Front", "Shimano GRX BL-RX820"),
]


def _bike_id(brand, model):
    with models.get_session() as s:
        return s.query(models.Bike.id).filter_by(brand=brand, model=model).scalar()


def test_short_description_round_trips(db):
    repository.save_bike_details("Trek", "Marlin 5", _details("Trek", "Marlin 5", FULL))
    got = repository.get_bike_details("trek", " MARLIN 5")  # normalised lookup
    assert got is not None and got.short_description == "Krótko. Dwa zdania."
    assert got.company == "Trek", "stored casing; the endpoint echoes the caller's"
    repository.save_bike_details("Trek", "Marlin 5", _details("Trek", "Marlin 5", FULL, short="Nowe."))
    assert repository.get_bike_details("Trek", "Marlin 5").short_description == "Nowe."


def test_empty_details_shape():
    e = repository.empty_details("A", "B")
    assert e.description.text == "" and e.components == [] and e.short_description == ""



def test_accessory_chips_picks_present_parts_only(db):
    repository.save_bike_details("Trek", "Full", _details("Trek", "Full", FULL))
    assert repository.accessory_chips(_bike_id("Trek", "Full")) == [
        "Shimano GRX RD-RX822", "Shimano GRX BL-RX820", "Carbon (CF)",
    ]
    # Crank when there is no rear derailleur, Brake Rotor when there is no lever, nothing for a missing part.
    repository.save_bike_details("Trek", "Partial", _details("Trek", "Partial", [
        _el("Drivetrain", "Crank", "FC-X"), _el("Brakes", "Brake Rotor", "SM-RT64"),
        _el("Frame", "Frame", "Frame Y", [("Weight", "1 kg")]),
    ]))
    assert repository.accessory_chips(_bike_id("Trek", "Partial")) == ["FC-X", "SM-RT64"]
    # The discovery scraper stores a plain "Brake Lever".
    repository.save_bike_details("Trek", "Scraped", _details("Trek", "Scraped", [_el("Brakes", "Brake Lever", "Tektro")]))
    assert repository.accessory_chips(_bike_id("Trek", "Scraped")) == ["Tektro"]


def test_bike_without_details_has_no_chips(db):
    with models.get_session() as s:
        b = models.Bike(brand="Trek", model="Bare")
        s.add(b)
        s.commit()
        bid = b.id
    assert repository.accessory_chips(bid) == []
    (r,) = repository.fill_bike_results([BikeResult(brand="trek", model="BARE", accessories=["x"], explanation="y")])
    assert r.explanation == "" and r.accessories == [], "AI text is never kept; a bike without details stays empty"


def test_fill_bike_results_uses_stored_details(db):
    repository.save_bike_details("Trek", "Full", _details("Trek", "Full", FULL, short="Tekst krótki."))
    (r,) = repository.fill_bike_results([BikeResult(brand="TREK", model="full", accessories=[], explanation="")])
    assert r.explanation == "Tekst krótki." and len(r.accessories) == 3


def test_save_search_stores_bikes_only(db):
    with models.get_session() as s:
        s.add(models.Bike(brand="Trek", model="Full"))
        s.commit()
    store.save_search("Brand: Trek", [
        BikeResult(brand="trek", model="FULL", accessories=["ignored"], explanation="ignored"),
        BikeResult(brand="Trek", model="New", accessories=[], explanation=""),
    ])
    with models.get_engine().connect() as conn:
        rows = conn.exec_driver_sql("SELECT brand, model FROM bike ORDER BY id").fetchall()
        tables = set(inspect(conn).get_table_names())
    assert [tuple(r) for r in rows] == [("Trek", "Full"), ("Trek", "New")],         "an existing bike is matched case-insensitively, a new one is created with the caller's casing"
    assert not tables & {"search_cache", "search_bike_rating_cache"}, "the per-search tables are gone (TODO-043)"
    assert not hasattr(store, "get_search_by_query") and not hasattr(store, "find_bikes_by_brand")


def test_find_bikes_by_details_fills_explanation_and_chips(db):
    from app.schemas import SearchRequest
    repository.save_bike_details("Trek", "Full", _details("Trek", "Full", FULL, short="Tekst krótki."))
    (r,) = repository.find_bikes_by_details(SearchRequest(brand="Trek", model="Full"))
    assert r.explanation == "Tekst krótki." and r.accessories[0] == "Shimano GRX RD-RX822"
    assert not hasattr(repository, "_describe_match") and not hasattr(repository, "_latest_ratings")


# ── migrate_short_description.py ───────────────────────────────────────────

def _old_db(path: Path, rows=2) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE bike_detail (id INTEGER PRIMARY KEY, bike_id INTEGER NOT NULL, description TEXT NOT NULL, created_at DATETIME, updated_at DATETIME)")
    for i in range(rows):
        conn.execute("INSERT INTO bike_detail (bike_id, description) VALUES (?, ?)", (i + 1, "{}"))
    conn.commit()
    conn.close()
    return path


def _columns(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[1] for r in conn.execute("PRAGMA table_info(bike_detail)")]
    finally:
        conn.close()


def test_migration_dry_run_then_real_then_idempotent(tmp_path):
    path = _old_db(tmp_path / "old.db")
    report = migrate(path, dry_run=True, verbose=False)
    assert report["status"] == "dry-run" and "short_description" not in _columns(path)

    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and report["verified"] and report["rows_before"] == report["rows_after"] == 2
    assert "short_description" in _columns(path)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM bike_detail WHERE short_description = ''").fetchone()[0] == 2
    conn.execute("INSERT INTO bike_detail (bike_id, description) VALUES (9, '{}')")  # server default applies
    conn.close()

    again = migrate(path, verbose=False)
    assert again["status"] == "already-migrated"


def test_migration_without_table_is_absent(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    assert migrate(path, verbose=False)["status"] == "absent"


def test_migrated_database_works_with_the_orm(tmp_path, monkeypatch):
    path = _old_db(tmp_path / "old.db", rows=0)
    migrate(path, verbose=False)
    sqlite3.connect(path).close()
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(path)
    try:
        models.init_db()  # creates the other tables; bike_detail keeps the migrated shape
        repository.save_bike_details("Trek", "Marlin", _details("Trek", "Marlin", FULL))
        assert repository.get_bike_details("Trek", "Marlin").short_description == "Krótko. Dwa zdania."
    finally:
        models.dispose_engine()
        models._db_url = None


# ── purge_details_cache.py ─────────────────────────────────────────────────

def _cache(endpoint, request):
    with models.get_engine().begin() as conn:
        conn.execute(insert(endpoint_req_to_body_cache).values(
            endpoint=endpoint, request=request, response=json.dumps({}), time_stored="2026-05-01T10:00:00+00:00",
        ))


def test_purge_deletes_only_details_rows(db):
    _cache("/v1/bike/details", "a")
    _cache("/v1/bike/details", "b")
    _cache("/v1/equipment/details", "a")
    _cache("/v1/bike/details-cache", "a")

    report = purge(db, dry_run=True, verbose=False)
    assert report["status"] == "dry-run" and report["rows"] == 2
    with models.get_engine().connect() as conn:
        assert conn.execute(select(endpoint_req_to_body_cache)).fetchall().__len__() == 4

    report = purge(db, verbose=False)
    assert report["status"] == "purged" and report["rows"] == 2
    with models.get_engine().connect() as conn:
        left = sorted(r.endpoint for r in conn.execute(select(endpoint_req_to_body_cache)))
    assert left == ["/v1/bike/details-cache", "/v1/equipment/details"]
    assert purge(db, verbose=False)["rows"] == 0, "idempotent"


def test_migrate_drop_search_tables(tmp_path):
    """The TODO-043 migration drops both per-search tables, keeps `bike`, and is idempotent."""
    from sqlalchemy import create_engine
    from migrate_drop_search_tables import migrate as drop_search_tables

    path = tmp_path / "old.db"
    eng = create_engine(f"sqlite:///{path}")
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE bike (id INTEGER PRIMARY KEY, brand TEXT, model TEXT)")
        conn.exec_driver_sql("INSERT INTO bike (brand, model) VALUES ('Trek', 'A'), ('Trek', 'B')")
        conn.exec_driver_sql("CREATE TABLE search_cache (id INTEGER PRIMARY KEY, query TEXT UNIQUE, time_stored TEXT)")
        conn.exec_driver_sql(
            "CREATE TABLE search_bike_rating_cache (id INTEGER PRIMARY KEY, "
            "search_cache_id INTEGER REFERENCES search_cache(id) ON DELETE CASCADE, "
            "bike_id INTEGER REFERENCES bike(id) ON DELETE CASCADE, "
            "explanation TEXT, accessories TEXT, display_order INTEGER)")
        conn.exec_driver_sql("INSERT INTO search_cache (query, time_stored) VALUES ('q', 't')")
        conn.exec_driver_sql("INSERT INTO search_bike_rating_cache VALUES (1, 1, 1, '', '[]', 0), (2, 1, 2, '', '[]', 1)")
    eng.dispose()

    dry = drop_search_tables(path, dry_run=True, verbose=False)
    assert dry["status"] == "dry-run" and dry["dropped"] == {"search_bike_rating_cache": 2, "search_cache": 1}
    with sqlite3.connect(path) as con:
        assert con.execute("SELECT COUNT(*) FROM search_cache").fetchone()[0] == 1, "dry run wrote nothing"

    rep = drop_search_tables(path, verbose=False)
    assert rep["status"] == "migrated" and rep["verified"] and rep["bikes_before"] == rep["bikes_after"] == 2
    with sqlite3.connect(path) as con:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert names == {"bike"}
        assert con.execute("SELECT COUNT(*) FROM bike").fetchone()[0] == 2

    assert drop_search_tables(path, verbose=False)["status"] == "already-migrated"
