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
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, validates
from pathlib import Path

Base = declarative_base()
_engine = None
_SessionLocal = None


DEFAULT_DB_PATH = Path(__file__).parent.parent / "cache.db"


def norm(text: str) -> str:
    """The canonical identity form of a brand or model.

    Python's `str.lower()` — NOT SQLite's `lower()`/`LIKE`, which are ASCII-only
    and leave characters like `Ü` untouched. That difference is why `bikes`
    carries `brand_norm`/`model_norm` columns instead of lowercasing in SQL.
    """
    return text.strip().lower()


def configure_db(db_path) -> None:
    """Point the ORM at a different SQLite file (migrations, tests).

    Rebuilds the engine and session factory, so call it before any session is
    opened. Pass `None` to go back to the default `backend/cache.db`.
    """
    global _engine, _SessionLocal
    path = DEFAULT_DB_PATH if db_path is None else db_path
    _engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    _SessionLocal = sessionmaker(bind=_engine)


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            f"sqlite:///{DEFAULT_DB_PATH}",
            connect_args={"check_same_thread": False},
            echo=False,
        )
    return _engine


def get_session():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def init_db():
    """Create all tables.

    NOTE: `create_all` creates *missing tables* only — it never ALTERs a table
    that already exists. A database created by an older build therefore keeps
    its old columns and no error is raised here. `verify_schema()` is what
    catches that; call it at startup, after this.
    """
    engine = get_engine()
    Base.metadata.create_all(engine)


class SchemaMismatchError(RuntimeError):
    """The live database is missing tables/columns the ORM expects."""


def verify_schema(raise_on_mismatch: bool = True) -> list[str]:
    """Compare every mapped table against the live schema.

    Exists because `create_all()` silently tolerates an out-of-date table, and
    the resulting failures surface deep inside cache helpers whose exception
    handlers treat everything as non-fatal — so a half-migrated database looks
    exactly like a cold cache while the feature is entirely dead. This turns
    that into a refusal to start.

    Deliberately NOT called from `init_db()`: the migration script calls
    `init_db()` before it ALTERs anything, and it is the one tool that must be
    allowed to open a database whose schema is out of date.
    """
    from sqlalchemy import inspect  # local import — keeps module import cheap

    inspector = inspect(get_engine())
    problems: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            problems.append(f"{table_name}: table is missing entirely")
            continue
        live = {c["name"] for c in inspector.get_columns(table_name)}
        missing = [c.name for c in table.columns if c.name not in live]
        if missing:
            problems.append(f"{table_name}: missing column(s) {', '.join(missing)}")

    if problems and raise_on_mismatch:
        raise SchemaMismatchError(
            "Database schema is out of date:\n  - "
            + "\n  - ".join(problems)
            + "\n\n`init_db()` creates missing tables but never ALTERs an existing one, "
            "so this cannot fix itself.\nRun:  python scripts/migrate_bike_details.py"
            f"\nAgainst: {DEFAULT_DB_PATH}"
        )
    return problems


