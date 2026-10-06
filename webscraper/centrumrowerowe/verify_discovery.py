"""Verify that every discovered bike landed completely (read-only; exit 1 on any ERROR).

Per bike_discovery row:
- queue      - nothing left pending / in_progress; failed rows listed with last_error; done/skipped has a bike;
- bike       - description JSON with text, short_description, bike_component rows (WARN under 4 categories),
               photos, a bike_review row, a centrumrowerowe bike_offer per listing, bike.category (ERROR when
               NULL although the discovery bike_type maps to a category, WARN when the type is not mapped);
               a paid step recorded "empty" in enrich's attempts file turns its ERROR into a WARN;
- read path  - what the app serves: repository.get_bike_details, photos_repository.get_bike_photos and
               reviews_repository.get_review for the stored brand/model are non-empty;
- fetch      - a done row has a listing fetched without error;
- --recheck N - N random done bikes: the shop page is fetched and parsed again and compared with the DB
               (component rows and description when the details are still the shop's, photo count when
               the photos are the shop's).

Prints a summary and writes every finding to a CSV (default runs/verify_<timestamp>.csv).
"""
import argparse
import csv
import json
import logging
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from db import (BikeDiscovery, BikeDiscoveryListing, DONE, FAILED, IN_PROGRESS, PENDING, SKIPPED, SOURCE,
                check_target, models, repository, session)
from app import photos_repository, reviews_repository
from app.bike_categories import category_from_discovery
from app.component_tree import flatten_components
from app.schemas import BikeDescription
import process_queue
from enrich import DEFAULT_ATTEMPTS, since_arg

RUNS = Path(__file__).resolve().parent / "runs"


class Findings:
    def __init__(self):
        self.rows: list[tuple] = []

    def add(self, level: str, check: str, bike: str, detail: str = "") -> None:
        self.rows.append((level, check, bike, detail))

    def count(self, level: str) -> int:
        return sum(1 for r in self.rows if r[0] == level)


