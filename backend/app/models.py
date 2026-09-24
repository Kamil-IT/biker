"""SQLAlchemy ORM models for bike data persistence."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from pathlib import Path
import os

Base = declarative_base()
_engine: Optional[Engine] = None
_SessionLocal = None

# Fallback when DATABASE_URL is unset: the local SQLite file (TODO-028).
DEFAULT_DB_PATH = Path(__file__).parent.parent / "cache.db"
_db_url: Optional[str] = None  # set by configure_db(); else DATABASE_URL / DEFAULT_DB_PATH


def database_url() -> str:
    """The SQLAlchemy URL in use: configure_db() > $DATABASE_URL > sqlite:///cache.db."""
    return _db_url or os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"


def configure_db(url_or_path) -> None:
    """Point the ORM at another database — a SQLAlchemy URL or a SQLite file path.

    Drops the current engine so the next get_engine()/get_session() rebuilds it.
    """
    global _db_url, _engine, _SessionLocal
    value = str(url_or_path)
    _db_url = value if "://" in value else f"sqlite:///{Path(value)}"
    if _engine is not None:
        _engine.dispose()
    _engine = None
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
        url = make_url(database_url())
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
    """Create all tables."""
    engine = get_engine()
    Base.metadata.create_all(engine)


class Bike(Base):
    """Base bike entity — shared identity across results, details, and offers."""

    __tablename__ = "bike"

    id = Column(Integer, primary_key=True)
    brand = Column(String(255), nullable=False, index=True)
    model = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    # Search results are no longer their own table — a search's rated bikes live
    # in search_bike_rating_cache (which FKs to bike). Details and offers below.
    details = relationship("BikeDetails", back_populates="bike", cascade="all, delete-orphan", uselist=False)
    offers = relationship("BikeOffer", back_populates="bike", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("brand", "model", name="uq_bike_brand_model"),)


