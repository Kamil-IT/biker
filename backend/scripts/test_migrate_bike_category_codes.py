"""Unit tests for scripts/migrate_bike_category_codes.py (TODO-047) on throwaway SQLite files,
plus the ck_bike_category constraint init_db() creates. The PostgreSQL path (LOCK, ADD
CONSTRAINT) is not covered here — rehearse it on a PostgreSQL copy.
No server, no network, no AI. Run: cd backend && pytest   (collected via pytest.ini)"""
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import models  # noqa: E402
from migrate_bike_category_codes import migrate  # noqa: E402

OLD = [
    (1, "MTB"), (2, "Triathlon"), (3, "Dirt/Street"), (4, "Cyclocross"), (5, "City"), (6, "Cross"),
    (7, "Hybrid/Commuter"), (8, "Cruiser"), (9, "Trekking"), (10, "Youth"), (11, "Balance"),
    (12, "Kids"), (13, None), (14, "Road"),
]
NEW = [
    (1, "MTB"), (2, "Road"), (3, "MTB"), (4, "Gravel"), (5, "City/Cross/Hybrid"), (6, "City/Cross/Hybrid"),
    (7, "City/Cross/Hybrid"), (8, "City/Cross/Hybrid"), (9, "Touring"), (10, "Kids"), (11, "Kids"),
    (12, "Kids"), (13, None), (14, "Road"),
]


def _old_db(path: Path, rows=OLD, column: bool = True) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE bike (id INTEGER PRIMARY KEY, brand VARCHAR(255) NOT NULL, model VARCHAR(255) NOT NULL"
                + (", category VARCHAR(32)" if column else "") + ")")
    if column:
        con.executemany("INSERT INTO bike (id, brand, model, category) VALUES (?, 'B', ?, ?)",
                        [(i, f"m{i}", c) for i, c in rows])
    else:
        con.executemany("INSERT INTO bike (id, brand, model) VALUES (?, 'B', ?)", [(i, f"m{i}") for i, _ in rows])
    con.commit()
    con.close()
    return path


def _rows(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT id, category FROM bike ORDER BY id").fetchall()
    finally:
        con.close()


def test_old_values_become_codes(tmp_path):
    db = _old_db(tmp_path / "old.db")
    report = migrate(db, verbose=False)
    assert report["status"] == "migrated" and report["verified"] and report["error"] is None
    assert _rows(db) == NEW
    assert report["renamed"]["Trekking -> Touring"] == 1 and report["renamed"]["City -> City/Cross/Hybrid"] == 1
    assert report["constraint"] == "skipped", "SQLite cannot add a CHECK to an existing table"


def test_rerun_is_already_migrated(tmp_path):
    db = _old_db(tmp_path / "old.db")
    migrate(db, verbose=False)
    report = migrate(db, verbose=False)
    assert report["status"] == "already-migrated" and report["renamed"] == {}
    assert _rows(db) == NEW


def test_electric_is_refused_without_the_flag(tmp_path):
    db = _old_db(tmp_path / "old.db", OLD + [(15, "Electric"), (16, "Electric cargo")])
    report = migrate(db, verbose=False)
    assert report["status"] == "failed" and "reclassify_ebikes.py" in report["error"]
    assert _rows(db) == OLD + [(15, "Electric"), (16, "Electric cargo")], "nothing written"


def test_electric_to_null(tmp_path):
    db = _old_db(tmp_path / "old.db", OLD + [(15, "Electric"), (16, "Electric cargo")])
    report = migrate(db, electric_to_null=True, verbose=False)
    assert report["status"] == "migrated" and report["electric_to_null"] == 2
    assert _rows(db) == NEW + [(15, None), (16, None)]


def test_unknown_value_is_refused(tmp_path):
    db = _old_db(tmp_path / "old.db", [(1, "MTB"), (2, "Fatbike")])
    report = migrate(db, electric_to_null=True, verbose=False)
    assert report["status"] == "failed" and "Fatbike" in report["error"]
    assert _rows(db) == [(1, "MTB"), (2, "Fatbike")]


def test_dry_run_writes_nothing(tmp_path):
    db = _old_db(tmp_path / "old.db")
    report = migrate(db, dry_run=True, verbose=False)
    assert report["status"] == "dry-run" and report["after"]["City/Cross/Hybrid"] == 4
    assert _rows(db) == OLD


def test_missing_column_and_absent_table(tmp_path):
    report = migrate(_old_db(tmp_path / "nocol.db", column=False), verbose=False)
    assert report["status"] == "failed" and "migrate_bike_category.py" in report["error"]
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert migrate(empty, verbose=False)["status"] == "absent"


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_db_url", None)
    models.configure_db(tmp_path / "fresh.db")
    models.init_db()
    yield tmp_path / "fresh.db"
    models.dispose_engine()
    models._db_url = None


def test_init_db_creates_the_constraint(fresh_db):
    with models.get_session() as s:
        s.add(models.Bike(brand="A", model="Ok", category="Touring"))
        s.add(models.Bike(brand="A", model="Unknown", category=None))
        s.commit()
        s.add(models.Bike(brand="A", model="Old", category="Trekking"))
        with pytest.raises(IntegrityError):
            s.commit()
    report = migrate(fresh_db, verbose=False)
    assert report["status"] == "already-migrated" and report["constraint"] == "present"
