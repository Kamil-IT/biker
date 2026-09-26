"""Data access layer using SQLAlchemy ORM models."""
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

from .models import (
    Bike,
    BikeDetails,
    BikeDetailPhoto,
    BikeDetailComponent,
    BikeMissingRequest,
    dialect_insert,
    get_session,
)
from .schemas import (
    BikeDetailsResponse,
    BikeDescription,
    BikeResult,
    BikeCategory,
    MissingDataResponse,
    BikeSubcategory,
    ComponentElement,
    SpecItem,
)

logger = logging.getLogger(__name__)

TTL_DETAILS = 30 * 24 * 60 * 60  # 30 days

# The search cache (search_cache + search_bike_rating_cache) lives in store.py.
# This module owns the bike-details helpers and the DB-first search below.


def rebuild_components(rows) -> list[BikeCategory]:
    """Regroup flat BikeDetailComponent rows back into the nested response tree.

    `rows` must already be ordered by (component_order, element_order,
    spec_order) — the relationship declares that ordering. Grouping keys off
    those integers rather than off names, so two elements sharing a name inside
    one subcategory stay distinct. A row whose spec_key is NULL contributes an
    element with no specs, which is how `specs: []` round-trips.
    """
    comps: dict[int, dict] = {}
    for r in rows:
        comp = comps.setdefault(r.component_order, {
            "category": r.category,
            "subcategory": r.subcategory,
            "elements": {},
        })
        element = comp["elements"].setdefault(r.element_order, {
            "name": r.element_name,
            "description": r.element_description or "",
            "specs": [],
        })
        if r.spec_key is not None:
            element["specs"].append(SpecItem(key=r.spec_key, value=r.spec_value or ""))

    # Categories are contiguous runs of component_order, so walking in order and
    # grouping into a dict re-nests them with their original ordering intact.
    grouped: dict[str, list[BikeSubcategory]] = {}
    for comp_order in sorted(comps):
        comp = comps[comp_order]
        grouped.setdefault(comp["category"], []).append(BikeSubcategory(
            subcategory=comp["subcategory"],
            elements=[
                ComponentElement(
                    name=el["name"],
                    description=el["description"],
                    specs=el["specs"],
                )
                for _, el in sorted(comp["elements"].items())
            ],
        ))
    return [
        BikeCategory(category=name, subcategories=subs)
        for name, subs in grouped.items()
    ]


def save_bike_details(company: str, model: str, data: BikeDetailsResponse, ttl: int = TTL_DETAILS) -> None:
    """Store bike details by company and model.

    `ttl` is accepted for call-compatibility with `store.save_bike_details` but is
    no longer persisted — staleness is measured against the module-level
    TTL_DETAILS, mirroring how save_search/get_search_by_query use TTL_SEARCH.
    """
    session = get_session()
    try:
        # Get or create bike
        bike = session.query(Bike).filter_by(
            brand=company,
            model=model,
        ).first()
        if not bike:
            bike = Bike(brand=company, model=model)
            session.add(bike)
            session.flush()

        # Remove old details if exists
        old_details = session.query(BikeDetails).filter_by(bike_id=bike.id).first()
        if old_details:
            session.delete(old_details)
            session.flush()

        # Create new details
        details = BikeDetails(
            bike_id=bike.id,
            description=data.description.model_dump_json(),
        )
        session.add(details)
        session.flush()

        # Add photos
        for idx, photo_url in enumerate(data.photos):
            session.add(BikeDetailPhoto(
                bike_detail_id=details.id,
                url=photo_url,
                display_order=idx,
            ))

        # Flatten the whole tree into one row per spec, each carrying its
        # element/subcategory/category ancestry. `component_order` is a running
        # counter across the tree so rows sharing a category stay contiguous;
        # element_order and spec_order order the levels beneath it.
        # An element with no specs still emits one row, with the spec_* columns
        # NULL — that is what makes `specs: []` survive the round-trip.
        comp_order = 0
        for category in data.components:
            for subcategory in category.subcategories:
                for e_idx, element in enumerate(subcategory.elements):
                    specs = list(element.specs)
                    if not specs:
                        session.add(BikeDetailComponent(
                            bike_detail_id=details.id,
                            category=category.category,
                            subcategory=subcategory.subcategory,
                            component_order=comp_order,
                            element_name=element.name,
                            element_description=element.description,
                            element_order=e_idx,
                            spec_key=None,
                            spec_value=None,
                            spec_order=None,
                        ))
                        continue
                    for s_idx, spec in enumerate(specs):
                        session.add(BikeDetailComponent(
                            bike_detail_id=details.id,
                            category=category.category,
                            subcategory=subcategory.subcategory,
                            component_order=comp_order,
                            element_name=element.name,
                            element_description=element.description,
                            element_order=e_idx,
                            spec_key=spec.key,
                            spec_value=spec.value,
                            spec_order=s_idx,
                        ))
                comp_order += 1

        session.commit()
        logger.info("bike_details stored | company=%r model=%r", company, model)
    except Exception as exc:
        session.rollback()
        logger.warning("bike_details store failed (non-fatal) | %s", exc)
    finally:
        session.close()


