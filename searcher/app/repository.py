"""Persistence of search results into the shared bike_offer tables (TODO-031, TODO-032, TODO-033).

Writes exactly what the backend's offers_repository reads back: bike_offer
rows under the bike's id tagged with the marketplace `source` ('olx.pl' for
/v1/search/olx, 'decathlon.pl' for /v1/search/decathlon, 'allegro.pl' for
/v1/search/allegro), each photo a bike_offer_photos row ordered by
display_order. Every write is scoped to one (bike, source) pair, so the three
searches never touch each other's rows — even when two of them run at once
for the same bike (the UI fires Decathlon + Allegro together).

Bike photos (/v1/search/photos) go into bike_detail_photos keyed on bike_id,
written once and never replaced: save_photos below.

Bike reviews (/v1/search/review, TODO-037) go into bike_review (one row per
bike) + bike_review_source (its `ref` URLs in order): save_review below. A
review is replaced only by a usable one.

Bike details (/v1/search/details, TODO-041) go into bike_detail (one row per
bike, updated in place) + bike_detail_component (the flattened tree): a port
of the backend's repository.save_bike_details / get_bike_details, plus the
new short_description column. get_stored_details / save_details below.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.exc import IntegrityError

from .models import (
    Bike,
    BikeOffer as BikeOfferRow,  # aliased: schemas.BikeOffer is the response shape
    BikeOfferPhoto as BikeOfferPhotoRow,
    BikeDetailPhoto,
    BikeReview as BikeReviewRow,  # aliased: schemas.BikeReview is the response shape
    BikeReviewSource,
    BikeDetailComponent,
    BikeDetails as BikeDetailsRow,  # aliased: schemas.BikeDetails is the response shape
    dialect_insert,
    get_session,
)
from .details_finder import has_components, is_usable_details
from .schemas import (
    BikeCategory,
    BikeDescription,
    BikeDetails,
    BikeOffer,
    BikeReview,
    BikeSubcategory,
    ComponentElement,
    SpecItem,
)

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
    for OLX listings, the shop page's answer for Decathlon, the listing's
    answer — default false — for Allegro).

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


def _photo_urls(session, bike_id: int) -> list[str]:
    return [
        r.url for r in session.query(BikeDetailPhoto.url)
        .filter(BikeDetailPhoto.bike_id == bike_id)
        .order_by(BikeDetailPhoto.display_order, BikeDetailPhoto.id)
    ]


def save_photos(company: str, model: str, photos: list[str]) -> tuple[Optional[int], list[str], int]:
    """Store `photos` for a bike that has none; returns (bike_id, the bike's photos now, rows written).

    Photos are never deleted or replaced: when the bike already has photo rows
    (another search for it finished first — a second process or instance) they
    are returned and nothing is written. The check and the insert run under a
    row lock on the bike (SELECT … FOR UPDATE; a no-op on SQLite, whose writers
    are serialised in one process by the caller's single-flight), so two
    concurrent searches for one bike cannot both insert. An empty `photos`
    writes nothing — not even a bike row. The bike row is otherwise created
    with the caller's casing when it is missing. Raises on a DB error after
    rolling back.
    """
    session = get_session()
    try:
        if not photos:
            bike_id = _find_bike_id(session, company, model)
            logger.warning("no photos to store — nothing written | company=%r model=%r", company, model)
            return bike_id, (_photo_urls(session, bike_id) if bike_id is not None else []), 0
        bike_id = _get_or_create_bike(session, company, model)
        session.query(Bike.id).filter(Bike.id == bike_id).with_for_update().one()
        existing = _photo_urls(session, bike_id)
        if existing:
            session.rollback()
            logger.info("photos already stored — kept, nothing written | bike_id=%d stored=%d", bike_id, len(existing))
            return bike_id, existing, 0
        for idx, url in enumerate(photos):
            session.add(BikeDetailPhoto(bike_id=bike_id, url=url, display_order=idx))
        session.commit()
        logger.info("photos stored | company=%r model=%r bike_id=%d saved=%d", company, model, bike_id, len(photos))
        return bike_id, list(photos), len(photos)
    except Exception as exc:
        session.rollback()
        logger.error("photos store failed | company=%r model=%r | %s", company, model, exc)
        raise
    finally:
        session.close()


def is_usable_review(review: BikeReview) -> bool:
    """Only a review with sources is worth storing — a degenerate rating-0 answer never is."""
    return bool(review.ref) and review.sources_used >= 1


def save_review(company: str, model: str, review: BikeReview) -> tuple[Optional[int], bool]:
    """Store `review` as the bike's review when it is usable; returns (bike_id, saved).

    Usable = non-empty `ref` and sources_used >= 1. Then, in one transaction:
    the bike row is created if missing (caller's casing), its bike_review row
    is upserted on bike_id (INSERT … ON CONFLICT (bike_id) DO UPDATE — score,
    explanation, rating, sources_used, updated_at replaced, created_at kept)
    and its bike_review_source rows are rewritten with display_order = the
    index in `ref`. An unusable review writes and deletes nothing — not even a
    bike row — so a bad run never wipes a stored review; (bike_id or None,
    False) comes back. Raises on a DB error after rolling back.
    """
    session = get_session()
    try:
        if not is_usable_review(review):
            bike_id = _find_bike_id(session, company, model)
            logger.warning(
                "no usable review to store — nothing written | company=%r model=%r ref=%d sources_used=%d",
                company, model, len(review.ref), review.sources_used,
            )
            return bike_id, False
        bike_id = _get_or_create_bike(session, company, model)
        now = datetime.now(timezone.utc)
        values = {
            "bike_id": bike_id, "score": review.score, "explanation": review.explanation,
            "rating": review.rating, "sources_used": review.sources_used,
            "created_at": now, "updated_at": now,
        }
        stmt = dialect_insert(BikeReviewRow).values(**values).on_conflict_do_update(
            index_elements=["bike_id"],
            set_={k: v for k, v in values.items() if k not in ("bike_id", "created_at")},
        )
        review_id = session.execute(stmt.returning(BikeReviewRow.id)).scalar_one()
        session.query(BikeReviewSource).filter_by(review_id=review_id).delete(synchronize_session=False)
        for idx, url in enumerate(review.ref):
            session.add(BikeReviewSource(review_id=review_id, url=url, display_order=idx))
        session.commit()
        logger.info(
            "review stored | company=%r model=%r bike_id=%d review_id=%d rating=%.1f sources=%d",
            company, model, bike_id, review_id, review.rating, len(review.ref),
        )
        return bike_id, True
    except Exception as exc:
        session.rollback()
        logger.error("review store failed | company=%r model=%r | %s", company, model, exc)
        raise
    finally:
        session.close()


def _rebuild_components(rows) -> list[BikeCategory]:
    """Regroup flat bike_detail_component rows (ordered by component/element/spec order) into the tree.

    Same grouping as the backend's repository.rebuild_components: by the order
    integers, not by names; a NULL spec_key is an element without specs.
    """
    comps: dict[int, dict] = {}
    for r in rows:
        comp = comps.setdefault(r.component_order, {"category": r.category, "subcategory": r.subcategory, "elements": {}})
        element = comp["elements"].setdefault(
            r.element_order, {"name": r.element_name, "description": r.element_description or "", "specs": []},
        )
        if r.spec_key is not None:
            element["specs"].append(SpecItem(key=r.spec_key, value=r.spec_value or ""))
    grouped: dict[str, list[BikeSubcategory]] = {}
    for comp_order in sorted(comps):
        comp = comps[comp_order]
        grouped.setdefault(comp["category"], []).append(BikeSubcategory(
            subcategory=comp["subcategory"],
            elements=[
                ComponentElement(name=el["name"], description=el["description"], specs=el["specs"])
                for _, el in sorted(comp["elements"].items())
            ],
        ))
    return [BikeCategory(category=name, subcategories=subs) for name, subs in grouped.items()]


def _stored_details(session, bike_id: int, company: str, model: str) -> Optional[BikeDetails]:
    row = session.query(BikeDetailsRow).filter(BikeDetailsRow.bike_id == bike_id).one_or_none()
    if row is None:
        return None
    try:
        description = BikeDescription.model_validate_json(row.description)
    except Exception as exc:  # noqa: BLE001 - an unreadable blob must not break the request
        logger.warning("stored details description unreadable | bike_id=%d | %s", bike_id, exc)
        description = BikeDescription()
    return BikeDetails(
        company=company, model=model, description=description,
        components=_rebuild_components(row.components), short_description=row.short_description or "",
    )


def get_stored_details(company: str, model: str) -> tuple[Optional[int], Optional[BikeDetails]]:
    """(bike_id, stored details in the caller's casing or None); (None, None) for an unknown bike. Never creates anything."""
    session = get_session()
    try:
        bike_id = _find_bike_id(session, company, model)
        if bike_id is None:
            return None, None
        return bike_id, _stored_details(session, bike_id, company, model)
    finally:
        session.close()


def _upgrade_casing(session, bike_id: int, company: str, model: str) -> None:
    """A stored brand/model equal to its own normalised form is a placeholder - the caller's real casing replaces it.

    Monotonic (lower-case never overwrites real casing) and skipped when
    another bike row already owns the upgraded (brand, model) pair.
    """
    bike = session.get(Bike, bike_id)
    brand, name = company.strip(), model.strip()
    new_brand = brand if bike.brand == _lc(bike.brand) and brand != bike.brand else bike.brand
    new_model = name if bike.model == _lc(bike.model) and name != bike.model else bike.model
    if (new_brand, new_model) == (bike.brand, bike.model):
        return
    clash = session.query(Bike.id).filter(Bike.brand == new_brand, Bike.model == new_model, Bike.id != bike_id).first()
    if clash is None:
        bike.brand, bike.model = new_brand, new_model


def save_details(company: str, model: str, details: BikeDetails) -> tuple[Optional[int], bool]:
    """Store `details` as the bike's details when usable; returns (bike_id, saved).

    Usable = a non-empty component tree or a non-empty description. Then, in
    one transaction: the bike row is created if missing (caller's casing; an
    existing placeholder casing is upgraded), its bike_detail row is updated
    IN PLACE (id stable; description JSON and short_description replaced) or
    inserted, and its bike_detail_component rows are replaced with the
    flattened tree (one row per spec, an element without specs gets one row
    with NULL spec_*; component_order counts subcategories across the tree).
    Photos hang off `bike` and are never touched. An unusable result writes and
    deletes nothing - not even a bike row - so a bad run never wipes stored
    details. Raises on a DB error after rolling back.
    """
    session = get_session()
    try:
        if not is_usable_details(details):
            bike_id = _find_bike_id(session, company, model)
            logger.warning("no usable details to store - nothing written | company=%r model=%r", company, model)
            return bike_id, False
        bike_id = _get_or_create_bike(session, company, model)
        _upgrade_casing(session, bike_id, company, model)
        now = datetime.now(timezone.utc)
        row = session.query(BikeDetailsRow).filter_by(bike_id=bike_id).first()
        has_desc = bool(details.description.text.strip())
        has_comps = has_components(details)
        if row is not None:
            # Only the half this run produced is replaced; the other half stays as stored.
            if has_desc:
                row.description = details.description.model_dump_json()
                row.short_description = details.short_description
            row.updated_at = now
            if has_comps:
                session.query(BikeDetailComponent).filter_by(bike_detail_id=row.id).delete(synchronize_session=False)
                session.expire(row, ["components"])
        else:
            row = BikeDetailsRow(
                bike_id=bike_id, description=details.description.model_dump_json(),
                short_description=details.short_description,
            )
            session.add(row)
        session.flush()

        comp_order = 0
        rows = 0
        for category in (details.components if has_comps else []):
            for subcategory in category.subcategories:
                for e_idx, element in enumerate(subcategory.elements):
                    base = dict(
                        bike_detail_id=row.id, category=category.category, subcategory=subcategory.subcategory,
                        component_order=comp_order, element_name=element.name,
                        element_description=element.description, element_order=e_idx,
                    )
                    if not element.specs:
                        session.add(BikeDetailComponent(**base, spec_key=None, spec_value=None, spec_order=None))
                        rows += 1
                        continue
                    for s_idx, spec in enumerate(element.specs):
                        session.add(BikeDetailComponent(**base, spec_key=spec.key, spec_value=spec.value, spec_order=s_idx))
                        rows += 1
                comp_order += 1
        session.commit()
        logger.info(
            "details stored | company=%r model=%r bike_id=%d detail_id=%d component_rows=%d",
            company, model, bike_id, row.id, rows,
        )
        return bike_id, True
    except Exception as exc:
        session.rollback()
        logger.error("details store failed | company=%r model=%r | %s", company, model, exc)
        raise
    finally:
        session.close()
