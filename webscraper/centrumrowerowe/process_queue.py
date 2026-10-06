"""Process the bike_discovery queue (TODO-036, TODO-039): fetch a listing's page, parse it, store bike details.

Dispatcher and worker in one process, no AI: a batch of bikes is claimed (and
committed) before any network I/O, then each bike's listings are tried newest
first — page fetched, parsed by the parser registered for the listing's shop
(`PARSERS`) — and the first one that parses is saved with `repository.save_bike_details`.

    python process_queue.py --limit 20 --delay 1.0
    python process_queue.py --dry-run          # fetch + parse + print, write nothing
    python process_queue.py --retry-failed     # re-queue failed rows, even exhausted ones
"""
import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

import db  # noqa: E402  (puts backend/ on sys.path, loads backend/.env)
from db import (  # noqa: E402
    DONE, FAILED, IN_PROGRESS, PENDING, SKIPPED, SOURCE, BikeDiscovery, BikeDiscoveryListing, models, repository,
    session, utcnow,
)
from bike_store import (  # noqa: E402,F401  (re-exported for callers and tests)
    KEPT, store_details, store_photos,
)
from bike_store import aware as _aware, tx as _tx  # noqa: E402
from discovery_repo import identity_fields, listed_by, listings_newest_first  # noqa: E402
from scrape_rowery import UA  # noqa: E402
from sqlalchemy import and_, exists, inspect, or_, update  # noqa: E402

logger = logging.getLogger("process_queue")

LOST = "lost"  # the row's lease was taken over by another run; nothing written
FETCH_TIMEOUT = 20.0
MAX_REDIRECTS = 3
ALLOWED_HOSTS = ("www.centrumrowerowe.pl", "centrumrowerowe.pl")
MAX_ATTEMPTS = 3  # the third failure is final (only --retry-failed brings a row back)
LEASE = timedelta(minutes=15)
# The 24 h step is never reached while MAX_ATTEMPTS = 3; it stays for a future higher limit.
BACKOFF = (timedelta(hours=1), timedelta(hours=6), timedelta(hours=24))
GONE_STATUSES = (404, 410)
MAX_ERROR_LEN = 1000
NO_LISTINGS = "bike has no listings — nothing to fetch"

# fetch(url) -> (status_code, html)
Fetch = Callable[[str], tuple[int, str]]


class FetchError(Exception):
    """A product page answered with a status other than 200 / 404 / 410, or redirected too often."""


class UnsafeURL(Exception):
    """A URL outside https://(www.)centrumrowerowe.pl — never fetched."""


class ProductGone(Exception):
    """The listing's page answered 404 / 410."""


class UnknownSource(Exception):
    """No parser is registered for the listing's shop."""


def check_url(url: str) -> str:
    """Return `url` if it is https on an allowed host (default port), else raise UnsafeURL."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in ALLOWED_HOSTS or parts.port not in (None, 443):
        raise UnsafeURL(f"refusing to fetch {url!r}: only https://www.centrumrowerowe.pl pages are allowed")
    return url


def http_fetch(url: str, transport=None) -> tuple[int, str]:
    """GET with the scraper's User-Agent; redirects followed by hand (≤ 3), only to allowed hosts."""
    import httpx

    with httpx.Client(headers=UA, timeout=FETCH_TIMEOUT, follow_redirects=False, transport=transport) as client:
        for _ in range(MAX_REDIRECTS + 1):
            r = client.get(check_url(url))
            location = r.headers.get("location")
            if not (r.is_redirect and location):
                return r.status_code, r.text
            url = urljoin(str(r.url), location)
    raise FetchError(f"more than {MAX_REDIRECTS} redirects, last to {url!r}")


def _parse_centrumrowerowe(html: str, url: str):
    from product_parser import parse_product

    return parse_product(html, url)


# source → parse(html, url) -> ParsedBike, and the URL allowlist checked before every fetch of that shop.
PARSERS = {SOURCE: _parse_centrumrowerowe}
URL_CHECKS = {SOURCE: check_url}


def backoff_for(attempts: int) -> timedelta:
    """Delay before the next try after `attempts` failed tries: 1 h, 6 h, then 24 h."""
    return BACKOFF[min(max(attempts, 1), len(BACKOFF)) - 1]


def _stale_lease(now: datetime):
    return or_(BikeDiscovery.locked_at.is_(None), BikeDiscovery.locked_at < now - LEASE)


