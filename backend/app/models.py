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

    __tablename__ = "bikes"

    id = Column(Integer, primary_key=True)
    brand = Column(String(255), nullable=False, index=True)
    model = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    results = relationship("BikeResult", back_populates="bike", cascade="all, delete-orphan")
    details = relationship("BikeDetails", back_populates="bike", cascade="all, delete-orphan", uselist=False)
    offers = relationship("BikeOffer", back_populates="bike", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("brand", "model", name="uq_bike_brand_model"),)


class BikeResult(Base):
    """Search result — one bike from a search query."""

    __tablename__ = "bike_results"

    id = Column(Integer, primary_key=True)
    bike_id = Column(Integer, ForeignKey("bikes.id", ondelete="CASCADE"), nullable=False, index=True)
    match_score = Column(Float, nullable=False)
    explanation = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
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
