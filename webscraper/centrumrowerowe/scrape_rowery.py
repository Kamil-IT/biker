"""Scrape the centrumrowerowe.pl bike listing into the `bike_discovery` queue (TODO-035, TODO-039).

Each product becomes a `bike_discovery_listing` row linked to its bike in `bike_discovery`
(found by normalised company + model, inserted as `pending` when new).

    python scrape_rowery.py                 # upsert into the DB the backend is configured for
    python scrape_rowery.py --dry-run       # counts only, no DB
    python scrape_rowery.py --csv           # also write rowery.csv (one row per listing entry)
    python scrape_rowery.py --max-pages 2   # stop early (testing)
    python scrape_rowery.py --allow-remote  # permit a non-local database (e.g. the Cloud SQL proxy)
"""
import argparse
import csv
import json
import re
import time
import urllib.request
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit, urlunsplit

BASE = "https://www.centrumrowerowe.pl/rowery/"
UA = {"User-Agent": "Mozilla/5.0"}
LD = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
PRODUCT_ID = re.compile(r"-(pd\d+)(?:/|$)")
ALLOWED_HOSTS = ("www.centrumrowerowe.pl", "centrumrowerowe.pl")
# Column sizes of bike_discovery (company, model, bike_type) and bike_discovery_listing (the rest).
LIMITS = {"raw_name": 512, "company": 255, "model": 255, "bike_type": 64, "price": 100, "details_link": 2048}

# Listing columns a re-scrape refreshes. The listing's bike and first_seen_at, and everything on
# the bike row (status, attempts, bike_id, company, model, bike_type) are never touched.
UPDATABLE = ("raw_name", "details_link", "price", "last_seen_at", "updated_at")


class UpsertCounts(NamedTuple):
    bikes_inserted: int
    listings_inserted: int
    listings_updated: int


def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read().decode("utf-8")


def _nodes(html):
    """Every JSON-LD object on the page; lists and @graph are flattened, malformed blocks skipped."""
    for block in LD.findall(html):
        try:
            stack = [json.loads(block)]
        except json.JSONDecodeError:
            continue
        while stack:
            node = stack.pop(0)
            if isinstance(node, list):
                stack = list(node) + stack
            elif isinstance(node, dict):
                yield node
                if isinstance(node.get("@graph"), list):
                    stack = list(node["@graph"]) + stack


def products(html):
    """Listing entries {name, price, url} of one page; anything malformed is skipped."""
    for node in _nodes(html):
        if node.get("@type") != "ItemList" or not isinstance(node.get("itemListElement"), list):
            continue
        for el in node["itemListElement"]:
            it = el.get("item") if isinstance(el, dict) else None
            if not isinstance(it, dict) or not it.get("url") or not it.get("name"):
                continue
            offers = it.get("offers")
            price = offers.get("price") if isinstance(offers, dict) else None
            yield {"name": str(it["name"]), "price": price, "url": str(it["url"])}


def fetch_page(url):
    """Download once, retry once; None (with a warning) when both attempts fail."""
    for attempt in (1, 2):
        try:
            return fetch(url)
        except Exception as exc:
            print(f"WARNING: {url} attempt {attempt} failed: {exc}", flush=True)
            time.sleep(1)
    return None


def collect(max_pages=None, delay=0.5):
    """All listing rows (one per colour/size variant), following ?page=N."""
    first = fetch_page(BASE)
    if first is None:
        raise SystemExit("Cannot download the first listing page - nothing to do")
    pages = [int(n) for n in re.findall(r"\?page=(\d+)", first)]
    last = max(pages) if pages else 1
    if max_pages:
        last = min(last, max_pages)
    rows = list(products(first))
    for p in range(2, last + 1):
        html = fetch_page(f"{BASE}?page={p}")
        if html is None:
            print(f"WARNING: page {p}/{last} skipped", flush=True)
            continue
        rows += products(html)
        print(f"page {p}/{last}: {len(rows)}", flush=True)
        time.sleep(delay)
    return rows


def _price_value(price):
    try:
        return float(str(price).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        return None


def clean_url(url):
    """Product URL without the ?v_Id= (variant) query."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def product_id(url):
    """`pd...` id of a product URL; None unless it is https on the shop's host with such an id."""
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "") not in ALLOWED_HOSTS:
        return None
    m = PRODUCT_ID.search(parts.path)
    return m.group(1) if m else None


def _fit(value, column):
    return value[:LIMITS[column]] if value else value


