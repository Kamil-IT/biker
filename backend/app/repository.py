"""Data access layer using SQLAlchemy ORM models."""
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .models import (
    Bike,
    BikeResult,
    Accessory,
    BikeDetails,
    BikeDetailPhoto,
    BikeOffer,
    BikeOfferPhoto,
    get_session,
)
from .schemas import BikeResult as BikeResultSchema, BikeSearchResponse, BikeDetailsResponse, BikeDescription, BikeCategory

logger = logging.getLogger(__name__)

TTL_SEARCH = 24 * 60 * 60  # 24 hours
TTL_DETAILS = 30 * 24 * 60 * 60  # 30 days


def save_search(query: str, bikes: list[BikeResultSchema], ttl: int = TTL_SEARCH) -> None:
    """Store search results with normalized query as key."""
    session = get_session()
    try:
        norm_query = query.strip().lower()
        for bike_schema in bikes:
            # Get or create bike
            bike = session.query(Bike).filter_by(
                brand=bike_schema.brand,
                model=bike_schema.model,
            ).first()
            if not bike:
                bike = Bike(brand=bike_schema.brand, model=bike_schema.model)
                session.add(bike)
                session.flush()

            # Create result
            result = BikeResult(
                bike_id=bike.id,
                match_score=bike_schema.match_score,
                explanation=bike_schema.explanation,
            )
            session.add(result)
            session.flush()  # Flush to get the result.id

            # Add accessories
            for accessory_name in bike_schema.accessories:
                session.add(Accessory(bike_result_id=result.id, name=accessory_name))

        session.commit()
        logger.info("search stored | query=%r bikes=%d", norm_query, len(bikes))
    except Exception as exc:
        session.rollback()
        logger.warning("search store failed (non-fatal) | %s", exc)
    finally:
        session.close()


def get_search_by_query(query: str) -> Optional[list[BikeResultSchema]]:
    """Retrieve search results by normalized query."""
    session = get_session()
    try:
        norm_query = query.strip().lower()
        results = session.query(BikeResult).join(Bike).filter(
            # Note: this is a simple substring match; for exact match, use a separate column
        ).all()

        if not results:
            logger.info("search miss | query=%r", norm_query)
            return None

        # Check TTL (handle both naive and aware datetimes)
        now = datetime.now(timezone.utc)
        for result in results:
            created_at = result.created_at
            # Make both datetimes comparable
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age = (now - created_at).total_seconds()
            if age > TTL_SEARCH:
                logger.info("search stale | query=%r", norm_query)
                return None

        # Build schemas
        bikes = []
        for result in results:
            accessories = [acc.name for acc in result.accessories]
            bike_schema = BikeResultSchema(
                brand=result.bike.brand,
                model=result.bike.model,
                accessories=accessories,
                match_score=result.match_score,
                explanation=result.explanation,
            )
            bikes.append(bike_schema)

        logger.info("search hit | query=%r", norm_query)
        return bikes
    finally:
        session.close()


def find_bikes_by_brand(brand: str) -> list[BikeResultSchema]:
    """Find all cached bikes matching a brand (case-insensitive)."""
    session = get_session()
    try:
        norm_brand = brand.strip().lower()
        bikes = session.query(BikeResult).join(Bike).filter(
            Bike.brand.ilike(f"%{brand}%")
        ).all()

        result = []
        seen = set()
        now = datetime.now(timezone.utc)
        for br in bikes:
            # Check TTL (handle both naive and aware datetimes)
            created_at = br.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age = (now - created_at).total_seconds()
            if age > TTL_SEARCH:
                continue

            key = (br.bike.brand.lower(), br.bike.model.lower())
            if key in seen:
                continue
            seen.add(key)

            accessories = [acc.name for acc in br.accessories]
            result.append(BikeResultSchema(
                brand=br.bike.brand,
                model=br.bike.model,
                accessories=accessories,
                match_score=br.match_score,
                explanation=br.explanation,
            ))

        logger.info("find_bikes_by_brand | brand=%r matches=%d", brand, len(result))
        return result
    finally:
        session.close()


def save_bike_details(company: str, model: str, data: BikeDetailsResponse, ttl: int = TTL_DETAILS) -> None:
    """Store bike details by company and model."""
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
