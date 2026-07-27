"""Data access layer using SQLAlchemy ORM models."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from .models import (
    Bike,
    BikeDetails,
    BikeDetailPhoto,
    BikeDetailComponent,
    BikeOffer,
    BikeOfferPhoto,
    get_session,
)
from .schemas import (
    BikeDetailsResponse,
    BikeDescription,
    BikeCategory,
    BikeSubcategory,
    ComponentElement,
    SpecItem,
)

logger = logging.getLogger(__name__)

TTL_DETAILS = 30 * 24 * 60 * 60  # 30 days


# NOTE: the search-cache helpers (save_search / get_search_by_query /
# find_bikes_by_brand) used to live here, backed by the bike_results +
# accessories ORM tables. Those tables have been removed — the live search cache
# is search_cache + search_bike_rating_cache in app/store.py. This module now
# owns only the bike-details helpers below.


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
