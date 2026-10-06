"""Unit tests for scripts/migrate_component_linkable.py (ISSUE-016) on throwaway SQLite files:
a pre-migration table (no is_linkable column) is built by hand, migrated, verified, and then read
through the ORM. No server, no network, no AI. Run: cd backend && pytest   (collected via pytest.ini)"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import models, repository  # noqa: E402
from migrate_component_linkable import migrate  # noqa: E402
from migrate_bike_category import migrate as migrate_category  # noqa: E402

ROWS = [
    # (bike_id, category, subcategory, component_order, element_name, element_order, spec_key, spec_value, spec_order)
    (1, "Accessories", "Tool", 0, "Giant Multi-Tool", 0, "Tools", "Allen keys", 0),
    (1, "Accessories", "Tool", 0, "Giant Multi-Tool", 0, "Material", "Steel", 1),
    (1, "Accessories", "Pedals", 1, "None included", 0, None, None, None),
    (1, "Accessories", "Included Items", 2, "Owner's Manual", 0, None, None, None),
    (1, "Accessories", "Included Items", 2, "Quick Start Guide", 1, None, None, None),
    (1, "Accessories", "Included Items", 2, "Warranty Documentation", 2, None, None, None),
    (1, "Drivetrain", "Rear Derailleur", 3, "Shimano Deore RD-M6000", 0, "Weight", "300 g", 0),
    (1, "Frame", "Frame", 4, "Frame", 0, "Material", "Aluminium", 0),
]
EXPECTED = {
    "Giant Multi-Tool": 1, "None included": 0, "Owner's Manual": 0, "Quick Start Guide": 0,
    "Warranty Documentation": 0, "Shimano Deore RD-M6000": 1, "Frame": 0,
}


def _old_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE bike (
            id INTEGER PRIMARY KEY, brand VARCHAR(255) NOT NULL, model VARCHAR(255) NOT NULL,
            brand_norm VARCHAR(255) NOT NULL, model_norm VARCHAR(255) NOT NULL,
            created_at DATETIME, updated_at DATETIME, description TEXT, short_description TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE bike_component (
            id INTEGER PRIMARY KEY, bike_id INTEGER NOT NULL REFERENCES bike(id) ON DELETE CASCADE,
            category VARCHAR(255) NOT NULL, subcategory VARCHAR(255) NOT NULL, component_order INTEGER NOT NULL,
            element_name VARCHAR(512) NOT NULL, element_description TEXT NOT NULL DEFAULT '',
            element_order INTEGER NOT NULL, spec_key VARCHAR(255), spec_value VARCHAR(1024), spec_order INTEGER,
            equipment_id INTEGER
        );
        INSERT INTO bike (id, brand, model, brand_norm, model_norm, description)
        VALUES (1, 'Giant', 'Talon 3', 'giant', 'talon 3', '{"text": "Opis.", "segments": [], "citations": []}');
    """)
    con.executemany(
        "INSERT INTO bike_component (bike_id, category, subcategory, component_order, element_name, "
        "element_order, spec_key, spec_value, spec_order) VALUES (?,?,?,?,?,?,?,?,?)", ROWS)
    con.commit()
    con.close()
    return path


def _flags(path):
    con = sqlite3.connect(path)
    try:
        return dict(con.execute("SELECT element_name, is_linkable FROM bike_component GROUP BY 1, 2"))
    finally:
        con.close()


def _columns(path):
    con = sqlite3.connect(path)
    try:
        return {r[1] for r in con.execute("PRAGMA table_info(bike_component)")}
    finally:
        con.close()


def test_dry_run_changes_nothing(tmp_path):
    db = _old_db(tmp_path / "old.db")
    report = migrate(db, dry_run=True, verbose=False)
    assert report["status"] == "dry-run"
    assert (report["linkable"], report["not_linkable"]) == (3, 5)
    assert "is_linkable" not in _columns(db)


def test_migrates_and_classifies_every_row(tmp_path):
    db = _old_db(tmp_path / "old.db")
    report = migrate(db, verbose=False)
    assert report["status"] == "migrated" and report["verified"]
    assert report["rows_before"] == report["rows_after"] == len(ROWS)
    assert _flags(db) == EXPECTED


def test_idempotent_and_keeps_existing_flags(tmp_path):
    db = _old_db(tmp_path / "old.db")
    assert migrate(db, verbose=False)["status"] == "migrated"
    # Simulate the searcher's model overruling the heuristic, then re-run.
    con = sqlite3.connect(db)
    con.execute("UPDATE bike_component SET is_linkable = 1 WHERE element_name = 'None included'")
    con.commit()
    con.close()
    assert migrate(db, verbose=False)["status"] == "already-migrated"
    assert _flags(db)["None included"] == 1


def test_reclassify_reruns_the_heuristic(tmp_path):
    db = _old_db(tmp_path / "old.db")
    migrate(db, verbose=False)
    con = sqlite3.connect(db)
    con.execute("UPDATE bike_component SET is_linkable = 1")
    con.commit()
    con.close()
    report = migrate(db, reclassify=True, verbose=False)
    assert report["status"] == "reclassified" and report["verified"]
    assert _flags(db) == EXPECTED


def test_absent_table_is_left_to_init_db(tmp_path):
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    assert migrate(db, verbose=False)["status"] == "absent"


def test_migrated_database_works_with_the_orm(tmp_path, monkeypatch):
    db = _old_db(tmp_path / "old.db")
    migrate(db, verbose=False)
    migrate_category(db, verbose=False)  # the ORM selects bike.category too
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(db)
    try:
        details = repository.get_bike_details("Giant", "Talon 3")
        flags = {el.name: el.is_linkable for cat in details.components for sub in cat.subcategories
                 for el in sub.elements}
        assert flags == {k: bool(v) for k, v in EXPECTED.items()}
    finally:
        models.dispose_engine()
        models._db_url = None


def test_refuses_a_database_still_on_the_old_table_name(tmp_path):
    db = _old_db(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE bike_component RENAME TO bike_detail_component")
    con.commit()
    con.close()
    report = migrate(db, verbose=False)
    assert report["status"] == "failed" and "migrate_rename_bike_component" in report["error"]