def group_products(rows, stats=None):
    """Collapse listing rows to one dict per `pd...` id: name, details_link, lowest price, variant ids.

    Rows off the shop's host, without an id or with a too long link are dropped and counted in
    stats["skipped"] (when a dict is passed).
    """
    import name_split

    stats = stats if stats is not None else {}
    stats.setdefault("skipped", 0)
    grouped = {}
    for row in rows:
        pid = product_id(row["url"])
        if pid is None or len(clean_url(row["url"])) > LIMITS["details_link"]:
            stats["skipped"] += 1
            continue
        entry = grouped.get(pid)
        if entry is None:
            parts = name_split.split_name(row["name"])
            entry = grouped[pid] = {
                "source_product_id": pid,
                "raw_name": _fit(row["name"].strip(), "raw_name"),
                "company": _fit(parts.company, "company"),
                "model": _fit(parts.model, "model"),
                "bike_type": _fit(parts.bike_type, "bike_type"),
                "details_link": clean_url(row["url"]),
                "price": None,
                "variant_ids": [],
            }
        variant = parse_qs(urlsplit(row["url"]).query).get("v_Id")
        if variant and variant[0] not in entry["variant_ids"]:
            entry["variant_ids"].append(variant[0])
        value = _price_value(row.get("price"))
        best = _price_value(entry["price"])
        if value is not None and (best is None or value < best):
            entry["price"] = _fit(str(row["price"]).strip(), "price")
    return list(grouped.values())


def upsert(items, source=None):
    """Upsert one listing per product and link it to its bike; one transaction.

    A known listing (source, source_product_id) only gets UPDATABLE refreshed and stays on its
    bike. A new one is linked to the bike with the same normalised company + model, which is
    inserted as `pending` when there is none. Returns UpsertCounts.
    """
    import db
    import discovery_repo

    source = source or db.SOURCE
    db.ensure_table()
    now = db.utcnow()
    bikes_inserted = listings_inserted = listings_updated = 0
    with db.session() as s:
        listings = {row.source_product_id: row for row in s.query(db.BikeDiscoveryListing).filter_by(source=source)}
        bikes = discovery_repo.bike_ids_by_identity(s)
        for item in items:
            values = {
                "raw_name": _fit(item["raw_name"], "raw_name"),
                "details_link": _fit(item["details_link"], "details_link"),
                "price": _fit(item["price"], "price"),
                "last_seen_at": now,
                "updated_at": now,
            }
            listing = listings.get(item["source_product_id"])
            if listing is not None:
                for column in UPDATABLE:
                    setattr(listing, column, values[column])
                listings_updated += 1
                continue
            company, model = _fit(item["company"], "company"), _fit(item["model"], "model")
            key = (db.norm(company), db.norm(model))
            if key not in bikes:
                bike = db.BikeDiscovery(company=company, model=model,
                                        bike_type=_fit(item["bike_type"], "bike_type") or None,
                                        status=db.PENDING, attempts=0, created_at=now, updated_at=now)
                s.add(bike)
                s.flush()
                bikes[key] = bike.id
                bikes_inserted += 1
            listing = db.BikeDiscoveryListing(discovery_id=bikes[key], source=source,
                                              source_product_id=item["source_product_id"],
                                              first_seen_at=now, **values)
            s.add(listing)
            listings[item["source_product_id"]] = listing
            listings_inserted += 1
        s.commit()
    return UpsertCounts(bikes_inserted, listings_inserted, listings_updated)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", action="store_true", help="also write rowery.csv")
    ap.add_argument("--dry-run", action="store_true", help="print counts only, write nothing to the DB")
    ap.add_argument("--allow-remote", action="store_true", help="allow writing to a non-local database")
    ap.add_argument("--max-pages", type=int, default=None, help="stop after N listing pages")
    args = ap.parse_args()

    rows = collect(args.max_pages)
    if args.csv:
        with open("rowery.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["name", "price", "url"], delimiter=";")
            w.writeheader()
            w.writerows(rows)
    stats = {}
    items = group_products(rows, stats)
    print(f"listing rows: {len(rows)}, products seen: {len(items)}, skipped (bad url): {stats['skipped']}")
    if args.dry_run:
        print("dry run: nothing written")
        return
    import db
    print(f"target database: {db.check_target(args.allow_remote)}")
    counts = upsert(items)
    print(f"products seen: {len(items)}, bikes inserted: {counts.bikes_inserted}, "
          f"listings inserted: {counts.listings_inserted}, listings updated: {counts.listings_updated}")


if __name__ == "__main__":
    main()
