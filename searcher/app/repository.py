"""Persistence of search results into the shared bike_offer tables (TODO-031, TODO-032).

Writes exactly what the backend's offers_repository reads back: bike_offer
rows under the bike's id tagged with the marketplace `source` ('olx.pl' for
/v1/search/olx, 'decathlon.pl' for /v1/search/decathlon), each photo a
bike_offer_photos row ordered by display_order. Every write is scoped to one
(bike, source) pair, so the two searches never touch each other's rows.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError

from .models import (
    Bike,
    BikeOffer as BikeOfferRow,  # aliased: schemas.BikeOffer is the response shape
    BikeOfferPhoto as BikeOfferPhotoRow,
    dialect_insert,
    get_session,
)
from .schemas import BikeOffer

logger = logging.getLogger("searcher.repository")


def _lc(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def _find_bike_id(session, company: str, model: str) -> Optional[int]:
    """Identity lookup normalised in Python (`strip().lower()`), same as the backend.

    SQLite's lower() is ASCII-only, so the compare happens here rather than in
    SQL. Oldest row wins should a case-split duplicate identity exist.
    """
    brand, name = _lc(company), _lc(model)
    return next(
        (b.id for b in session.query(Bike.id, Bike.brand, Bike.model).order_by(Bike.id)
         if _lc(b.brand) == brand and _lc(b.model) == name),
        None,
    )


def _get_or_create_bike(session, company: str, model: str) -> int:
    """The bike's id, creating the row with the caller's casing when it is new.

    Unlike the backend, the searcher may be called for a bike nobody has
    searched yet (a direct curl), so it must be allowed to mint the identity.
    Committed on its own so a concurrent creator only costs a retry, not the
    offers transaction.
    """
    bike_id = _find_bike_id(session, company, model)
    if bike_id is not None:
        return bike_id
    bike = Bike(brand=company.strip(), model=model.strip())  # caller's casing, no padding
    session.add(bike)
    try:
        session.flush()
        bike_id = bike.id
        session.commit()
    except IntegrityError:
        # Another writer inserted the same (brand, model) between lookup and insert.
        session.rollback()
        bike_id = _find_bike_id(session, company, model)
        if bike_id is None:
            raise
        return bike_id
    logger.info("bike created | company=%r model=%r bike_id=%d", company, model, bike_id)
    return bike_id


def save_offers(
    company: str, model: str, offers: list[BikeOffer], source: str,
) -> tuple[int, list[BikeOffer]]:
    """Replace the bike's stored `source` offers with `offers`; returns (bike_id, saved offers).

    One transaction: every offer is upserted on its url (INSERT … ON CONFLICT
    (url) DO UPDATE, so a listing seen again keeps its id but gets today's
    price/is_new/city/created_at), its photos are rewritten in order, and
    finally every `source` row of this bike whose url is not in the new set is
    deleted together with its photos. `is_new` is each offer's own flag (false
    for OLX listings, the shop page's answer for Decathlon).

    Two guards keep the shared table sane: (1) `url` is globally UNIQUE and the
    prompt's cascade returns model-family listings, so a listing that already
    belongs to ANOTHER bike (or another source) is left where it is (the DO
    UPDATE is limited to this bike's rows of this source) and is not reported
    as saved — otherwise two sibling bikes would keep stealing it from each
    other; (2) a search that found nothing keeps the rows already stored — a
    marketplace hiccup must not wipe data that was paid for. Raises on a DB
    error after rolling back, so a failed search never half-writes; the caller
    decides the HTTP status.
    """
    session = get_session()
    try:
        bike_id = _get_or_create_bike(session, company, model)
        now = datetime.now(timezone.utc)
        kept_urls: set[str] = set()
        saved: list[BikeOffer] = []
        photo_count = 0

        for offer in offers:
            url = offer.url.strip()
            if not url or url in kept_urls:
                logger.warning("offer skipped (empty or duplicate url) | url=%r", url)
                continue
            values = {
                "bike_id": bike_id, "price": offer.price, "is_new": offer.is_new,
                "url": url, "source": source, "city": offer.city, "created_at": now,
            }
            stmt = dialect_insert(BikeOfferRow).values(**values).on_conflict_do_update(
                index_elements=["url"],
                set_={k: v for k, v in values.items() if k not in ("url", "bike_id")},
                where=(BikeOfferRow.bike_id == bike_id) & (BikeOfferRow.source == source),
            )
            offer_id = session.execute(stmt.returning(BikeOfferRow.id)).scalar_one_or_none()
            if offer_id is None:
                logger.warning("offer already stored under another bike/source — left there | url=%s", url)
                continue
            kept_urls.add(url)
            saved.append(offer)
            session.query(BikeOfferPhotoRow).filter_by(bike_offer_id=offer_id).delete(synchronize_session=False)
            for idx, photo_url in enumerate(offer.photos):
                session.add(BikeOfferPhotoRow(bike_offer_id=offer_id, url=photo_url, display_order=idx))
                photo_count += 1

        # Replace semantics: `source` rows of this bike that the new search no
        # longer lists go, photos first so this does not lean on FK cascades.
        # An empty result replaces nothing.
        stale_ids: list[int] = []
        if kept_urls:
            stale_ids = [
                r.id for r in session.query(BikeOfferRow.id).filter(
                    BikeOfferRow.bike_id == bike_id, BikeOfferRow.source == source,
                    BikeOfferRow.url.not_in(kept_urls),
                ).all()
            ]
        else:
            logger.warning(
                "no offers to store — existing rows kept | source=%r company=%r model=%r", source, company, model,
            )
        if stale_ids:
            session.query(BikeOfferPhotoRow).filter(
                BikeOfferPhotoRow.bike_offer_id.in_(stale_ids)
            ).delete(synchronize_session=False)
            session.query(BikeOfferRow).filter(BikeOfferRow.id.in_(stale_ids)).delete(synchronize_session=False)

        session.commit()
        logger.info(
            "offers stored | source=%r company=%r model=%r bike_id=%d saved=%d photos=%d stale_removed=%d",
            source, company, model, bike_id, len(saved), photo_count, len(stale_ids),
        )
        return bike_id, saved
    except Exception as exc:
        session.rollback()
        logger.error("offers store failed | source=%r company=%r model=%r | %s", source, company, model, exc)
        raise
    finally:
        session.close()