def _desc_text(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    try:
        return BikeDescription.model_validate_json(raw).text.strip()
    except Exception:
        return ""


def check_bike(d: BikeDiscovery, f: Findings, attempts: dict, read_path: bool) -> None:
    name = f"{d.company} {d.model} (discovery {d.id})"
    with session() as s:
        bike = s.get(models.Bike, d.bike_id)
        if bike is None:
            f.add("ERROR", "bike.exists", name, f"bike_id {d.bike_id} missing")
            return
        name = f"{bike.brand} {bike.model} (bike {bike.id})"
        empty = lambda step: attempts.get(f"{bike.id}:{step}", {}).get("result") == "empty"  # noqa: E731
        text = _desc_text(bike.description)
        if not text:
            f.add("WARN" if empty("details") else "ERROR", "bike.description", name,
                  "NULL" if text is None else "empty text")
        if not (bike.short_description or "").strip():
            f.add("ERROR", "bike.short_description", name, "empty")
        cats = {c for (c,) in s.query(models.BikeComponent.category).filter_by(bike_id=bike.id)}
        if not cats:
            f.add("WARN" if empty("details") else "ERROR", "bike.components", name, "no rows")
        elif len(cats) < 4:
            f.add("WARN", "bike.components", name, f"only {len(cats)} categories: {sorted(cats)}")
        if bike.category is None:
            if category_from_discovery(d.bike_type) is not None:
                f.add("ERROR", "bike.category", name, f"NULL, bike_type {d.bike_type!r} maps to a category")
            else:
                f.add("WARN", "bike.category", name, f"NULL, bike_type {d.bike_type!r} not mapped")
        if s.query(models.BikeDetailPhoto.id).filter_by(bike_id=bike.id).first() is None:
            f.add("WARN" if empty("photos") else "ERROR", "bike.photos", name, "none")
        if s.query(models.BikeReview.id).filter_by(bike_id=bike.id).first() is None:
            f.add("WARN" if empty("review") else "ERROR", "bike.review", name, "none")
        listings = s.query(BikeDiscoveryListing).filter_by(discovery_id=d.id).all()
        for li in listings:
            offer = s.query(models.BikeOffer).filter_by(url=li.details_link).first() if li.details_link else None
            if offer is None:
                f.add("ERROR", "offer", name, f"no bike_offer for {li.details_link}")
            elif offer.bike_id != bike.id:
                f.add("WARN", "offer", name, f"{li.details_link} stored under bike {offer.bike_id}")
        if d.status == DONE and not any(li.fetched_at and not li.fetch_error for li in listings):
            # Rows done before the listings split (TODO-039) carry no fetched_at at all.
            legacy = not any(li.fetched_at for li in listings)
            f.add("WARN" if legacy else "ERROR", "fetch", name,
                  "done before TODO-039, no fetch recorded" if legacy else "done but every listing fetch failed")
        brand, model = bike.brand, bike.model
    if read_path:
        details = repository.get_bike_details(brand, model)
        if details is None or (not details.components and not details.description.text):
            f.add("ERROR", "read.details", name, "get_bike_details empty")
        if not photos_repository.get_bike_photos(brand, model).photos and not empty("photos"):
            f.add("ERROR", "read.photos", name, "get_bike_photos empty")
        if not reviews_repository.get_review(brand, model).ref and not empty("review"):
            f.add("ERROR", "read.review", name, "get_review empty")


def recheck(rows: list[BikeDiscovery], n: int, f: Findings, attempts: dict) -> None:
    """Fetch + parse the shop page again for `n` random done bikes and compare with what is stored."""
    for d in random.sample(rows, min(n, len(rows))):
        with session() as s:
            bike = s.get(models.Bike, d.bike_id)
            name = f"{bike.brand} {bike.model} (bike {bike.id})"
            li = next((x for x in s.query(BikeDiscoveryListing).filter_by(discovery_id=d.id)
                       if x.fetched_at and not x.fetch_error), None)
            stored_rows = s.query(models.BikeComponent).filter_by(bike_id=bike.id).count()
            stored_photos = s.query(models.BikeDetailPhoto).filter_by(bike_id=bike.id).count()
            stored_text = _desc_text(bike.description) or ""
        if li is None:
            continue
        try:
            parsed = process_queue._fetch_and_parse(li.source, li.details_link, process_queue.http_fetch, None)
        except Exception as exc:
            f.add("WARN", "recheck.fetch", name, f"{type(exc).__name__}: {exc}")
            continue
        ai = lambda step: f"{bike.id}:{step}" in attempts  # noqa: E731 - the AI touched this part
        resp = parsed.to_details_response(bike.brand, bike.model)
        if not ai("details"):
            page_rows = len(flatten_components(resp.components, include_linkable=True))
            if page_rows != stored_rows:
                f.add("ERROR", "recheck.components", name, f"page {page_rows} rows, DB {stored_rows}")
            if resp.description.text.strip() != stored_text:
                f.add("ERROR", "recheck.description", name, "page text differs from stored")
        if not ai("photos"):
            page_photos = min(len([u for u in parsed.photos if u]), 8)
            if page_photos != stored_photos:
                f.add("WARN", "recheck.photos", name, f"page {page_photos}, DB {stored_photos}")
        f.add("OK", "recheck", name, "compared")


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--recheck", type=int, default=20, help="random done bikes to re-fetch and compare (0 = none)")
    ap.add_argument("--bike", type=int, action="append", help="only this bike id (repeatable)")
    ap.add_argument("--since", type=since_arg, default=None,
                    help="check done/skipped bikes only when their row was updated at/after this ISO time (UTC)")
    ap.add_argument("--no-read-path", action="store_true", help="skip the backend read-path checks (faster)")
    ap.add_argument("--attempts", default=str(DEFAULT_ATTEMPTS), help="enrich's attempts JSON")
    ap.add_argument("--csv", default=None, help="findings CSV (default runs/verify_<timestamp>.csv)")
    ap.add_argument("--allow-remote", action="store_true", help="allow a non-local database (read-only)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    print("database:", check_target(args.allow_remote))
    attempts_path = Path(args.attempts)
    attempts = json.loads(attempts_path.read_text(encoding="utf-8")) if attempts_path.is_file() else {}

    f = Findings()
    with session() as s:
        q = s.query(BikeDiscovery).order_by(BikeDiscovery.id)
        if args.bike:
            q = q.filter(BikeDiscovery.bike_id.in_(args.bike))
        rows = q.all()
        s.expunge_all()
    statuses = Counter(d.status for d in rows)
    for d in rows:
        if d.status in (PENDING, IN_PROGRESS):
            f.add("ERROR", "queue.open", f"{d.company} {d.model} (discovery {d.id})", d.status)
        elif d.status == FAILED:
            f.add("ERROR", "queue.failed", f"{d.company} {d.model} (discovery {d.id})", d.last_error or "")
        elif d.bike_id is None:
            f.add("ERROR", "queue.no_bike", f"{d.company} {d.model} (discovery {d.id})", d.status)
        elif args.since is None or d.updated_at >= args.since:
            check_bike(d, f, attempts, not args.no_read_path)
    if args.recheck:
        recheck([d for d in rows if d.status == DONE and d.bike_id
                 and (args.since is None or d.updated_at >= args.since)], args.recheck, f, attempts)

    RUNS.mkdir(exist_ok=True)
    out = Path(args.csv) if args.csv else RUNS / f"verify_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerows([("level", "check", "bike", "detail"), *f.rows])
    by_check = Counter((r[0], r[1]) for r in f.rows if r[0] != "OK")
    print(f"discovery rows: {len(rows)} | statuses: {dict(statuses)}")
    for (level, check), n in sorted(by_check.items()):
        print(f"  {level:5} {check:24} {n}")
    print(f"ERROR={f.count('ERROR')} WARN={f.count('WARN')} recheck compared={f.count('OK')} | {out}")
    return 1 if f.count("ERROR") else 0


if __name__ == "__main__":
    sys.exit(main())
