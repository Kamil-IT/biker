"""Data access layer using SQLAlchemy ORM models."""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from .models import (
    Bike,
    BikeResult,
    Search,
    Accessory,
    BikeDetails,
    BikeDetailPhoto,
    BikeOffer,
    BikeOfferPhoto,
    get_session,
    norm,
)
from .schemas import BikeResult as BikeResultSchema, BikeSearchResponse, BikeDetailsResponse, BikeDescription, BikeCategory

logger = logging.getLogger(__name__)

TTL_SEARCH = 24 * 60 * 60  # 24 hours
TTL_DETAILS = 30 * 24 * 60 * 60  # 30 days

_SCHEMA_HINT = (
    "the ORM schema is out of date — `init_db()` only CREATEs missing tables, it "
    "never ALTERs an existing one. Run `python scripts/migrate_bike_details.py` "
    "against this database."
)


def _log_db_failure(operation: str, exc: Exception) -> None:
    """Log a cache failure, shouting when it is a schema mismatch.

    A missing column is a deployment error, not a cache miss, and it must not
    read as one: a half-migrated DB whose writes all fail silently is otherwise
    indistinguishable from a cold cache in the logs, so the feature looks merely
    unused rather than broken.
    """
    text = str(exc).lower()
    # Both shapes appear: a missing table when the migration never ran at all,
    # a missing column when it ran before the schema grew.
    if isinstance(exc, OperationalError) and ("no such column" in text or "no such table" in text):
        logger.error("%s FAILED — %s | %s", operation, _SCHEMA_HINT, exc)
    else:
        logger.warning("%s failed (non-fatal) | %s", operation, exc)


def _find_bike_ci(session: Session, company: str, model: str) -> Optional[Bike]:
    """Locate a bike by brand+model, ignoring case and surrounding whitespace.

    Matches on the `brand_norm`/`model_norm` columns, which hold Python's
    `norm()` of the real values. Doing this with SQL instead — `func.lower()`
    or `ilike` — would be wrong: SQLite's `lower()` and `LIKE` are ASCII-only,
    so `lower('Riese & MÜller')` keeps the `Ü` and never equals the
    Python-lowercased `'riese & müller'` we would compare it against.

    `bikes` is shared with search and offers and stores real casing, so the
    identity row is never lowercased on write — only these lookup columns are.
    """
    return session.query(Bike).filter(
        Bike.brand_norm == norm(company),
        Bike.model_norm == norm(model),
    ).first()


def _get_or_create_bike(session: Session, brand: str, model: str) -> Bike:
    """Reuse the existing identity row for this bike, or mint one.

    Every `Bike` insert must go through here — a get-or-create that matches
    case-sensitively is what splits one bike into two identity rows.

    `bikes.brand`/`model` are the single source of display casing for search
    results, so a row whose stored value equals its own normalised form is
    treated as a placeholder carrying no casing information (the old details
    blob keyed on `strip().lower()`, so every row it seeded looks like that)
    and is upgraded by the first caller that supplies real casing. The rule is
    monotonic — an all-lowercase value never overwrites real casing — so this
    cannot oscillate between two writers.
    """
    bike = _find_bike_ci(session, brand, model)
    if bike is None:
        bike = Bike(brand=brand, model=model)
        session.add(bike)
        session.flush()
        return bike

    for attr, incoming in (("brand", brand), ("model", model)):
        stored = getattr(bike, attr)
        if stored == norm(stored) and incoming.strip() != norm(incoming):
            setattr(bike, attr, incoming.strip())
    return bike


def _is_fresh(created_at: datetime, ttl_seconds: int) -> bool:
    """TTL check tolerant of the naive datetimes SQLite hands back."""
    if created_at is None:
        return False
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - created_at).total_seconds() < ttl_seconds


def _result_to_schema(result: BikeResult) -> BikeResultSchema:
    return BikeResultSchema(
        brand=result.bike.brand,
        model=result.bike.model,
        accessories=[acc.name for acc in result.accessories],
        match_score=result.match_score,
        explanation=result.explanation,
    )


def save_search(query: str, bikes: list[BikeResultSchema], ttl: int = TTL_SEARCH) -> None:
    """Store search results, keyed by the normalised query.

    Upsert semantics, matching the blob table's `ON CONFLICT DO UPDATE`: an
    existing search for this query has its results replaced and its clock reset.
    Bikes are stored as references to `bikes`, not copies.
    """
    session = get_session()
    try:
        norm_query = norm(query)
        search = session.query(Search).filter(Search.query == norm_query).first()
        if search is None:
            search = Search(query=norm_query, ttl_seconds=ttl)
            session.add(search)
        else:
            # Replace the previous result set wholesale, and reset the TTL clock.
            for old in list(search.results):
                session.delete(old)
            session.flush()
            search.created_at = datetime.now(timezone.utc)
            search.ttl_seconds = ttl
        session.flush()

        for position, bike_schema in enumerate(bikes):
            bike = _get_or_create_bike(session, bike_schema.brand, bike_schema.model)
            result = BikeResult(
                search_id=search.id,
                bike_id=bike.id,
                position=position,
                match_score=bike_schema.match_score,
                explanation=bike_schema.explanation,
            )
            session.add(result)
            session.flush()  # Flush to get the result.id

            for accessory_name in bike_schema.accessories:
                session.add(Accessory(bike_result_id=result.id, name=accessory_name))

        session.commit()
        logger.info("search stored | query=%r bikes=%d", norm_query, len(bikes))
    except Exception as exc:  # noqa: BLE001 — cache writes must never break the request
        session.rollback()
        _log_db_failure("search store", exc)
    finally:
        session.close()


