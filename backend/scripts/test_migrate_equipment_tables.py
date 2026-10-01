"""Unit tests for scripts/migrate_equipment_tables.py (TODO-042) on temp SQLite databases
in the pre-TODO-042 layout (already through migrate_drop_bike_detail.py: details on `bike`,
bike_detail_component keyed on bike_id) — no server, no network.
Run: cd backend && pytest   (collected via pytest.ini)"""
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import create_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import equipment_repository as er, models, repository  # noqa: E402
from app.schemas import (  # noqa: E402
    BikeCategory, BikeDescription, BikeDetailsResponse, BikeSubcategory, ComponentElement,
    EquipmentDetailsResponse,
)
from migrate_drop_bike_detail import migrate as migrate_drop_bike_detail  # noqa: E402
from migrate_equipment_tables import NEW_TABLES, migrate  # noqa: E402

OLD_COMPONENT_DDL = """
CREATE TABLE bike_detail_component (
    id INTEGER PRIMARY KEY,
    bike_id INTEGER NOT NULL REFERENCES bike (id) ON DELETE CASCADE,
    category VARCHAR(255) NOT NULL, subcategory VARCHAR(255) NOT NULL, component_order INTEGER NOT NULL,
    element_name VARCHAR(512) NOT NULL, element_description TEXT NOT NULL, element_order INTEGER NOT NULL,
    spec_key VARCHAR(255), spec_value VARCHAR(1024), spec_order INTEGER
)"""


def _old_db(path: Path, rows: int = 3) -> Path:
    """Every pre-TODO-042 table (bike_detail layout already dropped): bike_detail_component without equipment_id."""
    skip = {"bike_detail_component", *NEW_TABLES}
    engine = create_engine(f"sqlite:///{path}")
    models.Base.metadata.create_all(engine, tables=[t for n, t in models.Base.metadata.tables.items() if n not in skip])
    engine.dispose()
    conn = sqlite3.connect(path)
    conn.execute(OLD_COMPONENT_DDL)
    conn.execute("INSERT INTO bike (id, brand, model, description, short_description) VALUES (1, 'Canyon', 'Grizl', ?, '')",
                 ('{"text": "Rower.", "segments": [], "citations": []}',))
    for i in range(rows):
        conn.execute(
            "INSERT INTO bike_detail_component (bike_id, category, subcategory, component_order, element_name,"
            " element_description, element_order) VALUES (1, 'Accessories', 'Helmet', 0, ?, '', ?)",
            (f"Helmet {i}", i))
    conn.commit()
    conn.close()
    return path


def _schema(path: Path) -> tuple[list[str], list[str], list[str]]:
    conn = sqlite3.connect(path)
    try:
        columns = [r[1] for r in conn.execute("PRAGMA table_info(bike_detail_component)")]
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        indexes = [r[1] for r in conn.execute("PRAGMA index_list(bike_detail_component)")]
        return columns, tables, indexes
    finally:
        conn.close()


def test_dry_run_then_real_then_idempotent(tmp_path):
    path = _old_db(tmp_path / "old.db")
    report = migrate(path, dry_run=True, verbose=False)
    assert report["status"] == "dry-run" and report["rows_before"] == 3
    columns, tables, _ = _schema(path)
    assert "equipment_id" not in columns and not set(NEW_TABLES) & set(tables), "dry run writes nothing"

    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and report["verified"] and report["column_added"]
    assert report["rows_before"] == report["rows_after"] == 3
    assert sorted(report["tables_created"]) == sorted(NEW_TABLES)
    columns, tables, indexes = _schema(path)
    assert "equipment_id" in columns and set(NEW_TABLES) <= set(tables)
    assert "ix_bike_detail_component_equipment_id" in indexes
    conn = sqlite3.connect(path)
    fks = [(r[2], r[3], r[6]) for r in conn.execute("PRAGMA foreign_key_list(bike_detail_component)")]
    assert ("equipment", "equipment_id", "SET NULL") in fks
    assert conn.execute("SELECT COUNT(*) FROM bike_detail_component WHERE equipment_id IS NULL").fetchone()[0] == 3
    conn.close()

    again = migrate(path, verbose=False)
    assert again["status"] == "already-migrated" and again["rows_after"] == 3


def test_tables_created_by_init_db_only_get_the_column(tmp_path, monkeypatch):
    """An unmigrated database the new backend already started on: init_db() created the tables, not the column."""
    path = _old_db(tmp_path / "old.db", rows=1)
    engine = create_engine(f"sqlite:///{path}")
    models.Base.metadata.create_all(engine)  # what init_db() does: missing tables only
    engine.dispose()
    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and report["tables_created"] == [] and report["column_added"]


