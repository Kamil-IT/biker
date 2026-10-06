"""Data access layer using SQLAlchemy ORM models."""
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import OperationalError, ProgrammingError

from .component_tree import flatten_components, rebuild_components  # noqa: F401 — re-exported
from .models import (
    Bike,
    BikeComponent,
    BikeMissingRequest,
    dialect_insert,
    get_session,
    norm,
)
from .schemas import (
    BikeDetailsResponse,
    BikeDescription,
    BikeResult,
    MissingDataResponse,
)

logger = logging.getLogger(__name__)

# store.py puts AI-found bikes into `bike` (save_search). This module owns the bike-details helpers and the DB-first search below.


def save_bike_details(company: str, model: str, data: BikeDetailsResponse) -> bool:
    """Store bike details by company and model; True = committed, False = failed.

    Updates the bike row's `description` / `short_description` in place and
    replaces its component rows. Photos are keyed on `bike` too, so they are
    neither written nor touched here — a re-save keeps them (photos_repository
    owns them). Errors are swallowed (WARNING log, rollback) and reported as False.
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

        # TODO-042: snapshot the equipment links before the component rows go.
        links = _equipment_links(session, bike.id)
        bike.description = data.description.model_dump_json()
        bike.short_description = data.short_description or ""
        bike.updated_at = datetime.now(timezone.utc)
        session.query(BikeComponent).filter_by(
            bike_id=bike.id,
        ).delete(synchronize_session=False)
        session.expire(bike, ["components"])
        session.flush()

        # One row per spec (component_tree.flatten_components). TODO-042: a row
        # gets back the equipment link its element name had before the re-save;
        # an incoming element.equipment_id is ignored (it may be another DB's id).
        for row in flatten_components(data.components, include_linkable=True):
            session.add(BikeComponent(
                bike_id=bike.id,
                equipment_id=links.get(norm(row["element_name"])),
                **row,
            ))

        session.commit()
        logger.info("bike_details stored | company=%r model=%r", company, model)
        return True
    except Exception as exc:
        session.rollback()
        logger.warning("bike_details store failed (non-fatal) | %s", exc)
        return False
    finally:
        session.close()


def _equipment_links(session, bike_id: int) -> dict[str, int]:
    """norm(element_name) -> equipment_id of one bike's linked component rows (TODO-042)."""
    links: dict[str, int] = {}
    for name, equipment_id in session.query(
        BikeComponent.element_name, BikeComponent.equipment_id,
    ).filter(
        BikeComponent.bike_id == bike_id,
        BikeComponent.equipment_id.isnot(None),
    ).order_by(BikeComponent.id):
        links.setdefault(norm(name), equipment_id)
    return links


EQUIPMENT_MIGRATION_HINT = "run backend/scripts/migrate_equipment_tables.py"


def _log_schema_error(what: str, exc: Exception) -> None:
    """ERROR for a DB schema error, naming the TODO-042 migration.

    The ORM reads bike_component.equipment_id, which create_all() never
    adds to an existing table — an unmigrated database fails here ("no such
    column" / "does not exist") without saying why.
    """
    logger.error(
        "%s failed: database schema error — if bike_component.equipment_id is missing, "
        "the database is not migrated, %s | %s", what, EQUIPMENT_MIGRATION_HINT, exc,
    )


def get_bike_details(company: str, model: str) -> Optional[BikeDetailsResponse]:
    """Retrieve bike details by company and model, whatever their age (no TTL).

    Photos are not part of the details any more — see photos_repository.
    """
    session = get_session()
    try:
        # Identity matched on the Python-normalised brand/model (TODO-041), so a
        # discovered bike is found whatever casing the caller uses; the response
        # carries the stored casing (POST /v1/bike/details echoes the caller's).
        bike_id = _find_bike_id(session, company, model)
        bike = session.get(Bike, bike_id) if bike_id is not None else None

        if not bike:
            logger.info("bike_details miss | company=%r model=%r", company, model)
            return None

        if bike.description is None:
            logger.info("bike_details miss | company=%r model=%r", company, model)
            return None

        # Parse stored JSON
        description = BikeDescription.model_validate_json(bike.description)

        components = rebuild_components(bike.components)

        response = BikeDetailsResponse(
            company=bike.brand,
            model=bike.model,
            description=description,
            components=components,
            short_description=bike.short_description or "",
            category=bike.category,
        )

        logger.info("bike_details hit | company=%r model=%r", company, model)
        return response
    except (OperationalError, ProgrammingError) as exc:
        _log_schema_error("get_bike_details", exc)
        raise
    finally:
        session.close()


