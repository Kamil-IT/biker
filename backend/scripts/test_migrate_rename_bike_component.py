"""migrate_rename_bike_component.py on throwaway SQLite files (bike_detail_component -> bike_component).

Run: cd backend && .venv\\Scripts\\python.exe -m pytest scripts/test_migrate_rename_bike_component.py -q
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import models, repository  # noqa: E402
from migrate_rename_bike_component import migrate  # noqa: E402

ROWS = [(1, 1, "Frame", "Frame", 0, "F", "d", 0, "Material", "Carbon", 0, None),
        (2, 1, "Frame", "Fork", 0, "Fk", "", 1, None, None, None, 7),
        (3, 2, "Brakes", "Brake Lever", 1, "Tektro", "", 0, "Type", "Disc", 0, None)]
INDEXED = ("bike_id", "category", "subcategory", "element_name", "spec_key", "equipment_id")


def _old_db(path: Path, orphans=True, new_table=None) -> Path:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE bike (id INTEGER PRIMARY KEY, brand VARCHAR(255) NOT NULL, model VARCHAR(255) NOT NULL, "
                 "created_at DATETIME, updated_at DATETIME, description TEXT, short_description TEXT NOT NULL DEFAULT '')")
    for i in (1, 2):
        conn.execute("INSERT INTO bike (id, brand, model, description) VALUES (?, 'Trek', ?, '{\"text\": \"a\", \"segments\": [], \"citations\": []}')", (i, f"M{i}"))
    ddl = ("(id INTEGER NOT NULL, bike_id INTEGER NOT NULL, category VARCHAR(255) NOT NULL, subcategory VARCHAR(255) NOT NULL, "
           "component_order INTEGER NOT NULL, element_name VARCHAR(512) NOT NULL, element_description TEXT NOT NULL, "
           "element_order INTEGER NOT NULL, spec_key VARCHAR(255), spec_value VARCHAR(1024), spec_order INTEGER, "
           "equipment_id INTEGER, PRIMARY KEY (id), FOREIGN KEY(bike_id) REFERENCES bike (id) ON DELETE CASCADE)")
    conn.execute(f"CREATE TABLE bike_detail_component {ddl}")
    conn.executemany("INSERT INTO bike_detail_component VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ROWS)
    for c in INDEXED:
        conn.execute(f"CREATE INDEX ix_bike_detail_component_{c} ON bike_detail_component ({c})")
    if orphans:
        conn.execute("CREATE TABLE bike_detail_component_orphans (id INTEGER PRIMARY KEY, bike_detail_id INTEGER, bike_id INTEGER)")
        conn.execute("INSERT INTO bike_detail_component_orphans VALUES (9, 99, NULL)")
    if new_table is not None:  # an empty (or populated) bike_component next to the old one
        conn.execute(f"CREATE TABLE bike_component {ddl}")
        conn.executemany("INSERT INTO bike_component VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", new_table)
    conn.commit()
    conn.close()
    return path


def _q(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def _tables(path):
    return {r[0] for r in _q(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}


def _indexes(path, table):
    return {r[1] for r in _q(path, f"PRAGMA index_list({table})")}


def test_dry_run_changes_nothing(tmp_path):
    path = _old_db(tmp_path / "old.db")
    report = migrate(path, dry_run=True, verbose=False)
    assert report["status"] == "dry-run" and report["rows_before"] == 3 and report["renamed"] == []
    assert "bike_detail_component" in _tables(path) and "bike_component" not in _tables(path)


def test_renames_table_indexes_and_orphans(tmp_path):
    path = _old_db(tmp_path / "old.db")
    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and report["verified"] and report["error"] is None
    assert report["rows_before"] == report["rows_after"] == 3
    tables = _tables(path)
    assert "bike_component" in tables and "bike_component_orphans" in tables
    assert "bike_detail_component" not in tables and "bike_detail_component_orphans" not in tables
    assert _q(path, "SELECT id, bike_id, element_name, spec_key, equipment_id FROM bike_component ORDER BY id") == [
        (1, 1, "F", "Material", None), (2, 1, "Fk", None, 7), (3, 2, "Tektro", "Type", None),
    ]
    assert _indexes(path, "bike_component") == {f"ix_bike_component_{c}" for c in INDEXED}
    assert _q(path, "SELECT id, bike_detail_id FROM bike_component_orphans") == [(9, 99)]
    # the FK to bike survives the rename
    fks = _q(path, "PRAGMA foreign_key_list(bike_component)")
    assert fks and fks[0][2] == "bike" and fks[0][3] == "bike_id" and fks[0][6].upper() == "CASCADE"


def test_idempotent(tmp_path):
    path = _old_db(tmp_path / "old.db", orphans=False)
    assert migrate(path, verbose=False)["status"] == "migrated"
    again = migrate(path, verbose=False)
    assert again["status"] == "already-migrated" and again["rows_after"] == 3 and again["renamed"] == []


def test_repairs_leftover_index_names(tmp_path):
    path = _old_db(tmp_path / "old.db", orphans=False)
    conn = sqlite3.connect(path)
    conn.execute("ALTER TABLE bike_detail_component RENAME TO bike_component")  # keeps the old index names
    conn.commit()
    conn.close()
    report = migrate(path, verbose=False)
    assert report["status"] == "repaired" and len(report["renamed"]) == len(INDEXED)
    assert _indexes(path, "bike_component") == {f"ix_bike_component_{c}" for c in INDEXED}


def test_drops_empty_new_table_created_too_early(tmp_path):
    path = _old_db(tmp_path / "old.db", orphans=False, new_table=[])
    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and report["rows_after"] == 3
    assert report["renamed"][0] == "drop bike_component"
    assert "bike_detail_component" not in _tables(path)


def test_drops_empty_old_table_recreated_by_old_backend(tmp_path):
    path = _old_db(tmp_path / "old.db", orphans=False)
    assert migrate(path, verbose=False)["status"] == "migrated"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE bike_detail_component (id INTEGER PRIMARY KEY, bike_id INTEGER NOT NULL, category VARCHAR(255), "
                 "subcategory VARCHAR(255), component_order INTEGER, element_name VARCHAR(512), element_description TEXT, "
                 "element_order INTEGER, spec_key VARCHAR(255), spec_value VARCHAR(1024), spec_order INTEGER, equipment_id INTEGER)")
    conn.commit()
    conn.close()
    report = migrate(path, verbose=False)
    assert report["status"] == "repaired" and report["renamed"] == ["drop bike_detail_component"]
    assert report["rows_after"] == 3 and "bike_detail_component" not in _tables(path)


def test_refuses_when_both_tables_hold_data(tmp_path):
    path = _old_db(tmp_path / "old.db", orphans=False, new_table=ROWS[:1])
    report = migrate(path, verbose=False)
    assert report["status"] == "failed" and "both" in report["error"]
    assert "bike_detail_component" in _tables(path) and _q(path, "SELECT COUNT(*) FROM bike_component") == [(1,)]


def test_fresh_database_is_left_to_init_db(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    assert migrate(path, verbose=False)["status"] == "absent"


def test_migrated_database_works_with_the_orm(tmp_path, monkeypatch):
    path = _old_db(tmp_path / "old.db")
    migrate(path, verbose=False)
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(path)
    try:
        models.init_db()
        got = repository.get_bike_details("Trek", "M1")
        assert [c.category for c in got.components] == ["Frame"]
        assert [e.name for s in got.components[0].subcategories for e in s.elements] == ["F", "Fk"]
    finally:
        models.dispose_engine()
        models._db_url = None
