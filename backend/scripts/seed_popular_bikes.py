"""Seed the home page's "popular bikes" list — the `bike_popular` table (TODO-034).

`GET /v1/bike/popular` serves whatever this script puts into `bike_popular`; the
app never writes that table. The database is the one DATABASE_URL in backend/.env
selects (unset -> SQLite cache.db), exactly as for the server.

    python scripts/seed_popular_bikes.py --dry-run        # show the automatic picks, change nothing
    python scripts/seed_popular_bikes.py                  # replace bike_popular with the 3 best candidates
    python scripts/seed_popular_bikes.py --count 5
    python scripts/seed_popular_bikes.py --bike "Giant|Revolt Advanced Pro" --bike "Trek|Madone SL 6"
    python scripts/seed_popular_bikes.py --db ../cache.db # another database: SQLite path or SQLAlchemy URL

Automatic pick (default): a bike qualifies when its details (`bike.description`) are set and it has >= 1
photo and >= 20 component rows AND its stored review (`bike_review`, TODO-037)
has a `rating` > 0 — reviews from before the aggregate rating existed do not
qualify. Candidates rank by
marketplace offers desc, photos desc, component rows desc, then bike id; the list
takes at most one bike per brand while enough candidates remain and only then
fills up with repeats, so the top of the home page shows different brands.

`--bike "Brand|Model"` (repeatable) lists exactly those bikes instead, in the
given order; brand and model are compared after strip().lower() in Python. An
unknown bike aborts before anything is written; a pick that fails the quality
rules is accepted with a warning naming what it lacks.

Without --dry-run the table is REPLACED in one transaction (every row deleted,
the picks inserted at positions 1..n), so re-running is idempotent. Everything
goes through the SQLAlchemy ORM / Core with the JSON parsed in Python, so it
works on SQLite and PostgreSQL alike.

Exit code: 0 on success; 1 when fewer than --count candidates qualify (the
shortfall is printed, nothing is written), a --bike is unknown or repeated, or
the write fails (the table is then left as it was).
"""
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")  # DATABASE_URL selects the database, as for the server

from app.models import (  # noqa: E402
    Bike, BikeComponent, BikeDetailPhoto, BikeOffer, BikePopular, BikeReview,
    configure_db, get_engine, get_session, init_db,
)

MIN_PHOTOS = 1
MIN_COMPONENTS = 20
DESCRIPTION_CHARS = 60
DEFAULT_COUNT = 3


@dataclass
class Candidate:
    """One `bike` row with everything the ranking and the printout need."""

    bike_id: int
    brand: str
    model: str
    rating: float
    photos: int
    components: int
    offers: int
    description: str

    @property
    def qualifies(self) -> bool:
        return self.photos >= MIN_PHOTOS and self.components >= MIN_COMPONENTS and self.rating > 0

    @property
    def rank_key(self) -> tuple:
        return (-self.offers, -self.photos, -self.components, self.bike_id)

    @property
    def brand_key(self) -> str:
        return self.brand.strip().lower()

    def shortcomings(self) -> list[str]:
        out = []
        if self.photos < MIN_PHOTOS:
            out.append("no photos")
        if self.components < MIN_COMPONENTS:
            out.append(f"only {self.components} component rows (< {MIN_COMPONENTS})")
        if self.rating <= 0:
            out.append("no stored review with a rating > 0")
        return out


# --- reading -------------------------------------------------------------


def _description_text(raw: str) -> str:
    """The `text` of a stored BikeDescription JSON blob; "" when unreadable."""
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    text = data.get("text", "") if isinstance(data, dict) else ""
    return text if isinstance(text, str) else ""


def load_ratings(session) -> dict[int, float]:
    """bike_id -> stored review rating (`bike_review`); a bike without a review is absent."""
    return {bike_id: float(rating or 0) for bike_id, rating in session.execute(
        select(BikeReview.bike_id, BikeReview.rating)
    )}


def _count_per_bike(session, child, fk_column) -> dict[int, int]:
    """bike_id -> number of `child` rows hanging off that bike."""
    stmt = select(fk_column, func.count(child.id)).group_by(fk_column)
    return {bike_id: n for bike_id, n in session.execute(stmt)}


def load_candidates(session) -> list[Candidate]:
    """Every `bike` row with its counts, rating and description — a handful of aggregate queries."""
    # Photos are keyed on the bike itself (migrate_photos_bike_id.py), not on its details row.
    photos = dict(session.execute(
        select(BikeDetailPhoto.bike_id, func.count(BikeDetailPhoto.id)).group_by(BikeDetailPhoto.bike_id)
    ).all())
    components = _count_per_bike(session, BikeComponent, BikeComponent.bike_id)
    offers = dict(session.execute(
        select(BikeOffer.bike_id, func.count(BikeOffer.id)).group_by(BikeOffer.bike_id)
    ).all())
    descriptions = {
        bike_id: _description_text(raw)
        for bike_id, raw in session.execute(select(Bike.id, Bike.description).where(Bike.description.isnot(None)))
    }
    ratings = load_ratings(session)
    candidates = []
    for bike_id, brand, model in session.execute(select(Bike.id, Bike.brand, Bike.model)):
        candidates.append(Candidate(
            bike_id=bike_id, brand=brand, model=model,
            rating=ratings.get(bike_id, 0.0),
            photos=photos.get(bike_id, 0), components=components.get(bike_id, 0),
            offers=offers.get(bike_id, 0), description=descriptions.get(bike_id, ""),
        ))
    return candidates


# --- picking -------------------------------------------------------------


