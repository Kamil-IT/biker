"""Unit tests for scripts/migrate_photo_bg_color.py on throwaway SQLite files.
No server, no network. Run: cd backend && pytest   (collected via pytest.ini)"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migrate_photo_bg_color import migrate  # noqa: E402


def _db(path: Path, keyed_on="bike_id", with_color=False, rows=3) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE bike (id INTEGER PRIMARY KEY)")
    color = ", bg_color VARCHAR(7)" if with_color else ""
    con.execute(
        f"CREATE TABLE bike_detail_photos (id INTEGER PRIMARY KEY, {keyed_on} INTEGER NOT NULL, "
        f"url VARCHAR(2048) NOT NULL, display_order INTEGER{color})"
    )
    for i in range(rows):
        con.execute(
            f"INSERT INTO bike_detail_photos ({keyed_on}, url, display_order) VALUES (1, ?, ?)",
            (f"https://x/{i}.jpg", i),
        )
    con.commit()
    con.close()
    return path


def _columns(path: Path) -> set[str]:
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(bike_detail_photos)")}
    con.close()
    return cols


def test_migrates_and_keeps_rows(tmp_path):
    db = _db(tmp_path / "a.db")
    r = migrate(db, verbose=False)
    assert r["status"] == "migrated" and r["verified"] and r["rows_before"] == r["rows_after"] == 3
    assert "bg_color" in _columns(db)
    con = sqlite3.connect(db)
    assert con.execute("SELECT COUNT(*) FROM bike_detail_photos WHERE bg_color IS NULL").fetchone()[0] == 3
    con.close()


def test_idempotent(tmp_path):
    db = _db(tmp_path / "a.db")
    assert migrate(db, verbose=False)["status"] == "migrated"
    assert migrate(db, verbose=False)["status"] == "already-migrated"


def test_dry_run_writes_nothing(tmp_path):
    db = _db(tmp_path / "a.db")
    assert migrate(db, dry_run=True, verbose=False)["status"] == "dry-run"
    assert "bg_color" not in _columns(db)


def test_absent_table(tmp_path):
    db = tmp_path / "a.db"
    sqlite3.connect(db).close()
    assert migrate(db, verbose=False)["status"] == "absent"


def test_refuses_old_key(tmp_path):
    db = _db(tmp_path / "a.db", keyed_on="bike_detail_id")
    r = migrate(db, verbose=False)
    assert r["status"] == "failed" and "migrate_photos_bike_id" in r["error"]
    assert "bg_color" not in _columns(db)


def test_already_has_column(tmp_path):
    db = _db(tmp_path / "a.db", with_color=True)
    assert migrate(db, verbose=False)["status"] == "already-migrated"


def test_empty_table(tmp_path):
    db = _db(tmp_path / "a.db", rows=0)
    r = migrate(db, verbose=False)
    assert r["status"] == "migrated" and r["rows_after"] == 0
