"""Stored marketplace offers — the read side of bike_offer / bike_offer_photos (TODO-031).

Only OLX rows exist so far: they are written by the separate searcher service
(searcher/app/repository.py) and read here for POST /v1/bike/used. No TTL —
while rows exist the frontend's "Request data" button stays hidden, so nothing
re-triggers the search. Lives next to repository.py rather than in it to keep
that file from growing further past the 500-line limit.
"""
import logging

from .models import (
    Bike,
    BikeOffer as BikeOfferRow,  # aliased: schemas.BikeOffer is the response shape
    BikeOfferPhoto as BikeOfferPhotoRow,
    get_session,
)
from .repository import _find_bike_id
from .schemas import BikeOffer, UsedBikeResponse

logger = logging.getLogger(__name__)

OLX_SOURCE = "olx.pl"


def bike_exists(company: str, model: str) -> bool:
    """Whether the bike identity is known (Python-normalised brand/model compare).

    /v1/bike/used/search checks this before spending a searcher run: the
    searcher creates missing bikes for direct calls, and letting anonymous
    web traffic mint arbitrary `bike` rows would pollute the DB-first search.
    """
    session = get_session()
    try:
        return _find_bike_id(session, company, model) is not None
    finally:
        session.close()


def get_used_offers(company: str, model: str) -> UsedBikeResponse:
    """Stored OLX listings of one bike — a pure DB read, no AI, no generic cache.

    Rows come from bike_offer (source 'olx.pl') in id order, each with its
    bike_offer_photos ordered by display_order. brand/model on every offer are
    the bike row's (the single source of display casing). An unknown bike, no
    rows, or a DB error all yield the empty response — the details view must
    keep rendering whatever happens here.
    """
    session = get_session()
    try:
        bike_id = _find_bike_id(session, company, model)
        if bike_id is None:
            logger.info("used offers: bike not found | company=%r model=%r", company, model)
            return UsedBikeResponse(offers=[], info="")
        bike = session.get(Bike, bike_id)
        rows = (
            session.query(BikeOfferRow)
            .filter(BikeOfferRow.bike_id == bike_id, BikeOfferRow.source == OLX_SOURCE)
            .order_by(BikeOfferRow.id)
            .all()
        )
        # One query for every photo of these offers, not one lazy load per row.
        photos_by_offer: dict[int, list[str]] = {}
        if rows:
            photo_rows = (
                session.query(BikeOfferPhotoRow)
                .filter(BikeOfferPhotoRow.bike_offer_id.in_([r.id for r in rows]))
                .order_by(BikeOfferPhotoRow.display_order, BikeOfferPhotoRow.id)
            )
            for p in photo_rows:
                photos_by_offer.setdefault(p.bike_offer_id, []).append(p.url)
        offers = [
            BikeOffer(
                brand=bike.brand,
                model=bike.model,
                price=row.price,
                is_new=False,
                url=row.url,
                photos=photos_by_offer.get(row.id, []),
                source=row.source,
                city=row.city,
            )
            for row in rows
        ]
        logger.info(
            "used offers served from DB | company=%r model=%r bike_id=%d offers=%d",
            company, model, bike_id, len(offers),
        )
        return UsedBikeResponse(offers=offers, info="")
    except Exception as exc:  # noqa: BLE001 — a DB read must never break the details view
        logger.error("used offers read failed | company=%r model=%r | %s", company, model, exc)
        return UsedBikeResponse(offers=[], info="")
    finally:
        session.close()
