"""Unit tests for scripts/migrate_bike_category.py on throwaway SQLite files.
No server, no network, no AI. Run: cd backend && pytest   (collected via pytest.ini)"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migrate_bike_category import migrate  # noqa: E402


def _old_db(path: Path, discovery: bool = True) -> Path:
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE bike (
            id INTEGER PRIMARY KEY, brand VARCHAR(255) NOT NULL, model VARCHAR(255) NOT NULL,
            brand_norm VARCHAR(255) NOT NULL, model_norm VARCHAR(255) NOT NULL,
            description TEXT, short_description TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO bike (id, brand, model, brand_norm, model_norm) VALUES
            (1, 'Giant', 'Talon 3', 'giant', 'talon 3'),
            (2, 'Kross', 'Level', 'kross', 'level'),
            (3, 'Romet', 'X', 'romet', 'x'),
            (4, 'Orbea', 'Y', 'orbea', 'y'),
            (5, 'Trek', 'Marlin 5', 'trek', 'marlin 5');
    """)
    if discovery:
        con.executescript("""
            CREATE TABLE bike_discovery (id INTEGER PRIMARY KEY, bike_id INTEGER, bike_type VARCHAR(64));
            INSERT INTO bike_discovery (id, bike_id, bike_type) VALUES
                (1, 1, ' MTB '), (2, 2, 'Szosowy'), (3, 3, 'dziwny typ'), (4, 4, ''), (5, NULL, 'MTB');
        """)
    con.commit()
    con.close()
    return path


def _rows(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("SELECT id, category FROM bike ORDER BY id").fetchall()
    finally:
        con.close()


def test_migrate_adds_column_and_backfills(tmp_path):
    db = _old_db(tmp_path / "old.db")
    report = migrate(db, verbose=False)
    assert report["status"] == "migrated" and report["verified"] and report["error"] is None
    assert report["bikes_before"] == report["bikes_after"] == 5
    assert report["filled"] == 2 and report["unmapped"] == {"dziwny typ": 1}
    assert _rows(db) == [(1, "MTB"), (2, "Road"), (3, None), (4, None), (5, None)]


def test_rerun_is_already_migrated_and_keeps_existing_values(tmp_path):
    db = _old_db(tmp_path / "old.db")
    migrate(db, verbose=False)
    con = sqlite3.connect(db)
    con.execute("UPDATE bike SET category = 'Gravel' WHERE id = 1")
    con.commit()
    con.close()
    report = migrate(db, verbose=False)
    assert report["status"] == "already-migrated" and report["filled"] == 0
    assert _rows(db)[0] == (1, "Gravel")


def test_no_discovery_table(tmp_path):
    db = _old_db(tmp_path / "old.db", discovery=False)
    report = migrate(db, verbose=False)
    assert report["status"] == "migrated" and report["filled"] == 0
    assert all(c is None for _, c in _rows(db))


def test_dry_run_writes_nothing(tmp_path):
    db = _old_db(tmp_path / "old.db")
    report = migrate(db, dry_run=True, verbose=False)
    assert report["status"] == "dry-run" and report["filled"] == 2
    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(bike)")]
    con.close()
    assert "category" not in cols


def test_absent_table(tmp_path):
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    report = migrate(db, verbose=False)
    assert report["status"] == "absent" and report["verified"]
