"""migrate_merge_equipment_detail.py on throwaway SQLite files (old layout -> merged layout, TODO-044).

Run: cd backend && .venv\\Scripts\\python.exe -m pytest scripts/test_migrate_merge_equipment_detail.py -q
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest  # noqa: E402

from app import equipment_repository as er, models  # noqa: E402
from app.schemas import (  # noqa: E402
    BikeCategory, BikeDescription, BikeSubcategory, ComponentElement, EquipmentDetailsRequest,
    EquipmentDetailsResponse, EquipmentPhotosRequest, SpecItem,
)
from migrate_equipment_part_search import migrate as migrate_part_search  # noqa: E402
from migrate_equipment_tables import migrate as migrate_equipment_tables  # noqa: E402
from migrate_merge_equipment_detail import migrate  # noqa: E402

D1 = '{"text": "Kask.", "segments": [], "citations": []}'
D3 = '{"text": "Oktal.", "segments": [], "citations": []}'

OLD_DDL = """
CREATE TABLE bike (id INTEGER PRIMARY KEY, brand VARCHAR(255) NOT NULL, model VARCHAR(255) NOT NULL,
    description TEXT, short_description TEXT NOT NULL DEFAULT '', created_at DATETIME, updated_at DATETIME);
CREATE TABLE equipment (id INTEGER NOT NULL, category VARCHAR(32) NOT NULL, company VARCHAR(255) NOT NULL,
    model VARCHAR(512) NOT NULL, company_norm VARCHAR(255) NOT NULL, model_norm VARCHAR(512) NOT NULL,
    created_at DATETIME, PRIMARY KEY (id),
    CONSTRAINT uq_equipment_identity UNIQUE (category, company_norm, model_norm));
CREATE TABLE equipment_detail (id INTEGER NOT NULL, equipment_id INTEGER NOT NULL UNIQUE,
    description TEXT NOT NULL, short_description TEXT DEFAULT '' NOT NULL, created_at DATETIME, updated_at DATETIME,
    PRIMARY KEY (id), FOREIGN KEY(equipment_id) REFERENCES equipment (id) ON DELETE CASCADE);
CREATE TABLE equipment_detail_component (id INTEGER NOT NULL, equipment_detail_id INTEGER NOT NULL,
    category VARCHAR(255) NOT NULL, subcategory VARCHAR(255) NOT NULL, component_order INTEGER NOT NULL,
    element_name VARCHAR(512) NOT NULL, element_description TEXT NOT NULL, element_order INTEGER NOT NULL,
    spec_key VARCHAR(255), spec_value VARCHAR(1024), spec_order INTEGER, PRIMARY KEY (id),
    FOREIGN KEY(equipment_detail_id) REFERENCES equipment_detail (id) ON DELETE CASCADE);
CREATE INDEX ix_equipment_detail_component_equipment_detail_id ON equipment_detail_component (equipment_detail_id);
CREATE TABLE equipment_detail_photos (id INTEGER NOT NULL, equipment_id INTEGER NOT NULL,
    url VARCHAR(2048) NOT NULL, display_order INTEGER, PRIMARY KEY (id),
    FOREIGN KEY(equipment_id) REFERENCES equipment (id) ON DELETE CASCADE);
CREATE TABLE bike_component (id INTEGER NOT NULL, bike_id INTEGER NOT NULL REFERENCES bike (id) ON DELETE CASCADE,
    category VARCHAR(255) NOT NULL, subcategory VARCHAR(255) NOT NULL, component_order INTEGER NOT NULL,
    element_name VARCHAR(512) NOT NULL, element_description TEXT NOT NULL, element_order INTEGER NOT NULL,
    is_linkable BOOLEAN NOT NULL DEFAULT 1, spec_key VARCHAR(255), spec_value VARCHAR(1024), spec_order INTEGER,
    equipment_id INTEGER REFERENCES equipment (id) ON DELETE SET NULL, PRIMARY KEY (id));
