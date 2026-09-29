"""Shared fixtures: every test runs against a throwaway SQLite file, never the real database."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import db  # noqa: E402  (puts backend/ on sys.path)


@pytest.fixture
def temp_db(tmp_path):
    """Repoint the backend ORM at a fresh temp SQLite file with all tables created."""
    prev = db.models._db_url
    db.models.configure_db(tmp_path / "test.db")
    db.models.init_db()  # every backend table + bike_discovery (registered on the shared Base)
    db.ensure_table()
    yield db
    db.models.dispose_engine()
    db.models._db_url = prev