class BikeDetails(Base):
    """Full bike specifications and details."""

    __tablename__ = "bike_detail"

    id = Column(Integer, primary_key=True)
    bike_id = Column(Integer, ForeignKey("bike.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False)  # JSON serialized BikeDescription
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    bike = relationship("Bike", back_populates="details")
    photos = relationship("BikeDetailPhoto", back_populates="details", cascade="all, delete-orphan")
    components = relationship(
        "BikeDetailComponent",
        back_populates="details",
        cascade="all, delete-orphan",
        order_by=(
            "BikeDetailComponent.component_order, "
            "BikeDetailComponent.element_order, "
            "BikeDetailComponent.spec_order"
        ),
    )


class BikeDetailPhoto(Base):
    """Photos for bike details."""

    __tablename__ = "bike_detail_photos"

    id = Column(Integer, primary_key=True)
    bike_detail_id = Column(Integer, ForeignKey("bike_detail.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    display_order = Column(Integer, default=0)

    # Relationships
    details = relationship("BikeDetails", back_populates="photos")


# --- Component spec tree -------------------------------------------------
# The category -> subcategory -> element -> spec tree that used to live in a
# single `bike_details.components` TEXT blob, flattened into ONE fully
# denormalised table: one row per spec, carrying its element, subcategory and
# category alongside it. Components stay queryable across bikes ("every bike
# running a Shimano GRX rear derailleur") without any join.


class BikeDetailComponent(Base):
    """One spec row, with its whole ancestry denormalised onto it.

    ('Frame', 'Fork', 'Canyon FK0143 CF', 'Weight', '580 g')

    Reconstructing the nested response means grouping by the three *_order
    columns, NOT by name: order alone is authoritative, so two elements sharing
    a name inside one subcategory stay distinct instead of silently merging.

    An element with no specs still gets exactly one row, with spec_key /
    spec_value / spec_order all NULL — that is how `specs: []` survives the
    round-trip. NULL means "no spec here", distinct from a spec whose key is "".
    """

    __tablename__ = "bike_detail_component"

    id = Column(Integer, primary_key=True)
    bike_detail_id = Column(Integer, ForeignKey("bike_detail.id", ondelete="CASCADE"), nullable=False, index=True)

    # category / subcategory level — repeat across the rows that share them
    category = Column(String(255), nullable=False, index=True)
    subcategory = Column(String(255), nullable=False, index=True)
    component_order = Column(Integer, nullable=False, default=0)

    # element level — repeats across that element's spec rows
    element_name = Column(String(512), nullable=False, index=True)
    element_description = Column(Text, nullable=False, default="")
    element_order = Column(Integer, nullable=False, default=0)

    # spec level — NULL when the element carries no specs at all
    spec_key = Column(String(255), nullable=True, index=True)
    spec_value = Column(String(1024), nullable=True)
    spec_order = Column(Integer, nullable=True)

    # Relationships
    details = relationship("BikeDetails", back_populates="components")


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


# --- Search cache --------------------------------------------------------
# One cached search query fans out to many rated bikes. `search_cache` holds
# just the query and when it was stored; each bike it returned is one row in
# `search_bike_rating_cache`, which FKs to the canonical `bike`. This replaces
# the earlier design where `search_cache.bikes` was a JSON array of ids.


class SearchCache(Base):
    """One cached search. Its rated bikes live in search_bike_rating_cache.

    Freshness is `time_stored + store.SEARCH_TTL_SECONDS` (24 h), a module
    constant rather than a per-row column — mirrors how details TTL works.
    """

    __tablename__ = "search_cache"

    id = Column(Integer, primary_key=True)
    query = Column(Text, nullable=False, unique=True, index=True)
    time_stored = Column(String(64), nullable=False)  # ISO-8601 UTC

    # Relationships
    ratings = relationship(
        "SearchBikeRating",
        back_populates="search",
        cascade="all, delete-orphan",
        order_by="SearchBikeRating.display_order",
    )


class SearchBikeRating(Base):
    """One bike returned by one cached search — one row = one bike.

    Carries the per-*search* fields (rating, explanation, accessories) while
    the bike identity is a FK to `bike`. accessories is an inline JSON array of
    strings; brand/model are NOT duplicated here, they come via the `bike` FK.
    """

    __tablename__ = "search_bike_rating_cache"

    id = Column(Integer, primary_key=True)
    search_cache_id = Column(
        Integer, ForeignKey("search_cache.id", ondelete="CASCADE"), nullable=False, index=True
    )
    bike_id = Column(Integer, ForeignKey("bike.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Float, nullable=False)
    explanation = Column(Text, nullable=False, default="")
    accessories = Column(Text, nullable=False, default="[]")  # JSON array of strings
    display_order = Column(Integer, nullable=False, default=0)

    # Relationships
    search = relationship("SearchCache", back_populates="ratings")
    bike = relationship("Bike")


# --- Missing-data requests (TODO-026) ------------------------------------
# A user clicked "Request data" on an empty section of a bike's details view.
# One row per (bike, section); every later click on the same pair bumps
# `counter`, so the table ranks which data users want filled in first.


class BikeMissingRequest(Base):
    """How many times users asked for one missing section of one bike.

    `missing_type` is a free string owned by the frontend (photos, description,
    components, review, offers_new, offers_used); the backend only bounds it.
    """

    __tablename__ = "bike_missing_request"

    id = Column(Integer, primary_key=True)
    bike_id = Column(Integer, ForeignKey("bike.id", ondelete="CASCADE"), nullable=False, index=True)
    missing_type = Column(String(64), nullable=False)
    counter = Column(Integer, nullable=False, default=1)

    # Relationships
    bike = relationship("Bike")

    __table_args__ = (UniqueConstraint("bike_id", "missing_type", name="uq_missing_bike_type"),)


# --- Generic endpoint response cache ---------------------------------------
# The per-endpoint response cache read/written by app/cache.py. A Core table,
# not an ORM class: it has no primary key (rows are identified by the
# (endpoint, request) pair). Declared here so create_all() builds it on a fresh
# PostgreSQL database alongside everything else (TODO-028).

endpoint_req_to_body_cache = Table(
    "endpoint_req_to_body_cache",
    Base.metadata,
    Column("endpoint", Text, nullable=False),
    Column("request", Text, nullable=False),
    Column("response", Text, nullable=False),
    Column("time_stored", Text, nullable=False),  # ISO-8601 UTC
    UniqueConstraint("endpoint", "request"),
)