"""

COMPONENTS = [  # (id, equipment_detail_id, category, sub, comp_order, element, desc, el_order, key, value, spec_order)
    (1, 10, "Protection", "Shell", 0, "In-mould shell", "opis", 0, "Weight", "400 g", 0),
    (2, 10, "Protection", "Shell", 0, "In-mould shell", "opis", 0, "MIPS", "no", 1),
    (3, 12, "Protection", "Straps", 0, "Strap", "", 0, None, None, None),
    (4, 99, "Protection", "Pads", 1, "Pad", "", 0, "Size", "S", 0),  # no equipment_detail 99: an orphan
]


def _old_db(path: Path, orphan=True, collision=False) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(OLD_DDL)
    conn.execute("INSERT INTO bike (id, brand, model) VALUES (1, 'Canyon', 'Grizl')")
    conn.executemany(
        "INSERT INTO equipment (id, category, company, model, company_norm, model_norm, created_at) "
        "VALUES (?,?,?,?,?,?,'2026-09-01 10:00:00.000000')",
        [(1, "helmets", "", "Abus Hyban 2.0", "", "abus hyban 2.0"),
         (2, "locks", "", "Plain Lock", "", "plain lock"),                      # photos only, no detail row
         (3, "apparel", "POC", "Octal MIPS", "poc", "octal mips")]               # an older row that has a company
        + ([(4, "apparel", "", "POC Octal MIPS", "", "poc octal mips")] if collision else []))
    conn.execute("INSERT INTO equipment_detail VALUES (10, 1, ?, 'Krotko.', '2026-09-01 10:00:00', '2026-09-02 11:00:00')", (D1,))
    conn.execute("INSERT INTO equipment_detail VALUES (12, 3, ?, '', '2026-09-01 10:00:00', '2026-09-03 12:00:00')", (D3,))
    conn.executemany("INSERT INTO equipment_detail_component VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     COMPONENTS if orphan else COMPONENTS[:3])
    conn.executemany("INSERT INTO equipment_detail_photos (id, equipment_id, url, display_order) VALUES (?,?,?,?)",
                     [(1, 2, "https://a/1.jpg", 0), (2, 2, "https://a/2.jpg", 1)])
    conn.execute("INSERT INTO bike_component (id, bike_id, category, subcategory, component_order, element_name, "
                 "element_description, element_order, equipment_id) VALUES "
                 "(1, 1, 'Accessories', 'Helmet', 0, 'Abus Hyban 2.0', '', 0, 1)")
    conn.commit()
    conn.close()
    return path


def _q(path, sql):
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(sql).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def _tables(path):
    return {r[0] for r in _q(path, "SELECT name FROM sqlite_master WHERE type = 'table'")}


def test_dry_run_changes_nothing(tmp_path):
    path = _old_db(tmp_path / "old.db")
    report = migrate(path, dry_run=True, verbose=False)
    assert report["status"] == "dry-run" and report["equipment_before"] == 3 and report["details_before"] == 2
    assert len(report["orphans"]) == 1 and report["rows_before"] == 4
    assert {"equipment_detail", "equipment_detail_component"} <= _tables(path)
    assert "equipment_component" not in _tables(path) and "equipment_component_orphans" not in _tables(path)
    assert "name" not in [r[1] for r in _q(path, "PRAGMA table_info(equipment)")]


def test_migrates_equipment_components_and_orphans(tmp_path):
    path = _old_db(tmp_path / "old.db")
    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and report["verified"] and report["error"] is None
    assert (report["equipment_before"], report["equipment_after"]) == (3, 3)
    assert (report["rows_before"], report["rows_after"]) == (4, 3)
    assert [o["id"] for o in report["orphans"]] == [4]

    assert {"equipment", "equipment_component", "equipment_detail_photos"} <= _tables(path)
    assert not {"equipment_detail", "equipment_detail_component"} & _tables(path)
    rows = _q(path, "SELECT id, category, name, name_norm, company, model, company_norm, model_norm, description, "
                    "short_description, created_at, updated_at FROM equipment ORDER BY id")
    assert rows == [
        (1, "helmets", "Abus Hyban 2.0", "abus hyban 2.0", "", "Abus Hyban 2.0", "", "abus hyban 2.0", D1, "Krotko.",
         "2026-09-01 10:00:00.000000", "2026-09-02 11:00:00"),
        (2, "locks", "Plain Lock", "plain lock", "", "Plain Lock", "", "plain lock", None, "",
         "2026-09-01 10:00:00.000000", "2026-09-01 10:00:00.000000"),   # no detail: NULL description, updated_at = created_at
        (3, "apparel", "POC Octal MIPS", "poc octal mips", "POC", "Octal MIPS", "poc", "octal mips", D3, "",
         "2026-09-01 10:00:00.000000", "2026-09-03 12:00:00"),          # the name joins company + model
    ]
    assert _q(path, "SELECT id, equipment_id, category, subcategory, component_order, element_name, element_description, "
                    "element_order, spec_key, spec_value, spec_order FROM equipment_component ORDER BY id") == [
        (1, 1, "Protection", "Shell", 0, "In-mould shell", "opis", 0, "Weight", "400 g", 0),
        (2, 1, "Protection", "Shell", 0, "In-mould shell", "opis", 0, "MIPS", "no", 1),
        (3, 3, "Protection", "Straps", 0, "Strap", "", 0, None, None, None),
    ]
    assert _q(path, "SELECT id, equipment_detail_id, equipment_id, element_name FROM equipment_component_orphans") == [
        (4, 99, None, "Pad")]
    # untouched: photos and the bike element link
    assert _q(path, "SELECT equipment_id, url FROM equipment_detail_photos ORDER BY id") == [
        (2, "https://a/1.jpg"), (2, "https://a/2.jpg")]
    assert _q(path, "SELECT equipment_id FROM bike_component") == [(1,)]
    # the schema: (category, name_norm) unique, the old identity gone, FK + indexes on the new table
    conn = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO equipment (category, name, name_norm, company, model, company_norm, model_norm) "
                     "VALUES ('helmets', 'x', 'abus hyban 2.0', '', 'x', '', 'x')")
    conn.execute("INSERT INTO equipment (category, name, name_norm, company, model, company_norm, model_norm) "
                 "VALUES ('helmets', 'Other', 'other', '', 'Abus Hyban 2.0', '', 'abus hyban 2.0')")  # same model is fine now
    fks = [(r[2], r[3], r[6]) for r in conn.execute("PRAGMA foreign_key_list(equipment_component)")]
    assert ("equipment", "equipment_id", "CASCADE") in fks
    assert any(r[1] == "ix_equipment_component_equipment_id" for r in conn.execute("PRAGMA index_list(equipment_component)"))
    conn.close()


def test_idempotent(tmp_path):
    path = _old_db(tmp_path / "old.db")
    assert migrate(path, verbose=False)["status"] == "migrated"
    again = migrate(path, verbose=False)
    assert again["status"] == "already-migrated" and again["equipment_after"] == 3 and again["rows_after"] == 3
    assert migrate(path, dry_run=True, verbose=False)["status"] == "already-migrated"


def test_empty_leftovers_of_old_code_are_repaired_but_filled_ones_are_refused(tmp_path):
    path = _old_db(tmp_path / "old.db", orphan=False)
    migrate(path, verbose=False)
    conn = sqlite3.connect(path)  # what an old backend's create_all() does on the migrated database
    conn.executescript("""
        CREATE TABLE equipment_detail (id INTEGER NOT NULL, equipment_id INTEGER NOT NULL UNIQUE,
            description TEXT NOT NULL, short_description TEXT DEFAULT '' NOT NULL, created_at DATETIME, updated_at DATETIME,
            PRIMARY KEY (id));
        CREATE TABLE equipment_detail_component (id INTEGER NOT NULL, equipment_detail_id INTEGER NOT NULL,
            category VARCHAR(255) NOT NULL, subcategory VARCHAR(255) NOT NULL, component_order INTEGER NOT NULL,
            element_name VARCHAR(512) NOT NULL, element_description TEXT NOT NULL, element_order INTEGER NOT NULL,
            spec_key VARCHAR(255), spec_value VARCHAR(1024), spec_order INTEGER, PRIMARY KEY (id));""")
    conn.execute("INSERT INTO equipment_detail VALUES (1, 1, '{}', '', NULL, NULL)")
    conn.commit()
    conn.close()
    refused = migrate(path, verbose=False)
    assert refused["status"] == "failed" and "equipment_detail" in refused["error"]
    assert "equipment_detail" in _tables(path), "a refusal writes nothing"

    _q(path, "DELETE FROM equipment_detail")
    assert migrate(path, dry_run=True, verbose=False)["status"] == "dry-run"
    assert "equipment_detail" in _tables(path)
    assert migrate(path, verbose=False)["status"] == "repaired"
    assert not {"equipment_detail", "equipment_detail_component"} & _tables(path)
    assert migrate(path, verbose=False)["status"] == "already-migrated"
    assert _q(path, "SELECT COUNT(*) FROM equipment_component") == [(3,)]


def test_missing_component_table_is_created_on_a_merged_database(tmp_path):
    path = _old_db(tmp_path / "old.db")
    migrate(path, verbose=False)
    _q(path, "DROP TABLE equipment_component")
    assert migrate(path, verbose=False)["status"] == "repaired"
    assert "equipment_component" in _tables(path)


def test_empty_component_table_created_too_early_by_the_new_backend(tmp_path):
    """The new backend's create_all() ran on the unmigrated database: an empty equipment_component is in the way."""
    path = _old_db(tmp_path / "old.db")
    _q(path, "CREATE TABLE equipment_component (id INTEGER NOT NULL PRIMARY KEY, equipment_id INTEGER NOT NULL)")
    assert migrate(path, verbose=False)["status"] == "migrated"
    assert _q(path, "SELECT COUNT(*) FROM equipment_component") == [(3,)]