def _claimable(now: datetime, source: Optional[str]):
    due = or_(BikeDiscovery.next_attempt_at.is_(None), BikeDiscovery.next_attempt_at <= now)
    retryable = and_(BikeDiscovery.status.in_([PENDING, FAILED]), due, BikeDiscovery.attempts < MAX_ATTEMPTS)
    stale = and_(BikeDiscovery.status == IN_PROGRESS, _stale_lease(now), BikeDiscovery.attempts < MAX_ATTEMPTS)
    cond = or_(retryable, stale)
    return and_(cond, listed_by(source)) if source else cond


def _expire_exhausted_leases(s, now: datetime, source: Optional[str]) -> int:
    """A stale in_progress row that already used its last attempt becomes failed, not stuck."""
    q = s.query(BikeDiscovery).filter(
        BikeDiscovery.status == IN_PROGRESS, _stale_lease(now), BikeDiscovery.attempts >= MAX_ATTEMPTS,
    )
    if source:
        q = q.filter(listed_by(source))
    return q.update({
        BikeDiscovery.status: FAILED,
        BikeDiscovery.locked_at: None,
        BikeDiscovery.last_error: "lease expired on the last attempt",
        BikeDiscovery.updated_at: now,
    }, synchronize_session=False)


def requeue_failed(source: Optional[str], now: Optional[datetime] = None) -> int:
    """--retry-failed: every failed row (exhausted ones too) goes back to pending, due now."""
    now = now or utcnow()
    with _tx() as s:
        q = s.query(BikeDiscovery).filter(BikeDiscovery.status == FAILED)
        if source:
            q = q.filter(listed_by(source))
        return q.update({
            BikeDiscovery.status: PENDING,
            BikeDiscovery.attempts: 0,
            BikeDiscovery.next_attempt_at: None,
            BikeDiscovery.updated_at: now,
        }, synchronize_session=False)


def claim_batch(limit: int, source: Optional[str] = None, now: Optional[datetime] = None) -> list[int]:
    """Claim up to `limit` due rows: in_progress, locked_at = now, attempts += 1; committed on return.

    PostgreSQL locks the candidates with FOR UPDATE SKIP LOCKED, so two processors
    never claim the same row; SQLite (single process) uses a plain select + update.
    """
    now = now or utcnow()
    with _tx() as s:
        _expire_exhausted_leases(s, now, source)
        q = s.query(BikeDiscovery).filter(_claimable(now, source)).order_by(BikeDiscovery.id).limit(limit)
        if s.get_bind().dialect.name == "postgresql":
            q = q.with_for_update(skip_locked=True)
        rows = q.all()
        for row in rows:
            row.status = IN_PROGRESS
            row.locked_at = now
            row.attempts = (row.attempts or 0) + 1
            row.updated_at = now
        return [row.id for row in rows]


def _owned(row_ids: list[int], lease: Optional[datetime]):
    """WHERE clause: these rows, still in_progress and — when `lease` is known — still on that lease."""
    cond = and_(BikeDiscovery.id.in_(row_ids), BikeDiscovery.status == IN_PROGRESS)
    return and_(cond, BikeDiscovery.locked_at == lease) if lease is not None else cond


def release_rows(row_ids: list[int], lease: Optional[datetime] = None) -> int:
    """Hand claimed-but-unfinished rows back (Ctrl+C): pending again, the attempt not counted."""
    if not row_ids:
        return 0
    with _tx() as s:
        rows = s.query(BikeDiscovery).filter(_owned(row_ids, lease)).all()
        for row in rows:
            row.status = PENDING
            row.locked_at = None
            row.attempts = max((row.attempts or 0) - 1, 0)
            row.updated_at = utcnow()
        return len(rows)


def _take_lease(row_id: int, claimed_at: Optional[datetime] = None) -> Optional[datetime]:
    """Refresh the row's lease as its work starts; None when another run owns it now."""
    lease = utcnow()
    with _tx() as s:
        result = s.execute(update(BikeDiscovery).where(_owned([row_id], claimed_at))
                           .values(locked_at=lease, updated_at=lease))
        return lease if result.rowcount == 1 else None


def _finish(row_id: int, lease: Optional[datetime], company: Optional[str] = None, model: Optional[str] = None,
            **fields) -> bool:
    """Write the outcome only if this run still holds the lease; False (nothing written) otherwise.

    `company`/`model` (the bike's stored casing) go in with their norms — unless another
    bike_discovery row already owns that identity, then the row keeps its name.
    """
    fields.update(locked_at=None, updated_at=utcnow())
    with _tx() as s:
        if company is not None:
            fields.update(identity_fields(s, row_id, company, model))
        result = s.execute(update(BikeDiscovery).where(_owned([row_id], lease)).values(**fields))
        return result.rowcount == 1