def get_search_by_query(query: str) -> Optional[list[BikeResultSchema]]:
    """Retrieve one search's results by normalised query, in stored order."""
    session = get_session()
    try:
        norm_query = norm(query)
        search = session.query(Search).filter(Search.query == norm_query).first()
        if search is None:
            logger.info("search miss | query=%r", norm_query)
            return None

        if not _is_fresh(search.created_at, search.ttl_seconds):
            logger.info("search stale | query=%r", norm_query)
            return None

        bikes = [_result_to_schema(r) for r in search.results]
        logger.info("search hit | query=%r bikes=%d", norm_query, len(bikes))
        return bikes
    finally:
        session.close()


def find_bikes_by_brand(brand: str) -> list[BikeResultSchema]:
    """Every de-duplicated cached bike of this brand, across all fresh searches.

    Matches `brand_norm` exactly, mirroring the blob implementation this
    replaces. Note this is NOT a substring match — `Bike.brand.ilike("%x%")`
    would both over-match ("Trek" finding "Trekker") and, being SQL `LIKE`,
    carry the ASCII-only case bug that `brand_norm` exists to avoid.
    """
    session = get_session()
    try:
        results = (
            session.query(BikeResult)
            .join(Bike)
            .filter(Bike.brand_norm == norm(brand))
            .all()
        )
        matches = _dedupe_fresh(results)
        logger.info("find_bikes_by_brand | brand=%r matches=%d", brand, len(matches))
        return matches
    finally:
        session.close()


def find_bike_by_brand_model(brand: str, model: str) -> list[BikeResultSchema]:
    """Every cached bike matching brand AND model, across all fresh searches.

    Backs TODO-009's DB-first branch of `POST /v1/bike/search`.
    """
    try:
        session = get_session()
        try:
            results = (
                session.query(BikeResult)
                .join(Bike)
                .filter(Bike.brand_norm == norm(brand), Bike.model_norm == norm(model))
                .all()
            )
            matches = _dedupe_fresh(results)
            logger.info(
                "find_bike_by_brand_model | brand=%r model=%r matches=%d",
                brand, model, len(matches),
            )
            return matches
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001 — cache reads must never break the request
        _log_db_failure("find_bike_by_brand_model", exc)
        return []


def _dedupe_fresh(results: list[BikeResult]) -> list[BikeResultSchema]:
    """Drop results from stale searches, then de-duplicate on bike identity."""
    matches: list[BikeResultSchema] = []
    seen: set[tuple[str, str]] = set()
    for r in results:
        search = r.search
        # A result orphaned from its search (pre-migration row) has no TTL to
        # judge it by; fall back to its own timestamp rather than trusting it.
        if search is not None:
            if not _is_fresh(search.created_at, search.ttl_seconds):
                continue
        elif not _is_fresh(r.created_at, TTL_SEARCH):
            continue

        key = (r.bike.brand_norm, r.bike.model_norm)
        if key in seen:
            continue
        seen.add(key)
        matches.append(_result_to_schema(r))
    return matches


def save_bike_details(company: str, model: str, data: BikeDetailsResponse, ttl: int = TTL_DETAILS) -> None:
    """Store bike details by company and model."""
    session = get_session()
    try:
        # Reuse an existing identity regardless of casing, leaving its stored
        # casing alone; only a brand-new row takes the caller's casing.
        bike = _get_or_create_bike(session, company, model)

        # Remove old details if exists
        old_details = session.query(BikeDetails).filter_by(bike_id=bike.id).first()
        if old_details:
            session.delete(old_details)
            session.flush()

        # Create new details
        details = BikeDetails(
            bike_id=bike.id,
            description=data.description.model_dump_json(),
            components=json.dumps([c.model_dump() for c in data.components]),
            ttl_seconds=ttl,
        )
        session.add(details)
        session.flush()

        # Add photos
        for idx, photo_url in enumerate(data.photos):
            session.add(BikeDetailPhoto(
                bike_details_id=details.id,
                url=photo_url,
                display_order=idx,
            ))

        session.commit()
        logger.info("bike_details stored | company=%r model=%r", company, model)
    except Exception as exc:  # noqa: BLE001 — cache writes must never break the request
        session.rollback()
        _log_db_failure("bike_details store", exc)
    finally:
        session.close()


def get_bike_details(company: str, model: str) -> Optional[BikeDetailsResponse]:
    """Retrieve bike details by company and model."""
    session = get_session()
    try:
        bike = _find_bike_ci(session, company, model)

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
        if age > details.ttl_seconds:
            logger.info("bike_details stale | company=%r model=%r", company, model)
            return None

        # Fetch photos
        photos = [p.url for p in sorted(details.photos, key=lambda x: x.display_order)]

        # Parse stored JSON
        description = BikeDescription.model_validate_json(details.description)
        components = [
            BikeCategory.model_validate(c)
            for c in json.loads(details.components)
        ]

        # Echo the caller's casing, not the stored row's — matches the blob path.
        response = BikeDetailsResponse(
            company=company,
            model=model,
            description=description,
            components=components,
            photos=photos,
        )

        logger.info("bike_details hit | company=%r model=%r", company, model)
        return response
    finally:
        session.close()
