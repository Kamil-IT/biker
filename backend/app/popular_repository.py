"""Popular bikes — the read side of bike_popular (TODO-034).

The home page shows a hand-curated list of bikes before the first search.
`bike_popular` holds one row per listed bike (FK → bike, ordered by
`position`); only scripts/seed_popular_bikes.py writes it, this module reads
it for GET /v1/bike/popular. Each entry carries the bike's display casing and
the first two sentences of its stored details description — the card shows
those under the expert rating, which the frontend fetches separately through
POST /v1/bike/review. Pure DB read: no AI call, no generic cache, no TTL.
Lives next to offers_repository.py rather than in repository.py to keep that
file under the 500-line limit.
"""
import logging
import re

from .models import Bike, BikePopular, get_session
from .schemas import BikeDescription, PopularBike, PopularBikesResponse

logger = logging.getLogger(__name__)

BLURB_SENTENCES = 2  # how much of the description a home-page card shows

# A sentence ends with . ! ? or … (plus an optional closing quote / bracket)
# followed by whitespace. The lookahead captures the first character of the
# next word, past any opening quote / bracket, so the caller can insist it is
# upper-case — the one cheap guard against splitting on an abbreviation.
_SENTENCE_BOUNDARY = re.compile(r"(?P<end>[.!?…][”\"')»]?)\s+(?=[„“\"'(«]?(?P<next>\S))")


def first_sentences(text: str, n: int = BLURB_SENTENCES) -> str:
    """The first `n` sentences of `text` (whitespace collapsed), or all of it when it has fewer.

    A boundary is sentence-ending punctuation followed by whitespace and an
    upper-case word, so a lower-case or numeric continuation ("ok. 12 kg",
    "tzw. gravel", "np. 29-calowe") does not end a sentence. Deliberately no
    abbreviation dictionary: a rare over- or under-cut on a card blurb is
    harmless, and the details view shows the full description anyway.
    """
    text = " ".join(text.split())
    if n <= 0 or not text:
        return ""
    seen = 0
    for m in _SENTENCE_BOUNDARY.finditer(text):
        if not m.group("next").isupper():
            continue
        seen += 1
        if seen == n:
            return text[: m.end("end")]
    return text


def _blurb(brand: str, model: str, raw: str | None) -> str:
    """First sentences of a stored BikeDescription JSON; "" when there is none or it does not parse."""
    if not raw:
        return ""
    try:
        text = BikeDescription.model_validate_json(raw).text
    except ValueError as exc:  # pydantic's ValidationError — one bad blob must not drop the whole list
        logger.warning("popular bikes: unparseable description | brand=%r model=%r | %s", brand, model, exc)
        return ""
    return first_sentences(text)


def get_popular_bikes() -> PopularBikesResponse:
    """The curated home-page bikes in position order — a pure DB read, no AI, no generic cache.

    One query: bike_popular joined to bike (brand/model as stored — the single
    source of display casing) whose stored
    BikeDescription JSON (`bike.description`) supplies the blurb; a bike without details gets "".
    Ordered by position, then id. An empty table or a DB error both yield an
    empty list — the home page must keep rendering whatever happens here.
    """
    session = get_session()
    try:
        rows = (
            session.query(Bike.id, Bike.brand, Bike.model, Bike.description)
            .select_from(BikePopular)
            .join(Bike, Bike.id == BikePopular.bike_id)
            .order_by(BikePopular.position, BikePopular.id)
            .all()
        )
        bikes = [
            PopularBike(id=bike_id, brand=brand, model=model, description=_blurb(brand, model, description))
            for bike_id, brand, model, description in rows
        ]
        logger.info("popular bikes served from DB | bikes=%d", len(bikes))
        return PopularBikesResponse(bikes=bikes)
    except Exception as exc:  # noqa: BLE001 — a DB read must never break the home page
        logger.error("popular bikes read failed | %s", exc)
        return PopularBikesResponse(bikes=[])
    finally:
        session.close()
