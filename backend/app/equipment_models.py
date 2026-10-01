"""SQLAlchemy ORM models for equipment (TODO-042): helmets, lights, locks, apparel.

Registered on the shared `Base` of models.py, which imports this module at its
bottom, so `init_db()`'s create_all() builds these tables on a fresh database.
An existing database needs scripts/migrate_equipment_tables.py once (the four
tables + `bike_detail_component.equipment_id`). The searcher carries a verbatim
copy of this DDL in searcher/app/models.py — change it here first, then there.

Import the classes from here (`from app.equipment_models import Equipment`).
"""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship, validates

from .models import Base, norm


class Equipment(Base):
    """One equipment item (TODO-042): helmet, light, lock, apparel/bag/accessory.

    Identity = (category, company_norm, model_norm). Opened from a bike's spec
    tree, so company is usually "" and model is the element name. The norm
    columns follow company/model through @validates (construction and
    assignment); a Core update() must set them itself.
    """

    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True)
    category = Column(String(32), nullable=False)
    company = Column(String(255), nullable=False, default="")
    model = Column(String(512), nullable=False)
    company_norm = Column(String(255), nullable=False)
    model_norm = Column(String(512), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    details = relationship("EquipmentDetail", back_populates="equipment", cascade="all, delete-orphan", uselist=False)
    photos = relationship(
        "EquipmentDetailPhoto", back_populates="equipment", cascade="all, delete-orphan",
        order_by="EquipmentDetailPhoto.display_order, EquipmentDetailPhoto.id",
    )

    __table_args__ = (UniqueConstraint("category", "company_norm", "model_norm", name="uq_equipment_identity"),)

    @validates("company", "model")
    def _sync_norm(self, key, value):
        setattr(self, f"{key}_norm", norm(value))
        return value


class EquipmentDetail(Base):
    """An equipment item's description + short description (one row per item, updated in place)."""

    __tablename__ = "equipment_detail"

    id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=False)  # JSON serialized BikeDescription
    short_description = Column(Text, nullable=False, default="", server_default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    equipment = relationship("Equipment", back_populates="details")
    components = relationship(
        "EquipmentDetailComponent",
        back_populates="details",
        cascade="all, delete-orphan",
        order_by=(
            "EquipmentDetailComponent.component_order, "
            "EquipmentDetailComponent.element_order, "
            "EquipmentDetailComponent.spec_order"
        ),
    )


class EquipmentDetailComponent(Base):
    """One spec row of an equipment item — the flat shape of bike_detail_component (no equipment_id)."""

    __tablename__ = "equipment_detail_component"

    id = Column(Integer, primary_key=True)
    equipment_detail_id = Column(Integer, ForeignKey("equipment_detail.id", ondelete="CASCADE"), nullable=False, index=True)

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
    details = relationship("EquipmentDetail", back_populates="components")


class EquipmentDetailPhoto(Base):
    """Photos of an equipment item, keyed on the item (written once, never replaced)."""

    __tablename__ = "equipment_detail_photos"

    id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False, index=True)
    url = Column(String(2048), nullable=False)
    display_order = Column(Integer, default=0)

    # Relationships
    equipment = relationship("Equipment", back_populates="photos")