def get_bike_details(company: str, model: str) -> Optional[BikeDetailsResponse]:
    """Retrieve bike details by company and model."""
    session = get_session()
    try:
        bike = session.query(Bike).filter_by(
            brand=company,
            model=model,
        ).first()

        if not bike:
            logger.info("bike_details miss | company=%r model=%r", company, model)
            return None

        details = session.query(BikeDetails).filter_by(bike_id=bike.id).first()
        if not details:
            logger.info("bike_details miss | company=%r model=%r", company, model)
            return None

        # Check TTL (handle both naive and aware datetimes)
        now = datetime.now(timezone.utc)
        updated_at = details.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        age = (now - updated_at).total_seconds()
        if age > TTL_DETAILS:
            logger.info("bike_details stale | company=%r model=%r", company, model)
            return None

        # Fetch photos
        photos = [p.url for p in sorted(details.photos, key=lambda x: x.display_order)]

        # Parse stored JSON
        description = BikeDescription.model_validate_json(details.description)

        components = rebuild_components(details.components)

        response = BikeDetailsResponse(
            company=bike.brand,
            model=bike.model,
            description=description,
            components=components,
            photos=photos,
        )

        logger.info("bike_details hit | company=%r model=%r", company, model)
        return response
    finally:
        session.close()


# ── DB-first bike search (TODO-024) ─────────────────────────────────────────
# A bike matches when EVERY checkable field given matches; bike_type / year /
# free text are ignored. A missing spec row does not match. Normalise in Python:
# SQLite's lower() is ASCII-only, so 'RIESE & MÜLLER' would miss 'riese & müller'.

BATTERY_TOLERANCE = 0.10  # ±10 % — "500 Wh" should still find a 504 Wh pack

_SPEC_FIELDS = (
    "frame_material", "wheel_size", "frame_size", "gender", "is_electric",
    "battery_capacity_wh", "brake_type", "drivetrain", "belt_drive",
)
CHECKABLE_FIELDS = ("brand", "model") + _SPEC_FIELDS

_ELECTRIC = "Electric / Powertrain"

_MATERIAL_SYNONYMS = {
    "aluminum": ("alumin", "alloy", "al6", "al 6", "6061", "6066", "7005"),
    "carbon": ("carbon",),
    "steel": ("steel", "chromoly", "cro-mo", "crmo", "cromo", "hi-ten", "4130"),
    "titanium": ("titanium",),
}
_WHEEL_SYNONYMS = {
    "700c": ("700c", "700", "28"),
    "28": ("28", "700c", "700"),
    "650b": ("650b", "27.5"),
    "27.5": ("27.5", "650b"),
}
_GENDER_PATTERNS = {
    "male": r"\bmen|\bmale|\bunisex|\buniversal",
    "female": r"\bwomen|\bfemale|\bladies|\bunisex|\buniversal",
    "universal": r"\bunisex|\buniversal",
}
# Element descriptions are generated in Polish, so the patterns also carry the
# Polish stems ("hydrauliczne" already contains "hydraulic").
_BRAKE_PATTERNS = {
    "hydraulic disc": r"hydraulic",
    "mechanical disc": r"mechanical|cable[^|]*disc|mechaniczn|linkow[^|]*tarcz",
    "v-brake": r"v-?\s?brake|linear[- ]pull",
    "rim": r"\brim\b|v-?\s?brake|linear[- ]pull|cantilever|dual[- ]pivot|side-?pull|obręczow|szczękow",
}
_DISC_PATTERN = r"disc|tarcz"
_SIZE_ALIASES = {"SM": "S", "MD": "M", "LG": "L", "2XL": "XXL"}


