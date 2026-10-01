"""Persistence of equipment search results (TODO-042).

Equipment details (/v1/search/equipment/details) go into equipment (the
identity: category slug + Python-normalised company/model; opened from a
bike's spec tree, so company is "" and model is the element name) +
equipment_detail (one row per item, updated in place) +
equipment_detail_component (the flattened tree, same columns as
bike_detail_component). Photos (/v1/search/equipment/photos) go into
equipment_detail_photos keyed on equipment_id, written once, never replaced.

A successful save also links the element on the bike it was opened from:
link_bike_components sets bike_detail_component.equipment_id on THAT bike's
rows with that element name — never on other bikes — in the same transaction.
A bike missing from `bike` is not created: the equipment is stored anyway and
the link is skipped (WARNING). An unusable result writes nothing — no
equipment row, no link. Lives apart from repository.py (500-line rule) and
reuses its helpers.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from .details_finder import has_components, is_usable_details
from .models import (
    BikeDetailComponent,
    Equipment,
    EquipmentDetail,
    EquipmentDetailComponent,
    EquipmentDetailPhoto,
    dialect_insert,
    get_session,
    norm,
)
from .repository import _find_bike_id, _rebuild_components, flatten_components
from .schemas import BikeDescription, EquipmentDetails

logger = logging.getLogger("searcher.equipment.repository")


def _find_equipment_id(session, category: str, company: str, model: str) -> Optional[int]:
    """Identity lookup on the stored norm columns, compared with Python-normalised values (never SQL lower())."""
    return session.query(Equipment.id).filter(
        Equipment.category == category,
        Equipment.company_norm == norm(company),
        Equipment.model_norm == norm(model),
    ).order_by(Equipment.id).limit(1).scalar()


def _get_or_create_equipment(session, category: str, company: str, model: str) -> int:
    """The item's id, inserting the row (caller's casing) when it is new, then LOCKING it (SELECT … FOR UPDATE).

    Runs inside the caller's transaction and never commits, so a write that
    fails later rolls the new row back with everything else (no orphan rows).
    The insert is INSERT … ON CONFLICT DO NOTHING on uq_equipment_identity
    (SQLite and PostgreSQL alike): a concurrent creator makes it a no-op — on
    PostgreSQL it waits for that transaction — and the re-read finds its row.
    The row lock then serialises every save of this item (details and photos;
    a no-op on SQLite, whose writers are serialised anyway). Norms are set
    here because a Core insert bypasses @validates.
    """
    equipment_id = _find_equipment_id(session, category, company, model)
    if equipment_id is None:
        stmt = dialect_insert(Equipment).values(
            category=category, company=company.strip(), model=model.strip(),
            company_norm=norm(company), model_norm=norm(model), created_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing(index_elements=["category", "company_norm", "model_norm"])
        if session.execute(stmt).rowcount:
            logger.info("equipment created | category=%r company=%r model=%r", category, company, model)
        equipment_id = _find_equipment_id(session, category, company, model)
        if equipment_id is None:  # pragma: no cover - the insert or the conflicting row must be visible
            raise RuntimeError(f"equipment row missing after insert | category={category!r} model={model!r}")
    session.query(Equipment.id).filter(Equipment.id == equipment_id).with_for_update().one()
    return equipment_id


def get_or_create_equipment(category: str, company: str, model: str) -> int:
    session = get_session()
    try:
        equipment_id = _get_or_create_equipment(session, category, company, model)
        session.commit()
        return equipment_id
    finally:
        session.close()


def link_bike_components(session, bike_id: int, element_name: str, equipment_id: int) -> int:
    """Set equipment_id on this bike's bike_detail_component rows whose element name matches; returns rows linked.

    The match is Python-normalised (strip().lower()), scoped to the one bike's
    component rows — never global. Runs in the caller's transaction (no commit).
    """
    wanted = norm(element_name)
    ids = [
        r.id for r in session.query(BikeDetailComponent.id, BikeDetailComponent.element_name)
        .filter(BikeDetailComponent.bike_id == bike_id)
        if norm(r.element_name) == wanted
    ]
    if ids:
        session.query(BikeDetailComponent).filter(BikeDetailComponent.id.in_(ids)).update(
            {BikeDetailComponent.equipment_id: equipment_id}, synchronize_session=False,
        )
    return len(ids)


def _link(session, bike_company: str, bike_model: str, element_name: str, equipment_id: int) -> int:
    bike_id = _find_bike_id(session, bike_company, bike_model)
    if bike_id is None:
        logger.warning(
            "bike not found — equipment stored, element not linked | bike=%r %r element=%r equipment_id=%d",
            bike_company, bike_model, element_name, equipment_id,
        )
        return 0
    linked = link_bike_components(session, bike_id, element_name, equipment_id)
    if not linked:
        logger.warning(
            "no bike_detail_component row named %r on bike_id=%d — nothing linked | equipment_id=%d",
            element_name, bike_id, equipment_id,
        )
    return linked


def save_equipment_details(
    bike_company: str, bike_model: str, element_name: str, category: str, details: EquipmentDetails,
) -> tuple[Optional[int], bool]:
    """Store `details` as the item's details when usable; returns (equipment_id, saved).

    Usable = a non-empty component tree or a non-empty description. Then, in
    one transaction: the equipment row (company "", model = element name)
    created if missing, its equipment_detail row updated IN PLACE or inserted,
    its components replaced — only the half this run produced (same rule as
    repository.save_details) — and the element linked on the bike, all under
    the equipment row lock (_get_or_create_equipment), so two bikes saving the
    same item at once run one after the other. An unusable result writes,
    deletes and links nothing and answers (None, False) — no id the caller
    could store, even when the item exists (the UI falls back to the by-name
    read). Raises on a DB error after rolling back.
    """
    session = get_session()
    try:
        if not is_usable_details(details):
            logger.warning("no usable equipment details - nothing written | element=%r category=%r", element_name, category)
            return None, False
        equipment_id = _get_or_create_equipment(session, category, "", element_name)
        has_desc = bool(details.description.text.strip())
        has_comps = has_components(details)
        row = session.query(EquipmentDetail).filter_by(equipment_id=equipment_id).first()
        if row is not None:
            if has_desc:
                row.description = details.description.model_dump_json()
                row.short_description = details.short_description
            row.updated_at = datetime.now(timezone.utc)
            if has_comps:
                session.query(EquipmentDetailComponent).filter_by(equipment_detail_id=row.id).delete(synchronize_session=False)
                session.expire(row, ["components"])
        else:
            row = EquipmentDetail(
                equipment_id=equipment_id, description=details.description.model_dump_json(),
                short_description=details.short_description,
            )
            session.add(row)
        session.flush()
        rows = 0
        for values in flatten_components(details.components if has_comps else []):
            session.add(EquipmentDetailComponent(equipment_detail_id=row.id, **values))
            rows += 1
        linked = _link(session, bike_company, bike_model, element_name, equipment_id)
        session.commit()
        logger.info(
            "equipment details stored | element=%r category=%r equipment_id=%d component_rows=%d linked=%d",
            element_name, category, equipment_id, rows, linked,
        )
        return equipment_id, True
    except Exception as exc:
        session.rollback()
        logger.error("equipment details store failed | element=%r category=%r | %s", element_name, category, exc)
        raise
    finally:
        session.close()


def get_equipment_details(equipment_id: int) -> Optional[EquipmentDetails]:
    """The stored details of an item (stored casing), or None when the item or its details row is missing."""
    session = get_session()
    try:
        item = session.get(Equipment, equipment_id)
        if item is None or item.details is None:
            return None
        try:
            description = BikeDescription.model_validate_json(item.details.description)
        except Exception as exc:  # noqa: BLE001 - an unreadable blob must not break the request
            logger.warning("stored equipment description unreadable | equipment_id=%d | %s", equipment_id, exc)
            description = BikeDescription()
        return EquipmentDetails(
            company=item.company, model=item.model, category=item.category, description=description,
            components=_rebuild_components(item.details.components),
            short_description=item.details.short_description or "", equipment_id=equipment_id,
        )
    finally:
        session.close()


def _photo_urls(session, equipment_id: int) -> list[str]:
    return [
        r.url for r in session.query(EquipmentDetailPhoto.url)
        .filter(EquipmentDetailPhoto.equipment_id == equipment_id)
        .order_by(EquipmentDetailPhoto.display_order, EquipmentDetailPhoto.id)
    ]


def get_equipment_photos(equipment_id: int) -> list[str]:
    session = get_session()
    try:
        return _photo_urls(session, equipment_id)
    finally:
        session.close()


def save_equipment_photos(
    bike_company: str, bike_model: str, element_name: str, category: str, photos: list[str],
) -> tuple[Optional[int], list[str], int]:
    """Store `photos` for an item that has none; returns (equipment_id, the item's photos now, rows written).

    Photos are never deleted or replaced. The check and the insert run under a
    row lock on the equipment row (SELECT … FOR UPDATE; a no-op on SQLite), so
    two concurrent searches cannot both insert. A non-empty result links the
    element on the bike (also when another search stored the photos first —
    they are reachable by id either way). An empty `photos` writes nothing —
    no equipment row, no link — and answers (None, [], 0). equipment_id is None
    too when nothing was written and nothing linked (photos already stored, but
    the bike or its element is unknown). Raises on a DB error after rolling back.
    """
    session = get_session()
    try:
        if not photos:
            logger.warning("no equipment photos to store - nothing written | element=%r category=%r", element_name, category)
            return None, [], 0
        equipment_id = _get_or_create_equipment(session, category, "", element_name)  # row locked
        stored = _photo_urls(session, equipment_id)
        saved = 0
        if stored:
            logger.info("equipment photos already stored - kept | equipment_id=%d stored=%d", equipment_id, len(stored))
        else:
            for idx, url in enumerate(photos):
                session.add(EquipmentDetailPhoto(equipment_id=equipment_id, url=url, display_order=idx))
            stored, saved = list(photos), len(photos)
        linked = _link(session, bike_company, bike_model, element_name, equipment_id)
        session.commit()
        logger.info(
            "equipment photos stored | element=%r category=%r equipment_id=%d saved=%d linked=%d",
            element_name, category, equipment_id, saved, linked,
        )
        return (equipment_id if saved or linked else None), stored, saved
    except Exception as exc:
        session.rollback()
        logger.error("equipment photos store failed | element=%r category=%r | %s", element_name, category, exc)
        raise
    finally:
        session.close()