def test_duplicate_name_is_refused_and_nothing_changes(tmp_path):
    path = _old_db(tmp_path / "old.db", collision=True)  # ("", "POC Octal MIPS") vs ("POC", "Octal MIPS")
    report = migrate(path, verbose=False)
    assert report["status"] == "failed" and "name_norm" in report["error"]
    assert "name" not in [r[1] for r in _q(path, "PRAGMA table_info(equipment)")]
    assert {"equipment_detail", "equipment_detail_component"} <= _tables(path)


def test_refuses_before_the_component_rename(tmp_path):
    path = _old_db(tmp_path / "old.db")
    _q(path, "ALTER TABLE bike_component RENAME TO bike_detail_component")
    report = migrate(path, verbose=False)
    assert report["status"] == "failed" and "migrate_rename_bike_component.py" in report["error"]


def test_no_equipment_table_is_left_to_init_db(tmp_path):
    path = tmp_path / "empty.db"
    sqlite3.connect(path).close()
    assert migrate(path, verbose=False)["status"] == "absent"


def test_equipment_tables_script_leaves_the_old_layout_to_the_merge(tmp_path):
    path = _old_db(tmp_path / "old.db")
    _q(path, "ALTER TABLE bike_component RENAME TO bike_detail_component")  # that script runs before the rename
    report = migrate_equipment_tables(path, verbose=False)
    assert report["status"] != "failed" and not report["tables_created"], report  # (it adds a missing index only)
    assert "equipment_component" not in _tables(path), "no table is created next to the old layout"
    _q(path, "ALTER TABLE bike_detail_component RENAME TO bike_component")
    assert migrate(path, verbose=False)["status"] == "migrated"
    _q(path, "ALTER TABLE bike_component RENAME TO bike_detail_component")
    assert migrate_equipment_tables(path, verbose=False)["status"] == "already-migrated"


