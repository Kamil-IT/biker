"""The parts catalogue in the DB (TODO-046) — the "Wyszukiwanie części" tab.

The catalogue is the `equipment` table, category 'parts' only (never bike_component).
find_parts is the DB search behind POST /v1/parts/search — no AI, no generic cache:
every given field must match (part_type equal; brand equal to company_norm, or,
for a row whose company is still "", the name starting with the brand as a whole
word; model a substring of model_norm or name_norm; groupset a substring of the
stored groupset), `search` is not matched (like the bike search), sorted by brand
then model. A request with none of the four (free text only) matches nothing — like
the bike search's DB step — so the UI offers the AI search, which reads the text. Normalisation is always Python's models.norm(), never SQL lower(), so
the match runs over the category's rows in Python (the catalogue is small).

save_found_parts stores what POST /v1/parts/search/ai found: a new row per part
(category 'parts', name "Brand Model", company / model from the AI, description
NULL, so the equipment view searches its details by itself) via INSERT … ON
CONFLICT DO NOTHING on uq_equipment_name; an existing row — the same name_norm,
or the same company_norm + model_norm — only gets a missing part_type / groupset
/ key_specs. Nothing is ever overwritten and nothing goes into equipment_component.
"""
import json
import logging
from datetime import datetime, timezone
from typing import NamedTuple, Optional

from sqlalchemy import and_, or_

from .equipment_models import Equipment, EquipmentDetailPhoto
from .models import dialect_insert, get_session, norm
from .photo_cover import pick_covers
from .schemas import PartResult, PartsSearchRequest

logger = logging.getLogger("biker.parts")

PARTS_CATEGORY = "parts"
COMPANY_MAX = 255   # equipment.company
MODEL_MAX = 512     # equipment.model / name
GROUPSET_MAX = 128  # equipment.groupset
KEY_SPECS_MAX = 6
KEY_SPEC_MAX_LEN = 40


class FoundPart(NamedTuple):
    """One part from the AI search, already cleaned (parts_finder.clean_found_part)."""
    brand: str
    model: str
    part_type: Optional[str]
    groupset: Optional[str]
    key_specs: list[str]


def clean_key_specs(raw) -> list[str]:
    """≤ 6 chips: non-empty strings / numbers, whitespace collapsed, cut to 40 characters, duplicates dropped."""
    if not isinstance(raw, list):
        return []
    chips: list[str] = []
    for item in raw:
        if isinstance(item, bool) or not isinstance(item, (str, int, float)):
            continue
        chip = " ".join(str(item).split())[:KEY_SPEC_MAX_LEN].strip()
        if chip and chip.lower() not in (c.lower() for c in chips):
            chips.append(chip)
        if len(chips) == KEY_SPECS_MAX:
            break
    return chips


def load_key_specs(raw: Optional[str]) -> list[str]:
    """The stored JSON list, cleaned; [] for NULL or an unreadable value."""
    if not raw:
        return []
    try:
        return clean_key_specs(json.loads(raw))
    except (TypeError, ValueError):
        logger.warning("unreadable equipment.key_specs ignored | value=%r", raw[:80])
        return []


_COLUMNS = (
    Equipment.id, Equipment.part_type, Equipment.company, Equipment.model, Equipment.name,
    Equipment.company_norm, Equipment.model_norm, Equipment.name_norm, Equipment.groupset,
    Equipment.key_specs, Equipment.short_description,
)


def _brand_matches(row, brand: str) -> bool:
    if row.company_norm:
        return row.company_norm == brand
    return row.name_norm == brand or row.name_norm.startswith(brand + " ")


def _matches(row, brand: str, model: str, groupset: str) -> bool:
    if brand and not _brand_matches(row, brand):
        return False
    if model and model not in row.model_norm and model not in row.name_norm:
        return False
    return not groupset or groupset in norm(row.groupset)


def _photos(session, ids: list[int]) -> dict[int, str]:
    """First usable photo per item in one query (the bike tiles' junk / thumbnail filter); {} on a DB error."""
    if not ids:
        return {}
    try:
        rows = session.query(EquipmentDetailPhoto.equipment_id, EquipmentDetailPhoto.url).filter(
            EquipmentDetailPhoto.equipment_id.in_(ids),
        ).order_by(EquipmentDetailPhoto.equipment_id, EquipmentDetailPhoto.display_order, EquipmentDetailPhoto.id)
        return {eid: url for eid, (url, _bg) in pick_covers((eid, url, None) for eid, url in rows).items()}
    except Exception as exc:  # noqa: BLE001 - tiles without photos beat a failed search
        logger.error("parts photo read failed - tiles shown without photos | %s", exc)
        session.rollback()
        return {}


