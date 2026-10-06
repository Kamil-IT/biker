"""Persistence of equipment search results (TODO-042).

Equipment details (/v1/search/equipment/details) go into equipment (the item
AND its details since TODO-044: lookup identity = category slug + the
Python-normalised `name`, the element name from a bike's spec tree, the only
source of an equipment row; `company` / `model` are the researched brand and
model - "" and the name until a details search fills them; `description` /
`short_description` are updated in place) + equipment_component (the
flattened tree, same columns as bike_component, keyed on equipment_id). Photos (/v1/search/equipment/photos) go into
equipment_detail_photos keyed on equipment_id, written once, never replaced.

A successful save also links the element on the bike it was opened from:
link_bike_components sets bike_component.equipment_id on THAT bike's
rows with that element name — never on other bikes — in the same transaction.
A bike missing from `bike` is not created: the equipment is stored anyway and
the link is skipped (WARNING). An unusable details result stores only the
"Opis niedostępny dla tego produktu." placeholder on an item without a
description (the frontend then stops searching it automatically); an empty
photo result writes nothing. Lives apart from repository.py (500-line rule)
and reuses its helpers.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from .details_finder import has_components, is_usable_details
from .models import (
    BikeComponent,
    Equipment,
    EquipmentComponent,
    EquipmentDetailPhoto,
    dialect_insert,
    get_session,
    norm,
)
from .repository import _find_bike_id, _rebuild_components, flatten_components
from .schemas import BikeDescription, EquipmentDetails

logger = logging.getLogger("searcher.equipment.repository")

# Stored as the description of an item a details search found nothing for (see _store_not_found).
NOT_FOUND_TEXT = "Opis niedostępny dla tego produktu."


def _find_equipment_id(session, category: str, name: str) -> Optional[int]:
    """Identity lookup on the stored `name_norm`, compared with the Python-normalised name (never SQL lower())."""
    return session.query(Equipment.id).filter(
        Equipment.category == category,
        Equipment.name_norm == norm(name),
    ).order_by(Equipment.id).limit(1).scalar()


def _get_or_create_equipment(session, category: str, name: str) -> int:
    """The item's id, inserting the row (caller's casing) when it is new, then LOCKING it (SELECT … FOR UPDATE).

    Runs inside the caller's transaction and never commits, so a write that
    fails later rolls the new row back with everything else (no orphan rows).
    The insert is INSERT … ON CONFLICT DO NOTHING on uq_equipment_name
    (category, name_norm; SQLite and PostgreSQL alike): a concurrent creator makes it a no-op — on
    PostgreSQL it waits for that transaction — and the re-read finds its row.
    The row lock then serialises every save of this item (details and photos;
    a no-op on SQLite, whose writers are serialised anyway). Norms are set
    here because a Core insert bypasses @validates.
    """
    equipment_id = _find_equipment_id(session, category, name)
    if equipment_id is None:
        stmt = dialect_insert(Equipment).values(
            category=category, name=name.strip(), name_norm=norm(name), company="", company_norm="",
            model=name.strip(), model_norm=norm(name), short_description="",
            created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        ).on_conflict_do_nothing(index_elements=["category", "name_norm"])
        if session.execute(stmt).rowcount:
            logger.info("equipment created | category=%r name=%r", category, name)
        equipment_id = _find_equipment_id(session, category, name)
        if equipment_id is None:  # pragma: no cover - the insert or the conflicting row must be visible
            raise RuntimeError(f"equipment row missing after insert | category={category!r} name={name!r}")
    session.query(Equipment.id).filter(Equipment.id == equipment_id).with_for_update().one()
    return equipment_id


def fill_missing_identity(item: Equipment, company: str, model: str) -> None:
    """Fill the researched company / model only where missing; a "" never overwrites a stored value.

    company is set when the stored one is empty; model when the stored one is
    empty or still the element name (never researched). Stored casing as the
    search returned it, stripped, cut to the column length. The ORM
    assignment keeps the norm columns in step (@validates).
    """
    company = (company or "").strip()[:255]
    model = (model or "").strip()[:512]
    if company and not item.company:
        item.company = company
    if model and (not item.model or item.model_norm == item.name_norm):
        item.model = model


def get_or_create_equipment(category: str, name: str) -> int:
    session = get_session()
    try:
        equipment_id = _get_or_create_equipment(session, category, name)
        session.commit()
        return equipment_id
    finally:
        session.close()


def link_bike_components(session, bike_id: int, element_name: str, equipment_id: int) -> int:
    """Set equipment_id on this bike's bike_component rows whose element name matches; returns rows linked.

    The match is Python-normalised (strip().lower()), scoped to the one bike's
    component rows — never global. Runs in the caller's transaction (no commit).
    """
    wanted = norm(element_name)
    ids = [
        r.id for r in session.query(BikeComponent.id, BikeComponent.element_name)
        .filter(BikeComponent.bike_id == bike_id)
        if norm(r.element_name) == wanted
    ]
    if ids:
        session.query(BikeComponent).filter(BikeComponent.id.in_(ids)).update(
            {BikeComponent.equipment_id: equipment_id}, synchronize_session=False,
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
            "no bike_component row named %r on bike_id=%d — nothing linked | equipment_id=%d",
            element_name, bike_id, equipment_id,
        )
    return linked


def _store_not_found(session, bike_company: str, bike_model: str, element_name: str, category: str) -> int:
    """A run that found nothing usable: the item gets NOT_FOUND_TEXT as its description when it has none
    (`description` NULL), so the frontend, which searches automatically only while an item has no description,
    never runs it again. A stored description is never touched; no components, no researched identity. The
    element is linked like a usable result. Commits; returns the equipment id."""
    equipment_id = _get_or_create_equipment(session, category, element_name)
    item = session.get(Equipment, equipment_id)
    placed = item.description is None
    if placed:
        item.description = BikeDescription(text=NOT_FOUND_TEXT).model_dump_json()
        item.short_description = ""
        item.updated_at = datetime.now(timezone.utc)
    linked = _link(session, bike_company, bike_model, element_name, equipment_id)
    session.commit()
    logger.warning(
        "no usable equipment details | element=%r category=%r equipment_id=%d placeholder=%s linked=%d",
        element_name, category, equipment_id, placed, linked,
    )
    return equipment_id


def save_equipment_details(
    bike_company: str, bike_model: str, element_name: str, category: str, details: EquipmentDetails,
) -> tuple[Optional[int], bool]:
    """Store `details` as the item's details when usable; returns (equipment_id, saved).

    Usable = a non-empty component tree or a non-empty description. Then, in
    one transaction: the equipment row found by (category, name = the element
    name) - NOT by company / model - or created (company "", model = name),
    its description / short_description updated IN PLACE, its components
    replaced - only the half this run produced (same rule as
    repository.save_details) - the researched company / model filled where
    missing (fill_missing_identity: a stored value is never overwritten, a ""
    from the run never counts) and the element linked on the bike, all under
    the equipment row lock (_get_or_create_equipment), so two bikes saving the
    same item at once run one after the other. An unusable result (found:
    false or nothing in it) stores only the NOT_FOUND_TEXT placeholder on an
    item without a description (_store_not_found) and answers (equipment_id,
    False) — a failed run raises before this and writes nothing, so the next
    visit retries. Raises on a DB error after rolling back.
    """
    session = get_session()
    try:
        if not is_usable_details(details):
            return _store_not_found(session, bike_company, bike_model, element_name, category), False
        equipment_id = _get_or_create_equipment(session, category, element_name)
        item = session.get(Equipment, equipment_id)
        has_desc = bool(details.description.text.strip())
        has_comps = has_components(details)
        if has_desc or item.description is None:
            item.description = details.description.model_dump_json()
            item.short_description = details.short_description
        item.updated_at = datetime.now(timezone.utc)
        fill_missing_identity(item, details.found_company, details.found_model)
        if has_comps:
            session.query(EquipmentComponent).filter_by(equipment_id=equipment_id).delete(synchronize_session=False)
            session.expire(item, ["components"])
        session.flush()
        rows = 0
        for values in flatten_components(details.components if has_comps else []):
            session.add(EquipmentComponent(equipment_id=equipment_id, **values))
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
    """The stored details of an item (stored casing, the researched company / model), or None when the item is
    missing or has no details (`description` NULL)."""
    session = get_session()
    try:
        item = session.get(Equipment, equipment_id)
        if item is None or item.description is None:
            return None
        try:
            description = BikeDescription.model_validate_json(item.description)
        except Exception as exc:  # noqa: BLE001 - an unreadable blob must not break the request
            logger.warning("stored equipment description unreadable | equipment_id=%d | %s", equipment_id, exc)
            description = BikeDescription()
        return EquipmentDetails(
            company=item.company, model=item.model, category=item.category, description=description,
            components=_rebuild_components(item.components, element_links=False),
            short_description=item.short_description or "", equipment_id=equipment_id,
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
        equipment_id = _get_or_create_equipment(session, category, element_name)  # row locked
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
