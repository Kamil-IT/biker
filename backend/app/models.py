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
from sqlalchemy.orm import relationship, sessionmaker
from pathlib import Path

Base = declarative_base()
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        db_path = Path(__file__).parent.parent / "cache.db"
        _engine = create_engine(
            f"sqlite:///{db_path}",
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