def _results(session, rows, new_ids: set[int]) -> list[PartResult]:
    photos = _photos(session, [r.id for r in rows])
    return [
        PartResult(
            id=r.id, part_type=r.part_type, brand=r.company or "", model=r.model or r.name, name=r.name,
            groupset=(r.groupset or None), key_specs=load_key_specs(r.key_specs),
            short_description=r.short_description or "", photo=photos.get(r.id), is_new=r.id in new_ids,
        )
        for r in rows
    ]


def find_parts(req: PartsSearchRequest) -> list[PartResult]:
    """Every 'parts' row matching all given fields (see the module docstring), sorted by brand then model;
    [] without reading the DB when only the free text is given (it is not matched).

    A DB error raises (the route answers 503) — an empty answer would offer a paid AI search instead.
    """
    brand, model, groupset = norm(req.brand), norm(req.model), norm(req.groupset)
    if not (req.part_type or brand or model or groupset):
        return []
    session = get_session()
    try:
        q = session.query(*_COLUMNS).filter(Equipment.category == PARTS_CATEGORY)
        if req.part_type:
            q = q.filter(Equipment.part_type == req.part_type)
        rows = [r for r in q if _matches(r, brand, model, groupset)]
        rows.sort(key=lambda r: (norm(r.company), norm(r.model), r.id))
        return _results(session, rows, set())
    finally:
        session.close()


def _fill_missing(item: Equipment, part: FoundPart) -> bool:
    """part_type / groupset / key_specs set only where the row has none; True when something was set."""
    changed = False
    if item.part_type is None and part.part_type:
        item.part_type, changed = part.part_type, True
    if not (item.groupset or "").strip() and part.groupset:
        item.groupset, changed = part.groupset, True
    if not load_key_specs(item.key_specs) and part.key_specs:
        item.key_specs, changed = json.dumps(part.key_specs, ensure_ascii=False), True
    return changed


def _existing(session, part: FoundPart, name: str) -> Optional[Equipment]:
    return session.query(Equipment).filter(
        Equipment.category == PARTS_CATEGORY,
        or_(
            Equipment.name_norm == norm(name),
            and_(Equipment.company_norm == norm(part.brand), Equipment.model_norm == norm(part.model)),
        ),
    ).order_by(Equipment.id).first()


def _store(session, part: FoundPart) -> tuple[int, bool]:
    """(equipment id, created by this call) for one found part; runs in the caller's transaction."""
    name = f"{part.brand} {part.model}".strip()[:MODEL_MAX].strip()
    item = _existing(session, part, name)
    if item is None:
        now = datetime.now(timezone.utc)
        # A Core insert bypasses @validates: the norm columns are set here.
        inserted = session.execute(dialect_insert(Equipment).values(
            category=PARTS_CATEGORY, name=name, name_norm=norm(name),
            company=part.brand, company_norm=norm(part.brand), model=part.model, model_norm=norm(part.model),
            short_description="", part_type=part.part_type, groupset=part.groupset,
            key_specs=json.dumps(part.key_specs, ensure_ascii=False) if part.key_specs else None,
            created_at=now, updated_at=now,
        ).on_conflict_do_nothing(index_elements=["category", "name_norm"])).rowcount
        item = session.query(Equipment).filter(
            Equipment.category == PARTS_CATEGORY, Equipment.name_norm == norm(name),
        ).order_by(Equipment.id).first()
        if item is None:  # pragma: no cover - the insert or the conflicting row must be visible
            raise RuntimeError(f"equipment row missing after insert | name={name!r}")
        if inserted:
            return item.id, True
    _fill_missing(item, part)
    return item.id, False


def save_found_parts(found: list[FoundPart]) -> list[PartResult]:
    """Store the AI search's parts (one transaction) and answer them as catalogue tiles, in the AI's order.

    Two found parts that land on one row are answered once. is_new = the row was
    created by this call. Raises on a DB error after rolling back.
    """
    session = get_session()
    try:
        ids: list[int] = []
        new_ids: set[int] = set()
        for part in found:
            eid, created = _store(session, part)
            if eid not in ids:
                ids.append(eid)
            if created:
                new_ids.add(eid)
        session.commit()
        by_id = {r.id: r for r in session.query(*_COLUMNS).filter(Equipment.id.in_(ids))} if ids else {}
        results = _results(session, [by_id[i] for i in ids if i in by_id], new_ids)
        logger.info("parts stored | found=%d answered=%d created=%d", len(found), len(results), len(new_ids))
        return results
    except Exception as exc:
        session.rollback()
        logger.error("parts store failed | found=%d | %s", len(found), exc)
        raise
    finally:
        session.close()