def empty_details(company: str, model: str) -> BikeDetailsResponse:
    """The "nothing stored" answer of POST /v1/bike/details (TODO-041)."""
    return BikeDetailsResponse(
        company=company,
        model=model,
        description=BikeDescription(text="", segments=[], citations=[]),
        components=[],
        short_description="",
        category=None,
    )


# ── Search-result fill (TODO-041) ───────────────────────────────────────────
# explanation = the bike's stored bike.short_description; accessories =
# chips derived from its stored components, no AI. One builder for every place
# that returns a BikeResult (DB hit, AI fallback, search-cache readers).

# (category, subcategory, spec key or None) — the first candidate of a group that
# has a stored value wins, so the chip order is drivetrain, brakes, frame.
# The "Brake Lever" fallback is what the discovery scraper (spec_mapping.py) stores.
_CHIP_SOURCES: tuple[tuple[tuple[str, str, Optional[str]], ...], ...] = (
    (("Drivetrain", "Rear Derailleur", None), ("Drivetrain", "Crank", None)),
    (("Brakes", "Brake Lever Front", None), ("Brakes", "Brake Lever", None), ("Brakes", "Brake Rotor", None)),
    (("Frame", "Frame", "Material"),),
)


def _chips_from_rows(rows) -> list[str]:
    """`rows`: (category, subcategory, element_name, spec_key, spec_value) of one bike."""
    chips: list[str] = []
    for candidates in _CHIP_SOURCES:
        for cat, sub, key in candidates:
            value = next(
                (
                    ((spec_value if key else element_name) or "").strip()
                    for c, s, element_name, spec_key, spec_value in rows
                    if c == cat and s == sub and (key is None or spec_key == key)
                    and ((spec_value if key else element_name) or "").strip()
                ),
                None,
            )
            if value:
                chips.append(value)
                break
    return chips


def _search_fill(session, bike_ids: list[int]) -> dict[int, tuple[str, list[str]]]:
    """bike_id -> (short_description, chips) for the bikes that have stored details."""
    if not bike_ids:
        return {}
    bikes = session.query(Bike.id, Bike.short_description).filter(
        Bike.id.in_(list(bike_ids)), Bike.description.isnot(None),
    ).all()
    rows_by_bike: dict[int, list] = {b.id: [] for b in bikes}
    if rows_by_bike:
        for bike_id, cat, sub, el, key, value in session.query(
            BikeComponent.bike_id, BikeComponent.category,
            BikeComponent.subcategory, BikeComponent.element_name,
            BikeComponent.spec_key, BikeComponent.spec_value,
        ).filter(BikeComponent.bike_id.in_(list(rows_by_bike))).order_by(
            BikeComponent.component_order, BikeComponent.element_order,
            BikeComponent.spec_order,
        ):
            rows_by_bike[bike_id].append((cat, sub, el, key, value))
    return {
        b.id: ((b.short_description or ""), _chips_from_rows(rows_by_bike[b.id]))
        for b in bikes
    }


def fill_bike_results(bikes: list[BikeResult]) -> list[BikeResult]:
    """Fill `explanation` / `accessories` of result bikes from stored details (AI path).

    Bikes are matched by Python-normalised brand + model; a bike without stored
    details keeps `""` / `[]`. Never raises — a DB error returns the bikes unfilled.
    """
    if not bikes:
        return bikes
    session = get_session()
    try:
        ids = {}
        cats = {}
        for b in session.query(Bike.id, Bike.brand, Bike.model, Bike.category).order_by(Bike.id.desc()):
            ids[(_lc(b.brand), _lc(b.model))] = b.id
            cats[b.id] = b.category  # oldest row wins (iterated last)
        fill = _search_fill(session, [i for i in (ids.get((_lc(r.brand), _lc(r.model))) for r in bikes) if i])
        out = []
        for r in bikes:
            explanation, chips = fill.get(ids.get((_lc(r.brand), _lc(r.model))), ("", []))
            out.append(BikeResult(brand=r.brand, model=r.model, accessories=chips, explanation=explanation,
                                  category=cats.get(ids.get((_lc(r.brand), _lc(r.model))))))
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("fill_bike_results failed (non-fatal) | %s", exc)
        return bikes
    finally:
        session.close()


def accessory_chips(bike_id: int) -> list[str]:
    """Chips of one bike from its stored components: drivetrain, brakes, frame material.

    Drivetrain → the Rear Derailleur (else Crank) element name; Brakes → the
    Brake Lever Front (else Brake Lever, else Brake Rotor) element name; Frame →
    the Frame element's `Material` spec value. A missing part is skipped.
    """
    session = get_session()
    try:
        return _search_fill(session, [bike_id]).get(bike_id, ("", []))[1]
    finally:
        session.close()