def pick_automatic(candidates: list[Candidate], count: int) -> list[Candidate]:
    """The `count` best qualifying bikes: one per brand first, repeats only to fill up."""
    ranked = sorted((c for c in candidates if c.qualifies), key=lambda c: c.rank_key)
    picks: list[Candidate] = []
    brands: set[str] = set()
    for c in ranked:  # first pass: at most one bike per brand
        if len(picks) == count:
            break
        if c.brand_key not in brands:
            picks.append(c)
            brands.add(c.brand_key)
    chosen = {c.bike_id for c in picks}
    for c in ranked:  # second pass: fill the rest in rank order
        if len(picks) == count:
            break
        if c.bike_id not in chosen:
            picks.append(c)
            chosen.add(c.bike_id)
    return picks


def pick_explicit(candidates: list[Candidate], specs: list[str]) -> list[Candidate]:
    """The bikes named as "Brand|Model", in that order. Exits 1 on an unknown or repeated bike."""
    by_key: dict[tuple[str, str], list[Candidate]] = {}
    for c in candidates:
        by_key.setdefault((c.brand_key, c.model.strip().lower()), []).append(c)
    picks: list[Candidate] = []
    for spec in specs:
        brand, sep, model = spec.partition("|")
        brand, model = brand.strip(), model.strip()
        if not sep or not brand or not model:
            sys.exit(f'error: --bike expects "Brand|Model", got {spec!r}')
        matches = sorted(by_key.get((brand.lower(), model.lower()), []), key=lambda c: c.rank_key)
        if not matches:
            sys.exit(f"error: bike not found in `bike`: {brand} / {model} — nothing written")
        chosen = matches[0]
        if len(matches) > 1:
            print(f"  note: {len(matches)} bike rows match {spec!r} (different casing) — "
                  f"using id {chosen.bike_id} ({chosen.brand} / {chosen.model})")
        if any(p.bike_id == chosen.bike_id for p in picks):
            sys.exit(f"error: --bike {spec!r} names a bike already listed — a bike is listed at most once")
        for problem in chosen.shortcomings():
            print(f"  warning: {chosen.brand} / {chosen.model}: {problem}")
        picks.append(chosen)
    return picks


# --- writing -------------------------------------------------------------


def replace_table(picks: list[Candidate]) -> None:
    """Delete every bike_popular row and insert the picks at positions 1..n — one transaction."""
    with get_session() as session, session.begin():
        session.execute(delete(BikePopular))
        session.add_all(BikePopular(bike_id=c.bike_id, position=pos) for pos, c in enumerate(picks, 1))


def read_back(by_id: dict[int, Candidate]) -> list[Candidate]:
    """The rows now in bike_popular, in the order the endpoint serves them."""
    with get_session() as session:
        ids = session.execute(
            select(BikePopular.bike_id).order_by(BikePopular.position, BikePopular.id)
        ).scalars().all()
    return [by_id[bike_id] for bike_id in ids]


# --- output --------------------------------------------------------------


def print_table(title: str, rows: list[Candidate]) -> None:
    print(title)
    if not rows:
        print("  (no rows)")
        return
    print(f"  {'pos':>3}  {'brand':<20} {'model':<28} {'rating':>6} {'photos':>6} {'comps':>5} {'offers':>6}  description")
    for pos, c in enumerate(rows, 1):
        rating = f"{c.rating:.1f}" if c.rating > 0 else "-"
        desc = " ".join(c.description.split())[:DESCRIPTION_CHARS]
        print(f"  {pos:>3}  {c.brand[:20]:<20} {c.model[:28]:<28} {rating:>6} "
              f"{c.photos:>6} {c.components:>5} {c.offers:>6}  {desc}")


def positive_int(value: str) -> int:
    n = int(value)
    if n < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return n


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed bike_popular, the home page's popular-bikes list.")
    p.add_argument("--count", type=positive_int, default=DEFAULT_COUNT,
                   help=f"how many bikes to list automatically (default {DEFAULT_COUNT}; ignored with --bike)")
    p.add_argument("--bike", action="append", default=[], metavar='"Brand|Model"',
                   help="list exactly this bike (repeatable; the order of the flags is the order shown)")
    p.add_argument("--dry-run", action="store_true", help="print the picks and change nothing")
    p.add_argument("--db", default=None, metavar="URL_OR_PATH",
                   help="database to seed instead of DATABASE_URL: a SQLAlchemy URL or a SQLite file path")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if args.db:
        configure_db(args.db)
    init_db()  # creates bike_popular / bike_review on a database that predates TODO-034 / TODO-037
    print(f"database: {get_engine().url.render_as_string(hide_password=True)}")

    with get_session() as session:
        candidates = load_candidates(session)
    qualifying = sum(1 for c in candidates if c.qualifies)
    print(f"bikes: {len(candidates)} in `bike`, {qualifying} qualify "
          f"(>= {MIN_PHOTOS} photo, >= {MIN_COMPONENTS} component rows, stored review with rating > 0)")

    if args.bike:
        picks, wanted = pick_explicit(candidates, args.bike), len(args.bike)
    else:
        picks, wanted = pick_automatic(candidates, args.count), args.count
    print_table("picks:", picks)
    if len(picks) < wanted:
        print(f"error: only {len(picks)} of {wanted} bikes qualify — nothing written; "
              f"lower --count or name bikes with --bike")
        return 1
    if args.dry_run:
        print("dry run — bike_popular unchanged")
        return 0

    try:
        replace_table(picks)
        rows = read_back({c.bike_id: c for c in candidates})
    except SQLAlchemyError as exc:
        print(f"error: write failed — bike_popular unchanged: {exc}")
        return 1
    print_table(f"bike_popular now ({len(rows)} rows):", rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
