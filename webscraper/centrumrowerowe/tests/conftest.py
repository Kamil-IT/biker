"""Shared fixtures: every test runs against a throwaway SQLite file, never the real database."""
import sys
from datetime import timedelta
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import db  # noqa: E402  (puts backend/ on sys.path)
from sqlalchemy import (  # noqa: E402
    Column, DateTime, ForeignKey, Index, Integer, MetaData, String, Table, Text, UniqueConstraint,
)

# bike_discovery as TODO-036 created it (the layout migrate_discovery_listings.py migrates from).
OLD_METADATA = MetaData()
OLD_BIKE_DISCOVERY = Table(
    "bike_discovery", OLD_METADATA,
    Column("id", Integer, primary_key=True),
    Column("source", String(50), nullable=False),
    Column("source_product_id", String(64), nullable=False),
    Column("raw_name", String(512), nullable=False),
    Column("company", String(255), nullable=False),
    Column("model", String(255), nullable=False),
    Column("bike_type", String(64), nullable=True),
    Column("details_link", String(2048), nullable=True),
    Column("price", String(100), nullable=True),
    Column("status", String(16), nullable=False, server_default="pending"),
    Column("attempts", Integer, nullable=False, server_default="0"),
    Column("last_error", Text, nullable=True),
    Column("locked_at", DateTime, nullable=True),
    Column("next_attempt_at", DateTime, nullable=True),
    Column("bike_id", Integer, ForeignKey(db.models.Bike.__table__.c.id, ondelete="SET NULL"), nullable=True),
    Column("first_seen_at", DateTime, nullable=False),
    Column("last_seen_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    UniqueConstraint("source", "source_product_id", name="uq_bike_discovery_source_product"),
    Index("ix_bike_discovery_status_next_attempt", "status", "next_attempt_at"),
)


def old_row(pid: str, company: str = "ROMET", model: str = "Wagant 3", **kw) -> dict:
    """One old-layout row with sensible defaults; `kw` overrides any column (status, bike_id, ...)."""
    now = db.utcnow().replace(tzinfo=None)
    return {
        "source": db.SOURCE, "source_product_id": pid, "raw_name": f"Rower {company} {model}",
        "company": company, "model": model, "bike_type": "trekkingowy",
        "details_link": f"https://www.centrumrowerowe.pl/rower-{pid}/", "price": "1999.00",
        "status": db.PENDING, "attempts": 0, "first_seen_at": now - timedelta(days=1), "last_seen_at": now,
        "updated_at": now, **kw,
    }


@pytest.fixture
def temp_db(tmp_path):
    """Repoint the backend ORM at a fresh temp SQLite file with all tables created."""
    prev = db.models._db_url
    db.models.configure_db(tmp_path / "test.db")
    db.models.init_db()  # every backend table + both discovery tables (registered on the shared Base)
    db.ensure_table()
    yield db
    db.models.dispose_engine()
    db.models._db_url = prev


@pytest.fixture
def old_layout_db(tmp_path):
    """A temp SQLite file with every backend table but `bike_discovery` in its TODO-036 layout.

    Yields `insert(*rows)`: each row is a dict of old columns (build it with `old_row`); returns
    the inserted ids. `bike_discovery_listing` does not exist.
    """
    prev = db.models._db_url
    db.models.configure_db(tmp_path / "old.db")
    db.models.init_db()
    engine = db.models.get_engine()
    for table in reversed(db.TABLES):  # init_db created the new layout; replace it with the old one
        table.drop(engine)
    OLD_BIKE_DISCOVERY.create(engine)

    def insert(*rows: dict) -> list[int]:
        with engine.begin() as conn:
            return [conn.execute(OLD_BIKE_DISCOVERY.insert().values(**row)).inserted_primary_key[0] for row in rows]

    yield insert
    db.models.dispose_engine()
    db.models._db_url = prev
