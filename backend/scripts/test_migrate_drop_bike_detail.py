"""migrate_drop_bike_detail.py on throwaway SQLite files (old layout -> new layout).

Run: cd backend && .venv\\Scripts\\python.exe -m pytest scripts/test_migrate_drop_bike_detail.py -q
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from app import models, repository  # noqa: E402
from app.schemas import (  # noqa: E402
    BikeCategory, BikeDescription, BikeDetailsResponse, BikeSubcategory, ComponentElement, SpecItem,
)
from migrate_drop_bike_detail import migrate  # noqa: E402
from migrate_rename_bike_component import migrate as rename_component  # noqa: E402
from migrate_equipment_tables import migrate as migrate_equipment_tables  # noqa: E402
from migrate_component_linkable import migrate as migrate_linkable  # noqa: E402


A_JSON = '{"text": "a", "segments": [], "citations": []}'
B_JSON = '{"text": "b"}'


def _old_db(path: Path, short_description=True, orphan=True) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("CREATE TABLE bike (id INTEGER PRIMARY KEY, brand VARCHAR(255) NOT NULL, model VARCHAR(255) NOT NULL, "
                 "created_at DATETIME, updated_at DATETIME)")
    for i in (1, 2, 3):
        conn.execute("INSERT INTO bike (id, brand, model) VALUES (?, 'Trek', ?)", (i, f"M{i}"))
    sd = ", short_description TEXT NOT NULL DEFAULT ''" if short_description else ""
    conn.execute("CREATE TABLE bike_detail (id INTEGER PRIMARY KEY, bike_id INTEGER NOT NULL UNIQUE, "
                 f"description TEXT NOT NULL{sd}, created_at DATETIME, updated_at DATETIME)")
    conn.execute("INSERT INTO bike_detail (id, bike_id, description) VALUES (10, 1, '{\"text\": \"a\", \"segments\": [], \"citations\": []}')")
    conn.execute("INSERT INTO bike_detail (id, bike_id, description) VALUES (11, 2, '{\"text\": \"b\"}')")
    if short_description:
        conn.execute("UPDATE bike_detail SET short_description = 'Krotko.' WHERE id = 10")
    conn.execute("CREATE TABLE bike_detail_component (id INTEGER PRIMARY KEY, bike_detail_id INTEGER NOT NULL "
                 "REFERENCES bike_detail(id) ON DELETE CASCADE, category VARCHAR(255) NOT NULL, "
                 "subcategory VARCHAR(255) NOT NULL, component_order INTEGER NOT NULL, element_name VARCHAR(512) NOT NULL, "
                 "element_description TEXT NOT NULL, element_order INTEGER NOT NULL, spec_key VARCHAR(255), "
                 "spec_value VARCHAR(1024), spec_order INTEGER)")
    rows = [(1, 10, "Frame", "Frame", 0, "F", "d", 0, "Material", "Carbon", 0),
            (2, 10, "Frame", "Fork", 0, "Fk", "", 1, None, None, None),
            (3, 11, "Brakes", "Brake Lever", 1, "Tektro", "", 0, "Type", "Disc", 0)]
    if orphan:
        rows.append((4, 99, "Wheels", "Rim", 2, "R", "", 0, "Size", "29", 0))  # no bike_detail 99
    conn.executemany("INSERT INTO bike_detail_component VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("CREATE INDEX ix_bike_detail_component_bike_detail_id ON bike_detail_component (bike_detail_id)")
    conn.execute("CREATE TABLE bike_detail_photos (id INTEGER PRIMARY KEY, bike_id INTEGER NOT NULL "
                 "REFERENCES bike(id) ON DELETE CASCADE, url VARCHAR(2048) NOT NULL, display_order INTEGER)")
    conn.commit()
    conn.close()
    return path


def _q(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_dry_run_changes_nothing(tmp_path):
    path = _old_db(tmp_path / "old.db")
    report = migrate(path, dry_run=True, verbose=False)
    assert report["status"] == "dry-run" and report["details_before"] == 2 and len(report["orphans"]) == 1
    assert _q(path, "SELECT name FROM sqlite_master WHERE name = 'bike_detail'")
    assert "description" not in [r[1] for r in _q(path, "PRAGMA table_info(bike)")]


def test_migrates_details_components_and_orphans(tmp_path):
    path = _old_db(tmp_path / "old.db")
    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and report["verified"] and report["error"] is None
    assert report["details_after"] == 2 and report["rows_before"] == 4 and report["rows_after"] == 3
    assert _q(path, "SELECT id, description, short_description FROM bike ORDER BY id") == [
        (1, A_JSON, "Krotko."), (2, B_JSON, ""), (3, None, ""),
    ]
    assert not _q(path, "SELECT name FROM sqlite_master WHERE name = 'bike_detail'")
    assert _q(path, "SELECT id, bike_id, element_name FROM bike_detail_component ORDER BY id") == [
        (1, 1, "F"), (2, 1, "Fk"), (3, 2, "Tektro"),
    ]
    cols = [r[1] for r in _q(path, "PRAGMA table_info(bike_detail_component)")]
    assert "bike_id" in cols and "bike_detail_id" not in cols
    assert _q(path, "SELECT id, bike_detail_id, element_name FROM bike_detail_component_orphans") == [(4, 99, "R")]
    # NULL spec columns survive
    assert _q(path, "SELECT spec_key, spec_value, spec_order FROM bike_detail_component WHERE id = 2") == [(None, None, None)]


def test_missing_short_description_column_reads_as_empty(tmp_path):
    path = _old_db(tmp_path / "old.db", short_description=False, orphan=False)
    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and report["verified"]
    assert _q(path, "SELECT short_description FROM bike WHERE id IN (1, 2)") == [("",), ("",)]
    assert not _q(path, "SELECT name FROM sqlite_master WHERE name = 'bike_detail_component_orphans'")


def test_idempotent(tmp_path):
    path = _old_db(tmp_path / "old.db")
    assert migrate(path, verbose=False)["status"] == "migrated"
    again = migrate(path, verbose=False)
    assert again["status"] == "already-migrated" and again["rows_after"] == 3 and again["details_after"] == 2


def test_refuses_unmigrated_photos(tmp_path):
    path = _old_db(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute("DROP TABLE bike_detail_photos")
    conn.execute("CREATE TABLE bike_detail_photos (id INTEGER PRIMARY KEY, bike_detail_id INTEGER, url TEXT, display_order INTEGER)")
    conn.commit()
    conn.close()
    report = migrate(path, verbose=False)
    assert report["status"] == "failed" and "migrate_photos_bike_id" in report["error"]
    assert _q(path, "SELECT name FROM sqlite_master WHERE name = 'bike_detail'")  # untouched


def test_fresh_database_is_left_to_init_db(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    assert migrate(path, verbose=False)["status"] == "absent"


def test_migrated_database_works_with_the_orm(tmp_path, monkeypatch):
    path = _old_db(tmp_path / "old.db")
    migrate(path, verbose=False)
    # The documented order: this migration, then TODO-042's (the ORM reads bike_detail_component.equipment_id).
    assert migrate_equipment_tables(path, verbose=False)["status"] == "migrated"
    assert rename_component(path, verbose=False)["status"] == "migrated"  # the ORM maps bike_component now
    assert migrate_linkable(path, verbose=False)["status"] == "migrated"  # ISSUE-016: the ORM selects is_linkable too
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(path)
    try:
        models.init_db()
        got = repository.get_bike_details("Trek", "M1")
        assert got.short_description == "Krotko." and got.description.text == "a"
        assert [c.category for c in got.components] == ["Frame"]
        assert repository.get_bike_details("Trek", "M3") is None  # description NULL = no details
        resp = BikeDetailsResponse(
            company="Trek", model="M3", description=BikeDescription(text="n", segments=[], citations=[]),
            components=[BikeCategory(category="Frame", subcategories=[BikeSubcategory(
                subcategory="Frame", elements=[ComponentElement(name="X", description="", specs=[SpecItem(key="Material", value="Alu")])])])],
            short_description="Nowe.",
        )
        assert repository.save_bike_details("Trek", "M3", resp) is True
        assert repository.get_bike_details("Trek", "M3").short_description == "Nowe."
    finally:
        models.dispose_engine()
        models._db_url = None


def test_save_bike_details_returns_false_on_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(tmp_path / "fresh.db")
    try:
        # no tables created -> the save fails and reports it
        resp = BikeDetailsResponse(company="A", model="B", description=BikeDescription(text="", segments=[], citations=[]),
                                   components=[], short_description="")
        assert repository.save_bike_details("A", "B", resp) is False
    finally:
        models.dispose_engine()
        models._db_url = None