def _mark_listing(row_id: int, lease: Optional[datetime], listing_id: int, error: Optional[str]) -> None:
    """Record a fetch attempt on the listing — only while this run still holds the bike's lease."""
    now = utcnow()
    with _tx() as s:
        s.execute(update(BikeDiscoveryListing)
                  .where(BikeDiscoveryListing.id == listing_id, exists().where(_owned([row_id], lease)))
                  .values(fetched_at=now, fetch_error=error, updated_at=now))


def _fetch_and_parse(source: str, url: Optional[str], fetch: Fetch, parse):
    """One listing's page → parsed bike. Raises ProductGone on 404/410, anything else on any other failure."""
    if not url:
        raise ValueError("listing has no details_link")
    if source not in PARSERS:
        raise UnknownSource(f"no parser registered for source {source!r}")
    status, html = fetch(URL_CHECKS[source](url))
    if status in GONE_STATUSES:
        raise ProductGone(f"HTTP {status}: product gone")
    if status != 200:
        raise FetchError(f"HTTP {status} for {url}")
    return (parse or PARSERS[source])(html, url)


def _error_text(exc: Exception) -> str:
    return (str(exc) if isinstance(exc, ProductGone) else f"{type(exc).__name__}: {exc}")[:MAX_ERROR_LEN]


def process_row(row_id: int, fetch: Fetch = http_fetch, parse=None, claimed_at: Optional[datetime] = None) -> str:
    """Fetch, parse and store one claimed bike; returns its final status. Never raises (bar Ctrl+C).

    The bike's listings are tried newest `last_seen_at` first; the first page that parses wins,
    and every attempt is recorded on its listing (fetched_at / fetch_error). The bike fails only
    when every listing failed (or it has none) and is skipped when every listing is gone (404/410).
    `parse` overrides PARSERS (tests). `claimed_at` (the claim's locked_at) makes the lease check
    exact; without it any in_progress row is taken.
    """
    lease = _take_lease(row_id, claimed_at)
    if lease is None:
        logger.warning("lost | row %s | no longer in_progress on our lease, left alone", row_id)
        return LOST
    with session() as s:
        row = s.get(BikeDiscovery, row_id)
        attempts, name = row.attempts, f"{row.company} {row.model}"
        listings = [(li.id, li.source, li.source_product_id, li.details_link)
                    for li in listings_newest_first(s, row_id)]

    def finish(outcome: str, **fields) -> str:
        if _finish(row_id, lease, status=outcome, **fields):
            return outcome
        logger.warning("lost | %s | lease taken over before %s could be written", name, outcome)
        return LOST

    def fail(error: str) -> str:
        logger.warning("failed | %s | attempt %s | %s", name, attempts, error)
        return finish(FAILED, last_error=error[:MAX_ERROR_LEN], next_attempt_at=utcnow() + backoff_for(attempts))

    try:
        errors, gone, parsed = [], 0, None
        for listing_id, source, pid, url in listings:
            try:
                parsed = _fetch_and_parse(source, url, fetch, parse)
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # one bad listing never stops the others
                error = _error_text(exc)
                gone += isinstance(exc, ProductGone)
                errors.append(f"{pid}: {error}" if len(listings) > 1 else error)
                logger.info("listing failed | %s | %s | %s", pid, url, error)
                _mark_listing(row_id, lease, listing_id, error)
                continue
            _mark_listing(row_id, lease, listing_id, None)
            break
        if parsed is None:
            if not listings:
                return fail(NO_LISTINGS)
            if gone == len(listings):
                logger.info("skipped | %s | every listing gone", name)
                return finish(SKIPPED, last_error="; ".join(errors)[:MAX_ERROR_LEN], next_attempt_at=None)
            return fail("; ".join(errors))

        outcome, bike_id, company, model, response = store_details(
            parsed.brand, parsed.model, parsed.to_details_response,
            bike_type=parsed.bike_type)
        # Photos are independent of details: stored whenever the bike has none, never replaced.
        photos = store_photos(bike_id, company, model, parsed.photos)
        if outcome == KEPT:  # existing details (AI- or earlier-parsed) win; nothing overwritten
            logger.info("skipped | %s | details exist for bike %s %r %r | photos %s",
                        name, bike_id, company, model, photos)
            return finish(SKIPPED, bike_id=bike_id, company=company, model=model,
                          last_error=None, next_attempt_at=None)
        logger.info("done | %s | bike %s %r %r | photos %s", name, bike_id, company, model, photos)
        return finish(DONE, bike_id=bike_id, company=company, model=model,
                      last_error=None, next_attempt_at=None)
    except KeyboardInterrupt:
        release_rows([row_id], lease)
        raise
    except Exception as exc:  # e.g. the save did not land; one bad bike never stops the batch
        return fail(f"{type(exc).__name__}: {exc}")


