"""Stored marketplace offers — the read side of bike_offer / bike_offer_photos (TODO-031/032).

Every row here is written by the separate searcher service
(searcher/app/repository.py): OLX listings (source 'olx.pl', TODO-031) are
read for POST /v1/bike/used and Decathlon offers (source 'decathlon.pl',
TODO-032) for POST /v1/bike/decathlon. No TTL — while rows exist the
frontend's "Request data" button stays hidden, so nothing re-triggers the
search. Lives next to repository.py rather than in it to keep that file from
growing further past the 500-line limit.
"""
import logging

from .models import (
    Bike,
    BikeOffer as BikeOfferRow,  # aliased: schemas.BikeOffer is the response shape
    BikeOfferPhoto as BikeOfferPhotoRow,
    get_session,
)
from .repository import _find_bike_id
from .schemas import BikeOffer, BikeOfferResponse, UsedBikeResponse

logger = logging.getLogger(__name__)

OLX_SOURCE = "olx.pl"
DECATHLON_SOURCE = "decathlon.pl"


def bike_exists(company: str, model: str) -> bool:
    """Whether the bike identity is known (Python-normalised brand/model compare).

    /v1/bike/used/search and /v1/bike/decathlon/search check this before
    spending a searcher run: the searcher creates missing bikes for direct
    calls, and letting anonymous web traffic mint arbitrary `bike` rows would
    pollute the DB-first search.
    """
    session = get_session()
    try:
        return _find_bike_id(session, company, model) is not None
    finally:
        session.close()


def _get_stored_offers(company: str, model: str, source: str) -> list[BikeOffer]:
    """Stored offers of one bike from one marketplace — a pure DB read, no AI, no generic cache.

    Rows come from bike_offer (the given `source`) in id order, each with its
    bike_offer_photos ordered by display_order; `is_new` is the row's.
    brand/model on every offer are the bike row's (the single source of
    display casing). An unknown bike, no rows, or a DB error all yield an
    empty list — the details view must keep rendering whatever happens here.
    """
    session = get_session()
    try:
        bike_id = _find_bike_id(session, company, model)
        if bike_id is None:
            logger.info("stored offers: bike not found | source=%s company=%r model=%r", source, company, model)
            return []
        bike = session.get(Bike, bike_id)
        rows = (
            session.query(BikeOfferRow)
            .filter(BikeOfferRow.bike_id == bike_id, BikeOfferRow.source == source)
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
                is_new=bool(row.is_new),
                url=row.url,
                photos=photos_by_offer.get(row.id, []),
                source=row.source,
                city=row.city,
            )
            for row in rows
        ]
        logger.info(
            "stored offers served from DB | source=%s company=%r model=%r bike_id=%d offers=%d",
            source, company, model, bike_id, len(offers),
        )
        return offers
    except Exception as exc:  # noqa: BLE001 — a DB read must never break the details view
        logger.error("stored offers read failed | source=%s company=%r model=%r | %s", source, company, model, exc)
        return []
    finally:
        session.close()


def get_used_offers(company: str, model: str) -> UsedBikeResponse:
    """Stored OLX listings of one bike (source 'olx.pl') — see _get_stored_offers."""
    return UsedBikeResponse(offers=_get_stored_offers(company, model, OLX_SOURCE), info="")


def get_decathlon_offers(company: str, model: str) -> BikeOfferResponse:
    """Stored decathlon.pl offers of one bike (source 'decathlon.pl') — see _get_stored_offers."""
    return BikeOfferResponse(offers=_get_stored_offers(company, model, DECATHLON_SOURCE), info="")
