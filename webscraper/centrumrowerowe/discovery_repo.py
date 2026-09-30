"""Bike / listing lookups shared by the scraper, the processor and the copy script (TODO-039).

A `bike_discovery` row is found by its normalised identity (company_norm, model_norm), a
`bike_discovery_listing` row by (source, source_product_id). Everything takes the caller's
Session and never commits.
"""
from typing import Optional

from sqlalchemy import and_, exists

from db import BikeDiscovery, BikeDiscoveryListing, norm


def find_bike(s, company: str, model: str) -> Optional[BikeDiscovery]:
    return s.query(BikeDiscovery).filter_by(company_norm=norm(company), model_norm=norm(model)).first()


def find_listing(s, source: str, source_product_id: str) -> Optional[BikeDiscoveryListing]:
    return s.query(BikeDiscoveryListing).filter_by(source=source, source_product_id=source_product_id).first()


def bike_ids_by_identity(s) -> dict[tuple[str, str], int]:
    """(company_norm, model_norm) → bike_discovery.id for every row, loaded once."""
    return {(n1, n2): i for i, n1, n2 in
            s.query(BikeDiscovery.id, BikeDiscovery.company_norm, BikeDiscovery.model_norm)}


def listed_by(source: str):
    """WHERE clause on BikeDiscovery: the bike has at least one listing from `source`."""
    return exists().where(and_(BikeDiscoveryListing.discovery_id == BikeDiscovery.id,
                               BikeDiscoveryListing.source == source))


def listings_newest_first(s, discovery_id: int) -> list[BikeDiscoveryListing]:
    """The bike's listings, most recently seen first (id breaks ties, newest first too)."""
    return (s.query(BikeDiscoveryListing).filter_by(discovery_id=discovery_id)
            .order_by(BikeDiscoveryListing.last_seen_at.desc(), BikeDiscoveryListing.id.desc()).all())


def identity_fields(s, discovery_id: int, company: str, model: str) -> dict:
    """company / model (with their norms, for a Core update) to write on bike `discovery_id`.

    {} when another bike_discovery row already owns that identity: the row keeps its own name
    rather than breaking UNIQUE(company_norm, model_norm).
    """
    other = find_bike(s, company, model)
    if other is not None and other.id != discovery_id:
        return {}
    return {"company": company, "model": model, "company_norm": norm(company), "model_norm": norm(model)}
