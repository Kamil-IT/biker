"""SQLAlchemy engine helpers and the ten tables the searcher touches.

The DDL below is a verbatim copy of `bike`, `bike_offer`, `bike_offer_photos`,
`bike_detail_photos`, `bike_review`, `bike_review_source`,
`bike_component` and (TODO-042 / TODO-044) `equipment`, `equipment_component`,
`equipment_detail_photos` in
backend/app/models.py — same names, columns, constraints and index names —
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
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    inspect,
    true,
)
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, validates

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


REQUIRED_TABLES = (
    "bike", "bike_offer", "bike_offer_photos", "bike_detail_photos", "bike_review", "bike_review_source",
    "bike_component",
    "equipment", "equipment_component", "equipment_detail_photos",
)


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
    inspector = inspect(engine)
    # The component table was renamed; create_all() never renames, so an older database
    # still has bike_detail_component and every details write / read would miss it.
    if inspector.has_table("bike_detail_component") and not inspector.has_table("bike_component"):
        raise RuntimeError(
            "the database still has the bike_detail_component table (bike_component missing) — run "
            "backend/scripts/migrate_rename_bike_component.py on this database first"
        )
    # TODO-044: equipment_detail was merged into equipment (description / short_description / name) and
    # its component table renamed equipment_component; create_all() never ALTERs, so an older database
    # lacks the columns and the equipment saves would fail.
    if inspector.has_table("equipment") and (
        "name" not in {c["name"] for c in inspector.get_columns("equipment")}
        or inspector.has_table("equipment_detail")
        or inspector.has_table("equipment_detail_component")
        or not inspector.has_table("equipment_component")
    ):
        raise RuntimeError(
            "the database still has the equipment_detail / equipment_detail_component tables (equipment has no "
            "name column / equipment_component is missing) — run backend/scripts/migrate_merge_equipment_detail.py "
            "on this database first"
        )
    missing = [t for t in REQUIRED_TABLES if not inspector.has_table(t)]
    if missing:
        raise RuntimeError(
            f"tables {missing} are missing in the database — start the backend first (its init_db() "
            "creates the schema), or set SEARCHER_CREATE_TABLES=true for a standalone database"
        )
    # A database from before photos moved to the searcher still keys bike_detail_photos
    # on bike_detail_id; every photo write would fail, so say so at startup instead.
    photo_columns = {c["name"] for c in inspector.get_columns("bike_detail_photos")}
    if "bike_id" not in photo_columns:
        raise RuntimeError(
            "bike_detail_photos has no bike_id column — run backend/scripts/migrate_photos_bike_id.py "
            "on this database first"
        )
    # Details moved onto `bike` (description / short_description) and the component table was
    # re-keyed to bike_id; create_all() never ALTERs, so an older database lacks both and every
    # details write would fail.
    bike_columns = {c["name"] for c in inspector.get_columns("bike")}
    comp_columns = {c["name"] for c in inspector.get_columns("bike_component")}
    if (
        not {"description", "short_description"} <= bike_columns
        or "bike_id" not in comp_columns
        or inspector.has_table("bike_detail")
    ):
        raise RuntimeError(
            "the database still has the bike_detail table / the component table keyed on bike_detail_id "
            "(bike has no description / short_description) — run backend/scripts/migrate_drop_bike_detail.py "
            "on this database first"
        )
    # TODO-042: bike_component gained equipment_id (the link to an equipment row); the
    # bike details save re-applies it and the equipment save sets it, so both would fail without it.
    if "equipment_id" not in comp_columns:
        raise RuntimeError(
            "bike_component has no equipment_id column — run backend/scripts/migrate_equipment_tables.py "
            "on this database first"
        )
    # ISSUE-016: every bike component row carries is_linkable; the ORM selects and inserts it,
    # so an unmigrated database would fail on the first details read or write.
    if "is_linkable" not in comp_columns:
        raise RuntimeError(
            "bike_component has no is_linkable column — run backend/scripts/migrate_component_linkable.py "
            "on this database first"
        )
    # Bike photos carry bg_color (the tile's edge colour); the photo save inserts it.
    if "bg_color" not in photo_columns:
        raise RuntimeError(
            "bike_detail_photos has no bg_color column — run backend/scripts/migrate_photo_bg_color.py "
            "on this database first"
        )


def norm(value: Optional[str]) -> str:
    """Identity form of a name: `strip().lower()` in Python — never SQL lower(), SQLite's is ASCII-only."""
    return (value or "").strip().lower()