def _lc(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def checkable_fields(req) -> dict:
    """The DB-checkable fields the caller actually set (value is not None)."""
    return {f: getattr(req, f) for f in CHECKABLE_FIELDS if getattr(req, f) is not None}


class _BikeSpecs:
    """One bike's component rows, kept flat so each matcher filters one list."""

    def __init__(self) -> None:
        self.categories: set[str] = set()
        self.rows: list[tuple[str, str, str, str, str]] = []  # cat, sub, element, key, value
        self.descriptions: dict[str, list[str]] = {}  # category -> element descriptions

    def values(self, key: str, category: Optional[str] = None, sub: Optional[str] = None) -> list[str]:
        return [
            v for c, s, _, k, v in self.rows
            if _lc(k) == key and v and (category is None or c == category) and (sub is None or s == sub)
        ]

    def blob(self, category: str) -> str:
        """Element names, descriptions and spec values of one category, lowercased.

        Descriptions matter: many brakes are named only by model ("SRAM Maven
        Silver") and say "Hydraulic Disc Brake" only in their description.
        """
        parts = list(self.descriptions.get(category, []))
        for c, _, e, _, v in self.rows:
            if c == category:
                parts += [e, v]
        return " | ".join(_lc(p) for p in parts if p)

    def subcategories(self, category: str) -> set[str]:
        return {s for c, s, *_ in self.rows if c == category}


def _match_material(specs: _BikeSpecs, want: str) -> bool:
    needles = _MATERIAL_SYNONYMS.get(_lc(want), (_lc(want),))
    return any(any(n in _lc(v) for n in needles) for v in specs.values("material", "Frame", "Frame"))


def _match_wheel(specs: _BikeSpecs, want: str) -> bool:
    token = re.sub(r'"|inch(es)?|\bin\b', "", _lc(want)).strip()
    needles = _WHEEL_SYNONYMS.get(token, (token,))
    for v in specs.values("wheel size") + specs.values("size", "Wheels"):
        if any(re.search(rf"(?<![\d.]){re.escape(n)}(?![\d.])", _lc(v)) for n in needles):
            return True
    return False


def _match_frame_size(specs: _BikeSpecs, want: str) -> bool:
    target = _SIZE_ALIASES.get(want.strip().upper(), want.strip().upper())
    for v in specs.values("sizes", "Frame", "Frame") + specs.values("size", "Frame", "Frame"):
        tokens = {t for t in re.split(r"[\s,/()\-]+", v.upper()) if t}
        if target in {_SIZE_ALIASES.get(t, t) for t in tokens}:
            return True
    return False


def _match_gender(specs: _BikeSpecs, want: str) -> bool:
    pattern = _GENDER_PATTERNS.get(_lc(want), re.escape(_lc(want)))
    return any(re.search(pattern, _lc(v)) for v in specs.values("gender"))


def _match_battery(specs: _BikeSpecs, want: int) -> bool:
    for v in specs.values("capacity", _ELECTRIC, "Battery"):
        m = re.search(r"(\d{2,4}(?:[.,]\d+)?)\s*wh", _lc(v))
        if m and abs(float(m.group(1).replace(",", ".")) - want) <= want * BATTERY_TOLERANCE:
            return True
    return False


def _match_brake(specs: _BikeSpecs, want: str) -> bool:
    blob = specs.blob("Brakes")
    pattern = _BRAKE_PATTERNS.get(_lc(want), re.escape(_lc(want)))
    if not blob or re.search(pattern, blob) is None:
        return False
    # Rim brakes and discs are exclusive; "rim" can turn up in a disc bike's
    # description ("rotor mount on the rim side"), so a disc mention (English
    # "disc" or Polish "tarcza"/"tarczowe") vetoes it.
    return not (_lc(want) in ("rim", "v-brake") and re.search(_DISC_PATTERN, blob))


def _match_drivetrain(specs: _BikeSpecs, want: str) -> bool:
    blob = specs.blob("Drivetrain")
    if not blob:
        return False
    m = re.fullmatch(r"([123])\s*x", _lc(want))
    if not m:
        return _lc(want) in blob
    n = m.group(1)
    # "1x12" / "2x11" / "1x drivetrain"; the lookbehind stops "52x36T" reading as 2x.
    if re.search(rf"(?<![\d.]){n}\s?x(?!\d{{2}}t)", blob):
        return True
    # Otherwise infer from the chainring spec: "32T" (with no front derailleur)
    # is 1x, "50/34T" is 2x, "48/38/28T" is 3x.
    has_fd = "Front Derailleur" in specs.subcategories("Drivetrain")
    for v in specs.values("chainrings", "Drivetrain") + specs.values("chainring", "Drivetrain"):
        rings = re.findall(r"\d{2}", v.split("(")[0])
        if n == "1" and len(rings) == 1 and not has_fd:
            return True
        if n in ("2", "3") and "/" in v and len(rings) == int(n):
            return True
    return False


def _match_belt(specs: _BikeSpecs, want: bool) -> bool:
    has_belt = any("belt" in _lc(e) for c, _, e, _, _ in specs.rows if c == "Drivetrain")
    return has_belt == want


_MATCHERS = {
    "frame_material": _match_material,
    "wheel_size": _match_wheel,
    "frame_size": _match_frame_size,
    "gender": _match_gender,
    "is_electric": lambda specs, want: (_ELECTRIC in specs.categories) == want,
    "battery_capacity_wh": _match_battery,
    "brake_type": _match_brake,
    "drivetrain": _match_drivetrain,
    "belt_drive": _match_belt,
}

# Polish display names for the English filter values the frontend sends
# (mirrors the option labels in frontend SearchInput.tsx); unknown values pass through.
_PL_MATERIAL = {"aluminum": "aluminiowa", "aluminium": "aluminiowa", "carbon": "karbonowa", "steel": "stalowa"}
_PL_GENDER = {"male": "męski", "female": "damski", "universal": "uniwersalny"}
_PL_BRAKE = {
    "hydraulic disc": "tarczowe hydrauliczne",
    "mechanical disc": "tarczowe mechaniczne",
    "v-brake": "V-brake",
    "rim": "obręczowe",
}

_MATCH_LABELS = {
    "brand": lambda v: f"marka {v}",
    "model": lambda v: f"model {v}",
    "frame_material": lambda v: f"rama {_PL_MATERIAL.get(_lc(v), v)}",
    "wheel_size": lambda v: f"koła {v}",
    "frame_size": lambda v: f"rozmiar {v}",
    "gender": lambda v: f"geometria {_PL_GENDER.get(_lc(v), v)}",
    "is_electric": lambda v: "elektryczny" if v else "bez napędu elektrycznego",
    "battery_capacity_wh": lambda v: f"bateria ~{v} Wh",
    "brake_type": lambda v: f"hamulce {_PL_BRAKE.get(_lc(v), v)}",
    "drivetrain": lambda v: f"napęd {v}",
    "belt_drive": lambda v: "napęd paskowy" if v else "bez napędu paskowego",
}


def _describe_match(fields: dict) -> str:
    """'Pasuje: rama karbonowa, koła 29", hamulce tarczowe hydrauliczne.' for a DB hit."""
    return "Pasuje: " + ", ".join(_MATCH_LABELS[f](v) for f, v in fields.items()) + "."


def _latest_ratings(session, bike_ids: list[int]) -> dict[int, tuple[float, str, list[str]]]:
    """Most recent search_bike_rating_cache row per bike, if any."""
    if not bike_ids:
        return {}
    rows = session.execute(
        text(
            "SELECT r.bike_id, r.rating, r.explanation, r.accessories "
            "FROM search_bike_rating_cache r JOIN search_cache s ON s.id = r.search_cache_id "
            f"WHERE r.bike_id IN ({','.join(str(int(i)) for i in bike_ids)}) "
            "ORDER BY s.time_stored DESC, r.id DESC"
        )
    ).fetchall()
    out: dict[int, tuple[float, str, list[str]]] = {}
    for bike_id, rating, explanation, accessories in rows:
        if bike_id in out:
            continue
        try:
            acc = json.loads(accessories) if accessories else []
        except (TypeError, ValueError):
            acc = []
        out[bike_id] = (float(rating), explanation or "", [str(a) for a in acc])
    return out


def find_bikes_by_details(req) -> list[BikeResult]:
    """DB-first search over bike + bike_detail_component — no AI call.

    [] (→ AI fallback) when no checkable field is set, nothing matches, or the
    DB errors. Every match is returned (no cap), best rating first.
    """
    fields = checkable_fields(req)
    if not fields:
        return []
    session = get_session()
    try:
        brand, model = _lc(fields.get("brand")), _lc(fields.get("model"))
        candidates = [
            b for b in session.query(Bike.id, Bike.brand, Bike.model).all()
            if (not brand or _lc(b.brand) == brand) and (not model or _lc(b.model) == model)
        ]
        spec_fields = {f: v for f, v in fields.items() if f in _MATCHERS}
        if spec_fields and candidates:
            detail_by_bike = dict(
                session.query(BikeDetails.bike_id, BikeDetails.id)
                .filter(BikeDetails.bike_id.in_([b.id for b in candidates]))
                .all()
            )
            specs = {d: _BikeSpecs() for d in detail_by_bike.values()}
            rows = (
                session.query(
                    BikeDetailComponent.bike_detail_id, BikeDetailComponent.category,
                    BikeDetailComponent.subcategory, BikeDetailComponent.element_name,
                    BikeDetailComponent.spec_key, BikeDetailComponent.spec_value,
                    BikeDetailComponent.element_description, BikeDetailComponent.spec_order,
                )
                .filter(BikeDetailComponent.bike_detail_id.in_(list(specs)))
                .all()
            )
            for detail_id, cat, sub, elem, key, value, desc, spec_order in rows:
                bucket = specs[detail_id]
                bucket.categories.add(cat)
                bucket.rows.append((cat, sub, elem or "", key or "", value or ""))
                if desc and not spec_order:  # once per element, not once per spec row
                    bucket.descriptions.setdefault(cat, []).append(desc)
            # A bike with no details cannot prove any spec, so it never matches.
            candidates = [
                b for b in candidates
                if b.id in detail_by_bike
                and all(_MATCHERS[f](specs[detail_by_bike[b.id]], v) for f, v in spec_fields.items())
            ]

        ratings = _latest_ratings(session, [b.id for b in candidates])
        default = (10.0, _describe_match(fields), [])
        results = []
        for b in candidates:
            score, explanation, accessories = ratings.get(b.id, default)
            results.append(BikeResult(
                brand=b.brand, model=b.model, accessories=accessories,
                match_score=score, explanation=explanation,
            ))
        results.sort(key=lambda r: (-r.match_score, _lc(r.brand), _lc(r.model)))
        logger.info(
            "find_bikes_by_details | fields=%s matches=%d", sorted(fields), len(results),
        )
        return results
    except Exception as exc:  # noqa: BLE001 — a DB read must never break search
        logger.warning("find_bikes_by_details failed (non-fatal) | %s", exc)
        return []
    finally:
        session.close()


# ── Missing-data requests (TODO-026) ────────────────────────────────────────


def _find_bike_id(session, company: str, model: str) -> Optional[int]:
    """Identity lookup normalised in Python (`strip().lower()`), never created.

    SQLite's lower() is ASCII-only, so the compare happens here rather than in
    SQL — see find_bikes_by_details. Oldest row wins should a case-split
    duplicate identity exist.
    """
    brand, name = _lc(company), _lc(model)
    return next(
        (b.id for b in session.query(Bike.id, Bike.brand, Bike.model).order_by(Bike.id)
         if _lc(b.brand) == brand and _lc(b.model) == name),
        None,
    )


def record_missing_request(company: str, model: str, missing_type: str) -> MissingDataResponse:
    """Count one user request for a missing details section of an existing bike.

    The bike is looked up, never created: `save_search` always writes it before
    the details view can open, so a miss means that write was swallowed (locked
    SQLite, unmigrated DB). A miss or a failed write returns counter 0 and
    leaves the DB untouched.
    """
    session = get_session()
    try:
        bike_id = _find_bike_id(session, company, model)
        if bike_id is None:
            logger.error(
                "missing request: bike not found, nothing recorded | company=%r model=%r type=%r",
                company, model, missing_type,
            )
            return MissingDataResponse(bike_id=None, missing_type=missing_type, counter=0)

        # One atomic upsert: first request inserts counter=1, later ones add 1.
        # SQLite and PostgreSQL both support INSERT … ON CONFLICT DO UPDATE.
        stmt = dialect_insert(BikeMissingRequest).values(
            bike_id=bike_id, missing_type=missing_type, counter=1,
        )
        session.execute(stmt.on_conflict_do_update(
            index_elements=["bike_id", "missing_type"],
            set_={"counter": BikeMissingRequest.counter + 1},
        ))
        counter = session.query(BikeMissingRequest.counter).filter_by(
            bike_id=bike_id, missing_type=missing_type,
        ).scalar()
        session.commit()
        logger.info(
            "missing request recorded | bike_id=%d type=%r counter=%d", bike_id, missing_type, counter,
        )
        return MissingDataResponse(bike_id=bike_id, missing_type=missing_type, counter=counter)
    except Exception as exc:  # noqa: BLE001 — a failed tally must not break the details view
        session.rollback()
        logger.error(
            "missing request store failed | company=%r model=%r type=%r | %s",
            company, model, missing_type, exc,
        )
        return MissingDataResponse(bike_id=None, missing_type=missing_type, counter=0)
    finally:
        session.close()
