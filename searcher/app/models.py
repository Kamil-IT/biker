"""SQLAlchemy engine helpers and the three tables the searcher touches.

The DDL below is a verbatim copy of `bike`, `bike_offer` and `bike_offer_photos`
in backend/app/models.py — same names, columns, constraints and index names —
because both services share one database. Change it there first, then here.
init_db() only checks that the tables exist — the backend creates them.
"""
import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

from . import config

Base = declarative_base()
_engine: Optional[Engine] = None
_SessionLocal = None


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    # SQLite ships with FK enforcement OFF per connection, so ON DELETE CASCADE
    # never fires unless we ask. PostgreSQL always enforces FKs.
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = make_url(config.database_url())  # RuntimeError when DATABASE_URL is unset
        if url.get_backend_name() == "sqlite":
            _engine = create_engine(url, connect_args={"check_same_thread": False}, echo=False)
            event.listen(_engine, "connect", _sqlite_pragmas)
        else:
            # timezone=UTC: the DateTime columns are naive and the app treats
            # naive as UTC, so aware values must never be shifted by the server zone.
            _engine = create_engine(
                url, pool_pre_ping=True, echo=False,
                connect_args={"options": "-c timezone=UTC"},
            )
    return _engine


def dispose_engine() -> None:
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def dialect_insert(table):
    """INSERT construct supporting on_conflict_do_update/do_nothing for the active DB."""
    if get_engine().dialect.name == "postgresql":
        return pg_insert(table)
    return sqlite_insert(table)


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def init_db():
    """Check the shared tables exist; the backend's init_db() is what creates them.

    Two services running create_all() on one fresh database at the same time
    race (create_all is check-then-create per table), so the searcher never
    creates by default — it refuses to start until the backend has, and docker
    compose restarts it. SEARCHER_CREATE_TABLES=true opts into create_all()
    for a database the backend will never touch (scratch tests).
    """
    engine = get_engine()
    if os.getenv("SEARCHER_CREATE_TABLES", "").strip().lower() in ("1", "true", "yes"):
        Base.metadata.create_all(engine)
        return
    missing = [t for t in ("bike", "bike_offer", "bike_offer_photos") if not inspect(engine).has_table(t)]
    if missing:
        raise RuntimeError(
            f"tables {missing} are missing in the database — start the backend first (its init_db() "
            "creates the schema), or set SEARCHER_CREATE_TABLES=true for a standalone database"
        )


class Bike(Base):
    """Base bike entity — shared identity across results, details, and offers."""

    __tablename__ = "bike"

    id = Column(Integer, primary_key=True)
    brand = Column(String(255), nullable=False, index=True)
    model = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    offers = relationship("BikeOffer", back_populates="bike", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("brand", "model", name="uq_bike_brand_model"),)


class BikeOffer(Base):
    """Marketplace offer/listing for a bike."""

    __tablename__ = "bike_offer"

    id = Column(Integer, primary_key=True)
    bike_id = Column(Integer, ForeignKey("bike.id", ondelete="CASCADE"), nullable=False, index=True)
    price = Column(String(100), nullable=False)
    is_new = Column(Boolean, nullable=False)
    url = Column(String(2048), nullable=False, unique=True, index=True)
    source = Column(String(50), nullable=False, index=True)  # "allegro.pl", "olx.pl", "ceneo.pl", "decathlon.pl"
    city = Column(String(255), nullable=True)  # For used listings
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at_list = Column(DateTime, nullable=True)  # When the offer was created on the marketplace

    # Relationships
    bike = relationship("Bike", back_populates="offers")
    photos = relationship("BikeOfferPhoto", back_populates="offer", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("bike_id", "url", name="uq_offer_bike_url"),)


class BikeOfferPhoto(Base):
    """Photos for bike offers."""

    __tablename__ = "bike_offer_photos"

    id = Column(Integer, primary_key=True)
    bike_offer_id = Column(Integer, ForeignKey("bike_offer.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    display_order = Column(Integer, default=0)

    # Relationships
    offer = relationship("BikeOffer", back_populates="photos")