def _table_exists() -> bool:
    if db.has_old_layout():
        raise SystemExit(db.OLD_LAYOUT_MESSAGE)
    return inspect(models.get_engine()).has_table(BikeDiscovery.__tablename__)


def dry_run(limit: int, source: Optional[str], retry_failed: bool, delay: float,
            fetch: Fetch = http_fetch, parse=None) -> int:
    """Fetch + parse the listings of the bikes a real run would claim and print them; claims and writes nothing."""
    if not _table_exists():
        print("bike_discovery does not exist yet — run scrape_rowery.py first")
        return 0
    now = utcnow()
    with session() as s:
        cond = _claimable(now, source)
        if retry_failed:
            failed = BikeDiscovery.status == FAILED
            cond = or_(cond, and_(failed, listed_by(source)) if source else failed)
        bikes = [(r.id, f"{r.company} {r.model}")
                 for r in s.query(BikeDiscovery).filter(cond).order_by(BikeDiscovery.id).limit(limit)]
        listings = {i: [(li.source, li.source_product_id, li.details_link) for li in listings_newest_first(s, i)]
                    for i, _ in bikes}
        s.rollback()
    fetched = 0
    for bike_id, name in bikes:
        if not listings[bike_id]:
            print(f"{name}: {NO_LISTINGS}")
        for src, pid, url in listings[bike_id]:  # like a real run: stop at the first page that parses
            if fetched:
                time.sleep(delay)
            fetched += 1
            try:
                p = _fetch_and_parse(src, url, fetch, parse)
            except Exception as exc:
                print(f"{pid}: ERROR {_error_text(exc)}")
                continue
            n_specs = sum(len(el.specs) for c in p.components for sub in c.subcategories for el in sub.elements)
            print(f"{pid}: {p.brand!r} {p.model!r} type={p.bike_type!r} electric={p.is_electric} "
                  f"sizes={p.frame_sizes} photos={len(p.photos)} categories={len(p.components)} specs={n_specs}")
            break
    print(f"dry run: {len(bikes)} bikes, nothing written")
    return len(bikes)


def run(limit: int, source: Optional[str], delay: float, retry_failed: bool,
        fetch: Fetch = http_fetch, parse=None) -> dict[str, int]:
    db.ensure_table()
    if retry_failed:
        logger.info("re-queued %d failed rows", requeue_failed(source))
    counts = {DONE: 0, SKIPPED: 0, FAILED: 0, LOST: 0}
    claimed_at = utcnow()
    claimed = claim_batch(limit, source, claimed_at)
    logger.info("claimed %d rows", len(claimed))
    for i, row_id in enumerate(claimed):
        try:
            if i:
                time.sleep(delay)
            counts[process_row(row_id, fetch=fetch, parse=parse, claimed_at=claimed_at)] += 1
        except KeyboardInterrupt:
            # The row being processed was released by process_row; the rest still hold the claim's lease.
            released = release_rows(claimed[i:], claimed_at)
            logger.warning("interrupted — released %d unprocessed rows", released)
            raise
    return counts


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limit", type=int, default=20, help="bikes to claim (default 20)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between page fetches (default 1.0)")
    ap.add_argument("--source", default=None, help=f"only bikes with a listing from this shop, e.g. {SOURCE}")
    ap.add_argument("--retry-failed", action="store_true", help="re-queue failed rows, even after 3 attempts")
    ap.add_argument("--dry-run", action="store_true", help="fetch + parse + print; claim and write nothing")
    ap.add_argument("--allow-remote", action="store_true", help="allow writing to a non-local database")
    args = ap.parse_args(argv)
    if args.limit < 1 or args.delay < 0:
        ap.error("--limit must be >= 1 and --delay >= 0")
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # A dry run writes nothing, so it only prints the target instead of refusing a remote one.
    target = db.check_target(allow_remote=args.allow_remote or args.dry_run)
    logger.info("database: %s", target)
    if args.dry_run:
        dry_run(args.limit, args.source, args.retry_failed, args.delay, fetch=http_fetch)
        return 0
    try:
        counts = run(args.limit, args.source, args.delay, args.retry_failed, fetch=http_fetch)
    except KeyboardInterrupt:
        print("interrupted")
        return 130
    lost = f" lost={counts[LOST]}" if counts[LOST] else ""
    print(f"done={counts[DONE]} skipped={counts[SKIPPED]} failed={counts[FAILED]}{lost}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