def test_missing_index_is_repaired_alone(tmp_path):
    path = _old_db(tmp_path / "old.db", rows=1)
    migrate(path, verbose=False)
    conn = sqlite3.connect(path)
    conn.execute("DROP INDEX ix_bike_detail_component_equipment_id")
    conn.commit()
    conn.close()
    assert migrate(path, dry_run=True, verbose=False)["status"] == "dry-run"
    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and not report["column_added"]
    assert "ix_bike_detail_component_equipment_id" in _schema(path)[2]


def test_without_table_is_absent(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    assert migrate(path, verbose=False)["status"] == "absent"


def test_migrated_database_works_with_the_orm(tmp_path, monkeypatch):
    path = _old_db(tmp_path / "old.db", rows=1)
    migrate(path, verbose=False)
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(path)
    try:
        models.init_db()
        eid = er.save_equipment_details("", "Helmet 0", "helmets", EquipmentDetailsResponse(
            company="", model="Helmet 0", category="helmets",
            description=BikeDescription(text="Kask.", segments=[], citations=[]), components=[],
        ), bike_id=1, element_name="Helmet 0")
        assert eid is not None
        details = repository.get_bike_details("Canyon", "Grizl")
        assert details.components[0].subcategories[0].elements[0].equipment_id == eid
        repository.save_bike_details("Canyon", "Grizl", BikeDetailsResponse(
            company="Canyon", model="Grizl", description=BikeDescription(text="R.", segments=[], citations=[]),
            components=[BikeCategory(category="Accessories", subcategories=[BikeSubcategory(
                subcategory="Helmet", elements=[ComponentElement(name="Helmet 0")])])],
        ))
        details = repository.get_bike_details("Canyon", "Grizl")
        assert details.components[0].subcategories[0].elements[0].equipment_id == eid, "re-save keeps the link"
    finally:
        models.dispose_engine()
        models._db_url = None


def _pre_drop_db(path: Path) -> Path:
    """The layout before migrate_drop_bike_detail.py: bike_detail + components keyed on bike_detail_id."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE bike (id INTEGER PRIMARY KEY, brand VARCHAR(255) NOT NULL, model VARCHAR(255) NOT NULL,
            created_at DATETIME, updated_at DATETIME);
        CREATE TABLE bike_detail (id INTEGER PRIMARY KEY, bike_id INTEGER NOT NULL UNIQUE REFERENCES bike (id),
            description TEXT NOT NULL, short_description TEXT NOT NULL DEFAULT '', created_at DATETIME,
            updated_at DATETIME);
        CREATE TABLE bike_detail_component (id INTEGER PRIMARY KEY,
            bike_detail_id INTEGER NOT NULL REFERENCES bike_detail (id) ON DELETE CASCADE,
            category VARCHAR(255) NOT NULL, subcategory VARCHAR(255) NOT NULL, component_order INTEGER NOT NULL,
            element_name VARCHAR(512) NOT NULL, element_description TEXT NOT NULL, element_order INTEGER NOT NULL,
            spec_key VARCHAR(255), spec_value VARCHAR(1024), spec_order INTEGER);
        CREATE TABLE bike_detail_photos (id INTEGER PRIMARY KEY, bike_id INTEGER NOT NULL REFERENCES bike (id),
            url VARCHAR(2048) NOT NULL, display_order INTEGER);
        INSERT INTO bike (id, brand, model) VALUES (1, 'Canyon', 'Grizl');
        INSERT INTO bike_detail (id, bike_id, description) VALUES (7, 1, '{"text": "R.", "segments": [], "citations": []}');
        INSERT INTO bike_detail_component (bike_detail_id, category, subcategory, component_order, element_name,
            element_description, element_order) VALUES (7, 'Accessories', 'Helmet', 0, 'Helmet 0', '', 0);
    """)
    conn.commit()
    conn.close()
    return path


def test_refuses_before_the_bike_detail_migration_then_runs_after_it(tmp_path):
    """Production order: migrate_drop_bike_detail.py first, then this script."""
    path = _pre_drop_db(tmp_path / "pre.db")
    for dry_run in (True, False):
        report = migrate(path, dry_run=dry_run, verbose=False)
        assert report["status"] == "failed" and "migrate_drop_bike_detail.py" in report["error"]
    columns, tables, _ = _schema(path)
    assert "equipment_id" not in columns and not set(NEW_TABLES) & set(tables), "a refusal writes nothing"

    assert migrate_drop_bike_detail(path, verbose=False)["status"] == "migrated"
    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and report["column_added"] and report["rows_after"] == 1
    columns, tables, indexes = _schema(path)
    assert {"bike_id", "equipment_id"} <= set(columns) and set(NEW_TABLES) <= set(tables)
    assert "ix_bike_detail_component_equipment_id" in indexes
    assert migrate_drop_bike_detail(path, verbose=False)["status"] == "already-migrated", "extra column is fine"
    assert migrate(path, verbose=False)["status"] == "already-migrated"