def test_migrated_database_works_with_the_orm(tmp_path, monkeypatch):
    path = _old_db(tmp_path / "old.db")
    assert migrate(path, verbose=False)["status"] == "migrated"
    # The next migration in the deploy order (TODO-046): today's ORM selects equipment.part_type & co.
    assert migrate_part_search(path, verbose=False)["status"] == "migrated"
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(path)
    try:
        models.init_db()  # create_all finds every table: nothing to add, nothing recreated
        assert not {"equipment_detail", "equipment_detail_component"} & _tables(path)
        got = er.get_equipment_details(EquipmentDetailsRequest(model="Abus Hyban 2.0"))
        assert got.equipment_id == 1 and got.description.text == "Kask." and got.short_description == "Krotko."
        assert (got.company, got.model) == ("", "Abus Hyban 2.0")
        specs = got.components[0].subcategories[0].elements[0].specs
        assert [(s.key, s.value) for s in specs] == [("Weight", "400 g"), ("MIPS", "no")]
        assert got.components[0].subcategories[0].elements[0].equipment_id is None, "owner id is not an element link"
        # the migrated row with a company is found by its old pair and by the joined name
        assert er.get_equipment_details(EquipmentDetailsRequest(company="POC", model="Octal MIPS")).equipment_id == 3
        assert er.get_equipment_details(EquipmentDetailsRequest(model="poc octal mips")).equipment_id == 3
        # photos-only equipment reads empty details with its id, its photos stay reachable
        assert er.get_equipment_details(EquipmentDetailsRequest(model="Plain Lock")).equipment_id == 2
        assert er.get_equipment_photos(EquipmentPhotosRequest(model="Plain Lock")).photos == [
            "https://a/1.jpg", "https://a/2.jpg"]
        # a save on the migrated database fills the missing company / model and keeps the id
        eid = er.save_equipment_details(
            "Abus", "Hyban 2.0", "helmets",
            EquipmentDetailsResponse(
                company="Abus", model="Hyban 2.0", category="helmets",
                description=BikeDescription(text="Nowy.", segments=[], citations=[]),
                components=[BikeCategory(category="Protection", subcategories=[BikeSubcategory(
                    subcategory="Shell", elements=[ComponentElement(name="Shell", specs=[SpecItem(key="K", value="V")])])])]),
            element_name="Abus Hyban 2.0")
        assert eid == 1
        again = er.get_equipment_details(EquipmentDetailsRequest(equipment_id=1, model="x"))
        assert (again.company, again.model, again.description.text) == ("Abus", "Hyban 2.0", "Nowy.")
        assert [e.name for c in again.components for s in c.subcategories for e in s.elements] == ["Shell"]
    finally:
        models.dispose_engine()
        models._db_url = None


def test_empty_equipment_tables_migrate_and_rerun(tmp_path):
    """The real cache.db: the old tables exist but hold no rows (an empty executemany used to fail)."""
    path = _old_db(tmp_path / "old.db")
    for t in ("equipment_detail_photos", "equipment_detail_component", "equipment_detail", "equipment"):
        _q(path, f"DELETE FROM {t}")
    _q(path, "UPDATE bike_component SET equipment_id = NULL")
    report = migrate(path, verbose=False)
    assert report["status"] == "migrated" and report["verified"], report
    assert (report["equipment_after"], report["rows_after"]) == (0, 0)
    assert {"equipment_component"} <= _tables(path) and "equipment_detail" not in _tables(path)
    assert migrate(path, verbose=False)["status"] == "already-migrated"
