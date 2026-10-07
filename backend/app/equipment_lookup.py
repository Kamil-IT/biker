"""Equipment addressed by id — the frontend's /equipment/{id} pages.

get_equipment_item: the item's identity + the first bike whose spec tree links it
(the back target of a deep link). resolve_equipment: the equipment row of one
element of a bike's spec tree, created empty when missing (name + inferred
category, no details) and linked on THAT bike's rows — free, no AI; the click in
the bike view calls it, then navigates to /equipment/{id}. search_context: what
a search by equipment_id sends to the searcher (the context bike, the stored name
and category, so the searcher finds this very row by its (category, name_norm)).
A catalogue part no bike links (TODO-046) is searched without a bike.
Lives apart from equipment_repository.py (500-line rule).
"""
import logging
from datetime import datetime, timezone
from typing import NamedTuple, Optional

from .equipment_categories import infer_category
from .equipment_models import Equipment
from .part_types import part_type_name
from .models import Bike, BikeComponent, dialect_insert, get_session, norm
from .schemas import BikeRef, EquipmentItemResponse, EquipmentResolveResponse

logger = logging.getLogger(__name__)


class NotFound(Exception):
    """An unknown bike / element / equipment item; the message is the route's 404 detail."""


class SearchContext(NamedTuple):
    bike_company: str  # "" = no context bike (a catalogue part no bike links, TODO-046)
    bike_model: str
    element_name: str
    element_type: str
    category: Optional[str]  # the item's stored slug; the caller's (or None) on the by-name path


def _linked_row(session, equipment_id: int, bike_id: Optional[int] = None):
    """(bike_id, subcategory) of a bike_component row linking the item: on `bike_id` when that bike links it,
    else the oldest linking row; None when no bike links it."""
    q = session.query(BikeComponent.bike_id, BikeComponent.subcategory).filter(BikeComponent.equipment_id == equipment_id)
    if bike_id is not None:
        row = q.filter(BikeComponent.bike_id == bike_id).order_by(BikeComponent.id).first()
        if row is not None:
            return row
    return q.order_by(BikeComponent.id).first()


def get_equipment_item(equipment_id: int) -> Optional[EquipmentItemResponse]:
    """The item's identity and the first bike linking it; None for an unknown id. A DB error raises."""
    session = get_session()
    try:
        item = session.get(Equipment, equipment_id)
        if item is None:
            return None
        row = _linked_row(session, equipment_id)
        bike = session.get(Bike, row.bike_id) if row is not None else None
        return EquipmentItemResponse(
            equipment_id=item.id, name=item.name, category=item.category, company=item.company, model=item.model,
            bike=BikeRef(id=bike.id, brand=bike.brand, model=bike.model) if bike is not None else None,
        )
    finally:
        session.close()


def _find_or_create(session, name: str) -> int:
    """The oldest item named `name` (normalised, any category), else a new empty one under the inferred category.

    INSERT … ON CONFLICT DO NOTHING on uq_equipment_name: a concurrent creator makes it
    a no-op and the re-read finds its row (the searcher's _get_or_create_equipment does
    the same). Norms are set here because a Core insert bypasses @validates.
    """
    found = session.query(Equipment.id).filter(Equipment.name_norm == norm(name)).order_by(Equipment.id).limit(1).scalar()
    if found is not None:
        return found
    category = infer_category("", name)
    now = datetime.now(timezone.utc)
    session.execute(dialect_insert(Equipment).values(
        category=category, name=name.strip(), name_norm=norm(name), company="", company_norm="",
        model=name.strip(), model_norm=norm(name), short_description="", created_at=now, updated_at=now,
    ).on_conflict_do_nothing(index_elements=["category", "name_norm"]))
    created = session.query(Equipment.id).filter(
        Equipment.category == category, Equipment.name_norm == norm(name),
    ).order_by(Equipment.id).limit(1).scalar()
    logger.info("equipment row resolved | name=%r category=%r equipment_id=%s", name, category, created)
    return created


def resolve_equipment(bike_id: int, element_name: str) -> EquipmentResolveResponse:
    """The equipment row of a bike's element (Python-normalised name match), created when missing; links that
    bike's rows of the element. Raises NotFound("Bike not found" / "Component not found"); a DB error rolls
    back and raises.

    An element already linked keeps its item; otherwise an item with the same name is
    reused (any category), else a new one is made from the STORED element name (not
    the caller's spelling). Only this bike's rows are linked — never other bikes'.
    """
    wanted = norm(element_name)
    session = get_session()
    try:
        if session.get(Bike, bike_id) is None:
            raise NotFound("Bike not found")
        rows = [
            r for r in session.query(BikeComponent.id, BikeComponent.element_name, BikeComponent.equipment_id)
            .filter(BikeComponent.bike_id == bike_id).order_by(BikeComponent.id)
            if r.element_name and norm(r.element_name) == wanted
        ]
        if not rows:
            raise NotFound("Component not found")
        linked = next((r.equipment_id for r in rows if r.equipment_id is not None), None)
        item_id = linked if linked is not None else _find_or_create(session, rows[0].element_name)
        relink = [r.id for r in rows if r.equipment_id != item_id]
        if relink:
            session.query(BikeComponent).filter(BikeComponent.id.in_(relink)).update(
                {BikeComponent.equipment_id: item_id}, synchronize_session=False,
            )
        session.commit()
        item = session.get(Equipment, item_id)
        return EquipmentResolveResponse(equipment_id=item.id, name=item.name, category=item.category)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def search_context(equipment_id: int, bike_id: Optional[int] = None) -> SearchContext:
    """What a search by equipment_id sends to the searcher: the context bike (`bike_id` when it links the item,
    else the first bike linking it), the item's stored name and category, the element's subcategory.

    An item no bike links — a catalogue part from the parts search (TODO-046) — is searched without a bike:
    bike company / model "" and, as the element type, the English name of its part type ("Cassette", "" when
    unknown). Raises NotFound("Equipment not found") for an unknown id only."""
    session = get_session()
    try:
        item = session.get(Equipment, equipment_id)
        if item is None:
            raise NotFound("Equipment not found")
        row = _linked_row(session, equipment_id, bike_id)
        bike = session.get(Bike, row.bike_id) if row is not None else None
        if bike is None:
            return SearchContext("", "", item.name, part_type_name(item.part_type), item.category)
        return SearchContext(bike.brand, bike.model, item.name, row.subcategory or "", item.category)
    finally:
        session.close()
