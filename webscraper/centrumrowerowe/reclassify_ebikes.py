"""TODO-047: give every 'Electric' bike its type from the shop's product category, no AI.

'Electric' / 'Electric cargo' named no type ("Rower elektryczny HAIBIKE Trekking 5"), so the
type is read from the product page: JSON-LD Product.category ("Rowery > Elektryczne >
Trekkingowe") -> app.bike_categories.category_from_shop_path (Trekkingowe / SUV -> Touring,
MTB -> MTB, Miejskie / Crossowe / Cargo -> City/Cross/Hybrid, Szosowe i gravelowe -> Gravel,
Młodzieżowe -> Kids). Candidates: bikes whose category is 'Electric' / 'Electric cargo', and
NULL-category bikes whose discovery bike_type is 'elektryczny' / 'elektryczny cargo'. Each
bike's listings are tried newest first (URL allowlist and redirects as in process_queue); the
first page that names a type wins; 'elektryczny cargo' without one -> City/Cross/Hybrid.
A write only lands while the category is still the one read (never overwrites a value set
meanwhile). The e-bike stays recognisable as electric by its 'Electric / Powertrain' components.

    python reclassify_ebikes.py --dry-run          # fetch + print, write nothing
    python reclassify_ebikes.py --delay 0.5
    python reclassify_ebikes.py --allow-remote     # a non-local database, e.g. Cloud SQL via the proxy

Run BEFORE backend/scripts/migrate_bike_category_codes.py, which refuses leftover 'Electric'
rows. Idempotent: a second run finds nothing to do. Exit code 0 (unresolved bikes are listed).
"""
import argparse
import logging
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402  (puts backend/ on sys.path, loads backend/.env)
from db import SOURCE, BikeDiscovery, models, norm, session  # noqa: E402
from app.bike_categories import ELECTRIC_LEGACY, category_from_discovery, category_from_shop_path  # noqa: E402
from bike_store import tx  # noqa: E402
from discovery_repo import listings_newest_first  # noqa: E402
from process_queue import Fetch, check_url, http_fetch  # noqa: E402
from product_parser import shop_category  # noqa: E402

logger = logging.getLogger("reclassify_ebikes")

E_TYPES = ("elektryczny", "elektryczny cargo")
UNRESOLVED, CHANGED = "unresolved", "changed meanwhile"


def candidates(limit: Optional[int] = None) -> list[dict]:
    """Bikes to reclassify: id, name, current category and their listings (newest first)."""
    out = []
    with session() as s:
        discovery = {d.bike_id: d for d in s.query(BikeDiscovery).filter(BikeDiscovery.bike_id.isnot(None))
                     .order_by(BikeDiscovery.id)}
        bikes = (s.query(models.Bike)
                 .filter(models.Bike.category.in_(ELECTRIC_LEGACY) | models.Bike.category.is_(None))
                 .order_by(models.Bike.id))
        for bike in bikes:
            d = discovery.get(bike.id)
            if bike.category is None and (d is None or norm(d.bike_type) not in E_TYPES):
                continue
            listings = [(li.source, li.source_product_id, li.details_link)
                        for li in listings_newest_first(s, d.id)] if d is not None else []
            out.append({"id": bike.id, "name": f"{bike.brand} {bike.model}", "category": bike.category,
                        "bike_type": d.bike_type if d is not None else None, "listings": listings})
            if limit and len(out) >= limit:
                break
    return out


def resolve(bike: dict, fetch: Fetch, delay: float) -> tuple[Optional[str], str]:
    """(category, how it was found) — the first listing page that names a type wins."""
    notes = []
    for i, (source, pid, url) in enumerate(bike["listings"]):
        if source != SOURCE or not url:
            notes.append(f"{pid}: not a {SOURCE} page")
            continue
        if i:
            time.sleep(delay)
        try:
            status, html = fetch(check_url(url))
        except Exception as exc:  # noqa: BLE001 — recorded, the next listing is tried
            notes.append(f"{pid}: {type(exc).__name__}: {exc}")
            continue
        if status != 200:
            notes.append(f"{pid}: HTTP {status}")
            continue
        path = shop_category(html)
        if (category := category_from_shop_path(path)) is not None:
            return category, f"{pid}: {path}"
        notes.append(f"{pid}: no type in {path!r}")
    # "Electric cargo" / "elektryczny cargo" is a cargo bike even without a page.
    fallback = category_from_discovery(bike["bike_type"]) or (
        "City/Cross/Hybrid" if bike["category"] == "Electric cargo" else None)
    if fallback is not None:
        return fallback, f"bike_type {bike['bike_type']!r}" if bike["bike_type"] else "Electric cargo"
    return None, "; ".join(notes) or "no listings"


def write(bike_id: int, old: Optional[str], new: str) -> bool:
    """category old -> new, only while it is still `old`; True when the row was updated."""
    with tx() as s:
        q = s.query(models.Bike).filter(models.Bike.id == bike_id)
        q = q.filter(models.Bike.category.is_(None)) if old is None else q.filter(models.Bike.category == old)
        return q.update({models.Bike.category: new}, synchronize_session=False) == 1


def run(limit: Optional[int], delay: float, dry_run: bool, fetch: Fetch = http_fetch) -> Counter:
    counts: Counter = Counter()
    bikes = candidates(limit)
    print(f"{len(bikes)} bikes to reclassify")
    for n, bike in enumerate(bikes):
        if n:
            time.sleep(delay)
        category, how = resolve(bike, fetch, delay)
        if category is None:
            counts[UNRESOLVED] += 1
            print(f"{bike['id']} {bike['name']}: UNRESOLVED ({how})")
            continue
        if not dry_run and not write(bike["id"], bike["category"], category):
            counts[CHANGED] += 1
            print(f"{bike['id']} {bike['name']}: category changed meanwhile — left alone")
            continue
        counts[category] += 1
        print(f"{bike['id']} {bike['name']}: {bike['category']} -> {category} ({how})")
    return counts


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=None, help="at most N bikes (default: all)")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between page fetches (default 0.5)")
    ap.add_argument("--dry-run", action="store_true", help="fetch + print; write nothing")
    ap.add_argument("--allow-remote", action="store_true", help="allow writing to a non-local database")
    args = ap.parse_args(argv)
    if (args.limit is not None and args.limit < 1) or args.delay < 0:
        ap.error("--limit must be >= 1 and --delay >= 0")
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # A dry run writes nothing, so it only prints the target instead of refusing a remote one.
    logger.info("database: %s", db.check_target(allow_remote=args.allow_remote or args.dry_run))
    counts = run(args.limit, args.delay, args.dry_run)
    summary = " ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"{'dry run (nothing written): ' if args.dry_run else ''}{summary or 'nothing to do'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
