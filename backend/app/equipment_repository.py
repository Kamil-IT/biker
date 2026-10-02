"""Stored equipment data (TODO-042, tables merged in TODO-044): reads for the API, writes for tests and offline use.

POST /v1/equipment/details and POST /v1/equipment/photos are pure DB reads of
`equipment` (the item and its details: `description` NULL = no details) +
`equipment_component` and `equipment_detail_photos`. A request is resolved by
`equipment_id` when given, else by name - never SQL lower(), the category
ignored, oldest row first: the Python-normalised "company model" (just the
model when the company is empty, which is what the spec-tree click sends) is
matched against `name_norm`, or the pair against the researched
(company_norm, model_norm). Unknown equipment or a DB error answers the empty
response (a DB error also logs at ERROR), never an exception.

The live writer is the searcher (searcher/app/equipment_repository.py); the
save helpers here mirror its rules: the row is found by (category, name), a
result is stored only when usable, the details columns are updated in place
and only the half the result produced is replaced, company / model are filled
only where missing (never overwritten with ""), photos are insert-only, and
the bike link touches only that bike's `bike_component` rows with that
element name - never globally.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, or_

from .component_tree import flatten_components, has_components, rebuild_components
from .equipment_models import Equipment, EquipmentComponent, EquipmentDetailPhoto
from .models import BikeComponent, get_session, norm
from .repository import _find_bike_id
from .schemas import (
    BikeDescription,
    EquipmentDetailsRequest,
    EquipmentDetailsResponse,
    EquipmentPhotosRequest,
    EquipmentPhotosResponse,
)

logger = logging.getLogger(__name__)

MAX_PHOTO_URL = 2048


# ── Lookups ─────────────────────────────────────────────────────────────────


def _find_equipment_id(session, company: str, model: str, category: Optional[str] = None) -> Optional[int]:
    """Oldest id by name: `name_norm` == the normalised "company model" (just the model when company is
    empty - the spec-tree click), or the researched (company_norm, model_norm) pair."""
    full_name = norm(f"{(company or '').strip()} {(model or '').strip()}")
    q = session.query(Equipment.id).filter(or_(
        Equipment.name_norm == full_name,
        and_(Equipment.company_norm == norm(company), Equipment.model_norm == norm(model)),
    ))
    if category:
        q = q.filter(Equipment.category == category)
    return q.order_by(Equipment.id).limit(1).scalar()


def find_equipment_id(company: str, model: str, category: Optional[str] = None) -> Optional[int]:
    """Oldest equipment id found by name (see `_find_equipment_id`); `category` narrows it when given."""
    session = get_session()
    try:
        return _find_equipment_id(session, company, model, category)
    finally:
        session.close()


def bike_component_name(company: str, model: str, element_name: str) -> Optional[tuple[str, str]]:
    """(stored element name, its subcategory) for the bike's element matching `element_name` (Python-normalised),
    None when it has none.

    The guard of the equipment search routes: a search only runs for an element
    of a known bike's stored spec tree, so anonymous traffic cannot spend
    subscription runs on arbitrary strings. The routes forward the STORED name
    (not the caller's casing / whitespace) to the searcher, so the first caller
    cannot choose the equipment row's name or the prompt text. Oldest row wins
    should two names differ only by casing. The subcategory (e.g. "Frame") is the
    element type the searcher puts in its prompt: a frame is often named exactly
    like the bike. A DB error answers None (logged).
    """
    session = get_session()
    try:
        bike_id = _find_bike_id(session, company, model)
        if bike_id is None:
            return None
        wanted = norm(element_name)
        rows = (
            session.query(BikeComponent.element_name, BikeComponent.subcategory)
            .filter(BikeComponent.bike_id == bike_id)
            .order_by(BikeComponent.id)
        )
        return next(((name, subcategory or "") for name, subcategory in rows if name and norm(name) == wanted), None)
    except Exception as exc:  # noqa: BLE001
        logger.error("bike component lookup failed | company=%r model=%r element=%r | %s", company, model, element_name, exc)
        return None
    finally:
        session.close()


def _resolve(session, req: EquipmentDetailsRequest) -> Optional[Equipment]:
    """By id when the request carries one (an unknown id is a miss), else by name, category ignored."""
    if req.equipment_id is not None:
        return session.get(Equipment, req.equipment_id)
    equipment_id = _find_equipment_id(session, req.company, req.model)
    return session.get(Equipment, equipment_id) if equipment_id is not None else None


# ── Reads ───────────────────────────────────────────────────────────────────


def empty_equipment_details(
    company: str, model: str, category: Optional[str] = None, equipment_id: Optional[int] = None,
) -> EquipmentDetailsResponse:
    """The "nothing stored" answer of POST /v1/equipment/details."""
    return EquipmentDetailsResponse(
        company=company, model=model, category=category or "",
        description=BikeDescription(text="", segments=[], citations=[]),
        components=[], short_description="", equipment_id=equipment_id,
    )


def get_equipment_details(req: EquipmentDetailsRequest) -> EquipmentDetailsResponse:
    """Stored details of one equipment item; company/model/category come from the stored row
    (the researched brand and model, or "" and the name until a details search ran).

    Equipment that exists without details (`description` NULL, e.g. photos only)
    answers the empty details carrying its id and category.
    """
    session = get_session()
    try:
        equipment = _resolve(session, req)
        if equipment is None:
            logger.info("equipment details miss | id=%r company=%r model=%r", req.equipment_id, req.company, req.model)
            return empty_equipment_details(req.company, req.model, req.category)
        if equipment.description is None:
            logger.info("equipment details miss (no details) | equipment_id=%d", equipment.id)
            return empty_equipment_details(equipment.company, equipment.model, equipment.category, equipment.id)
        response = EquipmentDetailsResponse(
            company=equipment.company, model=equipment.model, category=equipment.category,
            description=BikeDescription.model_validate_json(equipment.description),
            components=rebuild_components(equipment.components, element_links=False),
            short_description=equipment.short_description or "",
            equipment_id=equipment.id,
        )
        logger.info("equipment details hit | equipment_id=%d", equipment.id)
        return response
    except Exception as exc:  # noqa: BLE001 — a DB read must never break the equipment view
        logger.error(
            "equipment details read failed | id=%r company=%r model=%r | %s",
            req.equipment_id, req.company, req.model, exc,
        )
        return empty_equipment_details(req.company, req.model, req.category)
    finally:
        session.close()


def get_equipment_photos(req: EquipmentPhotosRequest) -> EquipmentPhotosResponse:
    """Stored photo URLs of one equipment item, ORDER BY display_order, id."""
    session = get_session()
    try:
        equipment = _resolve(session, req)
        if equipment is None:
            logger.info("equipment photos miss | id=%r company=%r model=%r", req.equipment_id, req.company, req.model)
            return EquipmentPhotosResponse(photos=[], equipment_id=None)
        urls = [
            url for (url,) in session.query(EquipmentDetailPhoto.url)
            .filter(EquipmentDetailPhoto.equipment_id == equipment.id)
            .order_by(EquipmentDetailPhoto.display_order, EquipmentDetailPhoto.id)
        ]
        logger.info("equipment photos read | equipment_id=%d photos=%d", equipment.id, len(urls))
        return EquipmentPhotosResponse(photos=urls, equipment_id=equipment.id)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "equipment photos read failed | id=%r company=%r model=%r | %s",
            req.equipment_id, req.company, req.model, exc,
        )
        return EquipmentPhotosResponse(photos=[], equipment_id=None)
    finally:
        session.close()


# ── Writes (tests / offline; the live writer is the searcher) ───────────────


def _get_or_create_equipment(session, name: str, category: str, lock: bool = False) -> Equipment:
    """By the save identity (category, name_norm); created with the caller's casing, company "" and model = name."""
    q = session.query(Equipment).filter(Equipment.category == category, Equipment.name_norm == norm(name))
    if lock:
        q = q.with_for_update()  # PostgreSQL row lock; SQLite ignores it (writes are serialised anyway)
    equipment = q.order_by(Equipment.id).first()
    if equipment is None:
        equipment = Equipment(category=category, name=name.strip(), company="", model=name.strip())
        session.add(equipment)
        session.flush()
    return equipment


def fill_missing_identity(equipment: Equipment, company: str, model: str) -> None:
    """Fill the researched company / model only where missing; a "" never overwrites a stored value.

    company is set when the stored one is empty; model when the stored one is
    empty or still the element name (never researched). Stored casing as
    returned, stripped, cut to the column length.
    """
    company = (company or "").strip()[:255]
    model = (model or "").strip()[:512]
    if company and not equipment.company:
        equipment.company = company
    if model and (not equipment.model or equipment.model_norm == equipment.name_norm):
        equipment.model = model


def _link_bike_components(session, bike_id: int, element_name: str, equipment_id: int) -> int:
    """Set equipment_id on THIS bike's component rows whose element name matches (normalised); rows updated."""
    wanted = norm(element_name)
    ids = [
        row_id for row_id, name in session.query(BikeComponent.id, BikeComponent.element_name)
        .filter(BikeComponent.bike_id == bike_id)
        if norm(name) == wanted
    ]
    if ids:
        session.query(BikeComponent).filter(BikeComponent.id.in_(ids)).update(
            {BikeComponent.equipment_id: equipment_id}, synchronize_session=False,
        )
    return len(ids)


def link_bike_components(bike_id: int, element_name: str, equipment_id: int) -> int:
    """Link one bike's element to an equipment row in its own transaction; returns rows updated (0 on error)."""
    session = get_session()
    try:
        count = _link_bike_components(session, bike_id, element_name, equipment_id)
        session.commit()
        return count
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning("equipment link failed (non-fatal) | bike_id=%r element=%r | %s", bike_id, element_name, exc)
        return 0
    finally:
        session.close()


def is_usable_equipment_details(data: EquipmentDetailsResponse) -> bool:
    """Worth storing: a non-empty component tree OR a non-empty description."""
    return has_components(data.components) or bool(data.description.text.strip())


def save_equipment_details(
    company: str, model: str, category: str, data: EquipmentDetailsResponse,
    bike_id: Optional[int] = None, element_name: Optional[str] = None,
) -> Optional[int]:
    """Store usable details; returns the equipment id, None when nothing was written.

    The row is found by (category, name) with name = `element_name`, else
    "company model". One transaction: the row is created if missing, its
    description columns updated in place (id stable), only the half the result
    produced is replaced (description + short_description, and/or the
    components), and the researched `company` / `model` are filled where
    missing. With `bike_id` + `element_name` that bike's rows of that element
    are linked in the same transaction. An unusable result writes nothing (no
    equipment row, no link); a DB error rolls back and logs.
    """
    if not category or not is_usable_equipment_details(data):
        logger.warning("no usable equipment details to store | company=%r model=%r", company, model)
        return None
    session = get_session()
    try:
        name = element_name or f"{company} {model}".strip()
        equipment = _get_or_create_equipment(session, name, category)
        has_desc = bool(data.description.text.strip())
        has_comps = has_components(data.components)
        if has_desc or equipment.description is None:
            equipment.description = data.description.model_dump_json()
            equipment.short_description = data.short_description or ""
        equipment.updated_at = datetime.now(timezone.utc)
        fill_missing_identity(equipment, company, model)
        if has_comps:
            session.query(EquipmentComponent).filter_by(equipment_id=equipment.id).delete(synchronize_session=False)
            session.expire(equipment, ["components"])
        session.flush()
        for flat in (flatten_components(data.components) if has_comps else []):
            session.add(EquipmentComponent(equipment_id=equipment.id, **flat))
        if bike_id is not None and element_name:
            _link_bike_components(session, bike_id, element_name, equipment.id)
        session.commit()
        logger.info("equipment details stored | equipment_id=%d company=%r model=%r", equipment.id, company, model)
        return equipment.id
    except Exception as exc:  # noqa: BLE001 — mirrors save_bike_details: non-fatal
        session.rollback()
        logger.warning("equipment details store failed (non-fatal) | company=%r model=%r | %s", company, model, exc)
        return None
    finally:
        session.close()


def _valid_photo_urls(photos: list[str]) -> list[str]:
    return [
        u for u in (p.strip() for p in photos if p)
        if u.lower().startswith(("http://", "https://")) and len(u) <= MAX_PHOTO_URL
    ]


def save_equipment_photos(
    company: str, model: str, category: str, photos: list[str],
    bike_id: Optional[int] = None, element_name: Optional[str] = None,
) -> tuple[Optional[int], int]:
    """Store photos for equipment that has none; returns (equipment_id, rows written).

    Insert-only: equipment that already has photos keeps them (0 written).
    Only http/https URLs of at most 2048 chars are kept; no usable URL writes
    nothing (no equipment row, no link) and returns (None, 0). A usable result
    links that bike's element rows in the same transaction. Non-fatal on error.
    """
    urls = _valid_photo_urls(photos)
    if not category or not urls:
        return None, 0
    session = get_session()
    try:
        equipment = _get_or_create_equipment(
            session, element_name or f"{company} {model}".strip(), category, lock=True,
        )
        written = 0
        if session.query(EquipmentDetailPhoto.id).filter(EquipmentDetailPhoto.equipment_id == equipment.id).first() is None:
            session.add_all(
                EquipmentDetailPhoto(equipment_id=equipment.id, url=url, display_order=idx)
                for idx, url in enumerate(urls)
            )
            written = len(urls)
        if bike_id is not None and element_name:
            _link_bike_components(session, bike_id, element_name, equipment.id)
        session.commit()
        logger.info("equipment photos stored | equipment_id=%d photos=%d", equipment.id, written)
        return equipment.id, written
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning("equipment photos store failed (non-fatal) | company=%r model=%r | %s", company, model, exc)
        return None, 0
    finally:
        session.close()