# ── DB-first bike search (TODO-024) ─────────────────────────────────────────
# A bike matches when EVERY checkable field given matches; bike_type / year /
# free text are ignored. A missing spec row does not match. Normalise in Python:
# SQLite's lower() is ASCII-only, so 'RIESE & MÜLLER' would miss 'riese & müller'.

_SPEC_FIELDS = ("wheel_size", "frame_size", "is_electric")
CHECKABLE_FIELDS = ("brand", "model") + _SPEC_FIELDS

_ELECTRIC = "Electric / Powertrain"

_WHEEL_SYNONYMS = {
    "700c": ("700c", "700", "28"),
    "28": ("28", "700c", "700"),
    "650b": ("650b", "27.5"),
    "27.5": ("27.5", "650b"),
}
_SIZE_ALIASES = {"SM": "S", "MD": "M", "LG": "L", "2XL": "XXL"}


def _lc(s: Optional[str]) -> str:
    return norm(s)


def checkable_fields(req) -> dict:
    """The DB-checkable fields the caller actually set (value is not None)."""
    return {f: getattr(req, f) for f in CHECKABLE_FIELDS if getattr(req, f) is not None}


class _BikeSpecs:
    """One bike's component rows, kept flat so each matcher filters one list."""

    def __init__(self) -> None:
        self.categories: set[str] = set()
        self.rows: list[tuple[str, str, str, str, str]] = []  # cat, sub, element, key, value

    def values(self, key: str, category: Optional[str] = None, sub: Optional[str] = None) -> list[str]:
        return [
            v for c, s, _, k, v in self.rows
            if _lc(k) == key and v and (category is None or c == category) and (sub is None or s == sub)
        ]


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


_MATCHERS = {
    "wheel_size": _match_wheel,
    "frame_size": _match_frame_size,
    "is_electric": lambda specs, want: (_ELECTRIC in specs.categories) == want,
}

def find_bikes_by_details(req) -> list[BikeResult]:
    """DB-first search over bike + bike_component — no AI call.

    [] (→ AI fallback) when no checkable field is set, nothing matches, or the
    DB errors. Every match is returned (no cap), sorted by brand then model
    (TODO-040: there is no match score any more — the frontend orders by expert rating).
    """
    fields = checkable_fields(req)
    if not fields:
        return []
    session = get_session()
    try:
        brand, model = _lc(fields.get("brand")), _lc(fields.get("model"))
        candidates = [
            b for b in session.query(Bike.id, Bike.brand, Bike.model, Bike.category).all()
            if (not brand or _lc(b.brand) == brand) and (not model or _lc(b.model) == model)
        ]
        spec_fields = {f: v for f, v in fields.items() if f in _MATCHERS}
        if spec_fields and candidates:
            with_details = {
                r[0] for r in session.query(Bike.id)
                .filter(Bike.id.in_([b.id for b in candidates]), Bike.description.isnot(None))
                .all()
            }
            specs = {i: _BikeSpecs() for i in with_details}
            rows = (
                session.query(
                    BikeComponent.bike_id, BikeComponent.category,
                    BikeComponent.subcategory, BikeComponent.element_name,
                    BikeComponent.spec_key, BikeComponent.spec_value,
                )
                .filter(BikeComponent.bike_id.in_(list(specs)))
                .all()
            )
            for bike_id, cat, sub, elem, key, value in rows:
                bucket = specs[bike_id]
                bucket.categories.add(cat)
                bucket.rows.append((cat, sub, elem or "", key or "", value or ""))
            # A bike with no details cannot prove any spec, so it never matches.
            candidates = [
                b for b in candidates
                if b.id in with_details
                and all(_MATCHERS[f](specs[b.id], v) for f, v in spec_fields.items())
            ]

        fill = _search_fill(session, [b.id for b in candidates])
        results = []
        for b in candidates:
            explanation, accessories = fill.get(b.id, ("", []))
            results.append(BikeResult(
                brand=b.brand, model=b.model, accessories=accessories, explanation=explanation,
                category=b.category,
            ))
        results.sort(key=lambda r: (_lc(r.brand), _lc(r.model)))
        logger.info(
            "find_bikes_by_details | fields=%s matches=%d", sorted(fields), len(results),
        )
        return results
    except (OperationalError, ProgrammingError) as exc:
        _log_schema_error("find_bikes_by_details", exc)
        return []
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