class Bike(Base):
    """Base bike entity — shared identity across results, details, and offers."""

    __tablename__ = "bikes"

    id = Column(Integer, primary_key=True)
    brand = Column(String(255), nullable=False, index=True)
    model = Column(String(255), nullable=False, index=True)
    # Lookup keys: `norm()` of brand/model. Real casing stays in brand/model;
    # every identity lookup goes through these so "Riese & Müller" and
    # "riese & müller" resolve to one row.
    brand_norm = Column(String(255), nullable=False, server_default="", index=True)
    model_norm = Column(String(255), nullable=False, server_default="", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    results = relationship("BikeResult", back_populates="bike", cascade="all, delete-orphan")
    details = relationship("BikeDetails", back_populates="bike", cascade="all, delete-orphan", uselist=False)
    offers = relationship("BikeOffer", back_populates="bike", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("brand", "model", name="uq_bike_brand_model"),
        UniqueConstraint("brand_norm", "model_norm", name="uq_bike_brand_model_norm"),
    )

    @validates("brand", "model")
    def _sync_norm(self, key: str, value: str) -> str:
        """Keep brand_norm/model_norm in lockstep with brand/model.

        A `@validates` handler rather than an `__init__` override so it also
        fires on later assignment (`bike.brand = "..."`), which would otherwise
        leave a stale norm column and break every subsequent lookup. It does
        NOT fire on a bulk `query().update()` — use the ORM for brand/model
        edits, or write both columns yourself.
        """
        if value is not None:
            setattr(self, f"{key}_norm", norm(value))
        return value


class Search(Base):
    """One cached search — owns the query identity and its freshness.

    Without this row a search has nothing to be keyed or expired by: the query
    string is not an attribute of any single result, and TTL applies to the set
    as a whole. `bike_results` hangs off it, so results reference `bikes` by id
    instead of being flattened into a JSON blob.
    """

    __tablename__ = "searches"

    id = Column(Integer, primary_key=True)
    # The `norm()`'d enriched query — same key the blob `search_cache` used.
    query = Column(String(2048), nullable=False, unique=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    ttl_seconds = Column(Integer, default=24 * 60 * 60)  # 24 hours

    results = relationship(
        "BikeResult",
        back_populates="search",
        cascade="all, delete-orphan",
        order_by="BikeResult.position",
    )


class BikeResult(Base):
    """Search result — one bike from a search query."""

    __tablename__ = "bike_results"

    id = Column(Integer, primary_key=True)
    search_id = Column(Integer, ForeignKey("searches.id", ondelete="CASCADE"), nullable=True, index=True)
    bike_id = Column(Integer, ForeignKey("bikes.id", ondelete="CASCADE"), nullable=False, index=True)
    # The bikes are allocated by score weight, so their order is meaningful and
    # has to be stored explicitly — a row set has no inherent ordering.
    position = Column(Integer, nullable=False, default=0)
    match_score = Column(Float, nullable=False)
    explanation = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    search = relationship("Search", back_populates="results")
    bike = relationship("Bike", back_populates="results")
    accessories = relationship("Accessory", back_populates="bike_result", cascade="all, delete-orphan")


class Accessory(Base):
    """Accessory list item for a bike result."""

    __tablename__ = "accessories"

    id = Column(Integer, primary_key=True)
    bike_result_id = Column(Integer, ForeignKey("bike_results.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)

    # Relationships
    bike_result = relationship("BikeResult", back_populates="accessories")


class BikeDetails(Base):
    """Full bike specifications and details."""

    __tablename__ = "bike_details"

    id = Column(Integer, primary_key=True)
    bike_id = Column(Integer, ForeignKey("bikes.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False)  # JSON serialized BikeDescription
    components = Column(Text, nullable=False)  # JSON serialized list[BikeCategory]
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    ttl_seconds = Column(Integer, default=30 * 24 * 60 * 60)  # 30 days

    # Relationships
    bike = relationship("Bike", back_populates="details")
    photos = relationship("BikeDetailPhoto", back_populates="details", cascade="all, delete-orphan")


class BikeDetailPhoto(Base):
    """Photos for bike details."""

    __tablename__ = "bike_detail_photos"

    id = Column(Integer, primary_key=True)
    bike_details_id = Column(Integer, ForeignKey("bike_details.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    display_order = Column(Integer, default=0)

    # Relationships
    details = relationship("BikeDetails", back_populates="photos")


class BikeOffer(Base):
    """Marketplace offer/listing for a bike."""

    __tablename__ = "bike_offers"

    id = Column(Integer, primary_key=True)
    bike_id = Column(Integer, ForeignKey("bikes.id", ondelete="CASCADE"), nullable=False, index=True)
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
    bike_offer_id = Column(Integer, ForeignKey("bike_offers.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    display_order = Column(Integer, default=0)

    # Relationships
    offer = relationship("BikeOffer", back_populates="photos")
