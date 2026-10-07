"""Unit tests for scripts/migrate_equipment_part_search.py on throwaway SQLite files.
No server, no network. Run: cd backend && pytest   (collected via pytest.ini)"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from migrate_equipment_part_search import migrate  # noqa: E402

NEW = {"part_type", "groupset", "key_specs"}


def _db(path: Path, merged=True, extra="", rows=3) -> Path:
    con = sqlite3.connect(path)
    name = "name VARCHAR(512) NOT NULL, name_norm VARCHAR(512) NOT NULL, " if merged else ""
    con.execute(
        f"CREATE TABLE equipment (id INTEGER PRIMARY KEY, category VARCHAR(32) NOT NULL, {name}"
        f"company VARCHAR(255) NOT NULL, model VARCHAR(512) NOT NULL{extra})"
    )
    for i in range(rows):
        if merged:
            con.execute("INSERT INTO equipment (category, name, name_norm, company, model) VALUES ('parts', ?, ?, '', ?)",
                        (f"Part {i}", f"part {i}", f"Part {i}"))
        else:
            con.execute("INSERT INTO equipment (category, company, model) VALUES ('parts', '', ?)", (f"Part {i}",))
    con.commit()
    con.close()
    return path


def _columns(path: Path) -> set[str]:
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(equipment)")}
    con.close()
    return cols


def test_migrates_and_keeps_rows(tmp_path):
    db = _db(tmp_path / "a.db")
    r = migrate(db, verbose=False)
    assert r["status"] == "migrated" and r["verified"] and r["rows_before"] == r["rows_after"] == 3
    assert set(r["added"]) == NEW and NEW <= _columns(db)
    con = sqlite3.connect(db)
    assert con.execute(
        "SELECT COUNT(*) FROM equipment WHERE part_type IS NULL AND groupset IS NULL AND key_specs IS NULL"
    ).fetchone()[0] == 3
    con.close()


def test_idempotent(tmp_path):
    db = _db(tmp_path / "a.db")
    assert migrate(db, verbose=False)["status"] == "migrated"
    assert migrate(db, verbose=False)["status"] == "already-migrated"


def test_dry_run_writes_nothing(tmp_path):
    db = _db(tmp_path / "a.db")
    assert migrate(db, dry_run=True, verbose=False)["status"] == "dry-run"
    assert not NEW & _columns(db)


def test_absent_table(tmp_path):
    db = tmp_path / "a.db"
    sqlite3.connect(db).close()
    assert migrate(db, verbose=False)["status"] == "absent"


def test_refuses_pre_merge_layout(tmp_path):
    db = _db(tmp_path / "a.db", merged=False)
    r = migrate(db, verbose=False)
    assert r["status"] == "failed" and "migrate_merge_equipment_detail" in r["error"]
    assert not NEW & _columns(db)


def test_adds_only_the_missing_columns(tmp_path):
    db = _db(tmp_path / "a.db", extra=", part_type VARCHAR(32)")
    r = migrate(db, verbose=False)
    assert r["status"] == "migrated" and r["added"] == ["groupset", "key_specs"]
    assert NEW <= _columns(db)


def test_already_has_columns(tmp_path):
    db = _db(tmp_path / "a.db", extra=", part_type VARCHAR(32), groupset VARCHAR(128), key_specs TEXT")
    assert migrate(db, verbose=False)["status"] == "already-migrated"


def test_empty_table(tmp_path):
    db = _db(tmp_path / "a.db", rows=0)
    r = migrate(db, verbose=False)
    assert r["status"] == "migrated" and r["rows_after"] == 0