class Bike(Base):
    """Base bike entity — shared identity across results, details, and offers."""

    __tablename__ = "bike"

    id = Column(Integer, primary_key=True)
    brand = Column(String(255), nullable=False, index=True)
    model = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Details live on the bike itself: description = JSON BikeDescription (NULL = no details),
    # short_description = two-sentence Polish summary ('' = none).
    description = Column(Text, nullable=True)
    short_description = Column(Text, nullable=False, default="", server_default="")

    # Relationships
    components = relationship(
        "BikeComponent",
        back_populates="bike",
        cascade="all, delete-orphan",
        order_by=(
            "BikeComponent.component_order, "
            "BikeComponent.element_order, "
            "BikeComponent.spec_order"
        ),
    )
    offers = relationship("BikeOffer", back_populates="bike", cascade="all, delete-orphan")
    photos = relationship(
        "BikeDetailPhoto", back_populates="bike", cascade="all, delete-orphan",
        order_by="BikeDetailPhoto.display_order, BikeDetailPhoto.id",
    )
    review = relationship("BikeReview", back_populates="bike", uselist=False, cascade="all, delete-orphan")

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


class BikeDetailPhoto(Base):
    """Photos of a bike, keyed on the bike itself (not on its details row).

    Photos are written by the searcher's photo search and are independent of
    the bike's details: a details re-save or delete leaves them alone. The table
    kept its old name; `bike_id` replaced `bike_detail_id`
    (scripts/migrate_photos_bike_id.py migrates an existing database).
    """

    __tablename__ = "bike_detail_photos"

    id = Column(Integer, primary_key=True)
    bike_id = Column(Integer, ForeignKey("bike.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    display_order = Column(Integer, default=0)
    # The photo's own edge colour "#RRGGBB" (the results tile's frame background); NULL = not
    # computed / transparent / unknown. scripts/migrate_photo_bg_color.py adds it to an existing table.
    bg_color = Column(String(7), nullable=True)

    # Relationships
    bike = relationship("Bike", back_populates="photos")


class BikeReview(Base):
    """The bike's expert review (TODO-037) — at most one per bike, no TTL.

    Written by the searcher's review search (/v1/search/review), only when the
    run found at least one source; read by the backend's /v1/bike/review.
    """

    __tablename__ = "bike_review"

    id = Column(Integer, primary_key=True)
    bike_id = Column(Integer, ForeignKey("bike.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    score = Column(Integer, nullable=False, default=0)
    explanation = Column(Text, nullable=False, default="")
    rating = Column(Float, nullable=False, default=0.0)
    sources_used = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    bike = relationship("Bike", back_populates="review")
    sources = relationship(
        "BikeReviewSource", back_populates="review", cascade="all, delete-orphan",
        order_by="BikeReviewSource.display_order, BikeReviewSource.id",
    )


class BikeReviewSource(Base):
    """One source URL of a bike review; display_order keeps the tier-sorted `ref` order."""

    __tablename__ = "bike_review_source"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("bike_review.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    display_order = Column(Integer, nullable=False, default=0)

    # Relationships
    review = relationship("BikeReview", back_populates="sources")


class BikeComponent(Base):
    """One spec row, with its whole ancestry denormalised onto it (see backend/app/models.py)."""

    __tablename__ = "bike_component"

    id = Column(Integer, primary_key=True)
    bike_id = Column(Integer, ForeignKey("bike.id", ondelete="CASCADE"), nullable=False, index=True)

    category = Column(String(255), nullable=False, index=True)
    subcategory = Column(String(255), nullable=False, index=True)
    component_order = Column(Integer, nullable=False, default=0)

    element_name = Column(String(512), nullable=False, index=True)
    element_description = Column(Text, nullable=False, default="")
    element_order = Column(Integer, nullable=False, default=0)
    # ISSUE-016 — the model's verdict whether the name is a linkable product (see backend/app/models.py).
    is_linkable = Column(Boolean, nullable=False, default=True, server_default=true())

    spec_key = Column(String(255), nullable=True, index=True)
    spec_value = Column(String(1024), nullable=True)
    spec_order = Column(Integer, nullable=True)

    # TODO-042: the equipment row this element opens (set by an equipment search for THIS bike only).
    equipment_id = Column(Integer, ForeignKey("equipment.id", ondelete="SET NULL"), nullable=True, index=True)

    # Relationships
    bike = relationship("Bike", back_populates="components")


class Equipment(Base):
    """One equipment item (TODO-042, merged with its details in TODO-044): helmet, light, lock, apparel/bag/accessory.

    Lookup identity = (category, name_norm): `name` is the element name from a
    bike's spec tree, the only source of an equipment row. `company` / `model`
    are the RESEARCHED brand and model: "" and the name until a details search
    fills them. `description` (JSON BikeDescription) is NULL until details are
    stored - "has details" = `description IS NOT NULL`, like `bike.description`.
    The norm columns follow company / model / name through @validates
    (construction and assignment); a Core update() must set them itself.
    """

    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True)
    category = Column(String(32), nullable=False)
    name = Column(String(512), nullable=False)
    name_norm = Column(String(512), nullable=False)
    company = Column(String(255), nullable=False, default="")
    model = Column(String(512), nullable=False)
    company_norm = Column(String(255), nullable=False)
    model_norm = Column(String(512), nullable=False)
    description = Column(Text, nullable=True)  # JSON serialized BikeDescription; NULL = no details
    short_description = Column(Text, nullable=False, default="", server_default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    components = relationship(
        "EquipmentComponent",
        back_populates="equipment",
        cascade="all, delete-orphan",
        order_by=(
            "EquipmentComponent.component_order, "
            "EquipmentComponent.element_order, "
            "EquipmentComponent.spec_order"
        ),
    )
    photos = relationship(
        "EquipmentDetailPhoto", back_populates="equipment", cascade="all, delete-orphan",
        order_by="EquipmentDetailPhoto.display_order, EquipmentDetailPhoto.id",
    )

    __table_args__ = (UniqueConstraint("category", "name_norm", name="uq_equipment_name"),)

    @validates("name", "company", "model")
    def _sync_norm(self, key, value):
        setattr(self, f"{key}_norm", norm(value))
        return value


class EquipmentComponent(Base):
    """One spec row of an equipment item - the flat shape of bike_component, keyed on the item."""

    __tablename__ = "equipment_component"

    id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False, index=True)

    category = Column(String(255), nullable=False, index=True)
    subcategory = Column(String(255), nullable=False, index=True)
    component_order = Column(Integer, nullable=False, default=0)

    element_name = Column(String(512), nullable=False, index=True)
    element_description = Column(Text, nullable=False, default="")
    element_order = Column(Integer, nullable=False, default=0)

    spec_key = Column(String(255), nullable=True, index=True)
    spec_value = Column(String(1024), nullable=True)
    spec_order = Column(Integer, nullable=True)

    # Relationships
    equipment = relationship("Equipment", back_populates="components")


class EquipmentDetailPhoto(Base):
    """Photos of an equipment item, keyed on the item (written once, never replaced)."""

    __tablename__ = "equipment_detail_photos"

    id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    display_order = Column(Integer, default=0)

    # Relationships
    equipment = relationship("Equipment", back_populates="photos")
