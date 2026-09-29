"""Process the bike_discovery queue (TODO-036): fetch each product page, parse it, store bike details.

Dispatcher and worker in one process, no AI: a batch of rows is claimed (and
committed) before any network I/O, then each page is fetched, parsed by
`product_parser.parse_product` and saved with `repository.save_bike_details`.

    python process_queue.py --limit 20 --delay 1.0
    python process_queue.py --dry-run          # fetch + parse + print, write nothing
    python process_queue.py --retry-failed     # re-queue failed rows, even exhausted ones
    python process_queue.py --sync-cache       # copy done rows' details into the /v1/bike/details cache
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
    DONE, FAILED, IN_PROGRESS, PENDING, SKIPPED, SOURCE, BikeDiscovery, models, repository, session, utcnow,
)
from bike_store import (  # noqa: E402,F401  (re-exported for callers and tests)
    CACHE_FAILED, CACHE_MISSING, CACHE_PRESENT, CACHE_WRITTEN, DETAILS_ENDPOINT, KEPT,
    cache_details, store_details,
)
from bike_store import aware as _aware, tx as _tx  # noqa: E402
from scrape_rowery import UA  # noqa: E402
from sqlalchemy import and_, inspect, or_, update  # noqa: E402

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

# fetch(url) -> (status_code, html)
Fetch = Callable[[str], tuple[int, str]]


class FetchError(Exception):
    """A product page answered with a status other than 200 / 404 / 410, or redirected too often."""


class UnsafeURL(Exception):
    """A URL outside https://(www.)centrumrowerowe.pl — never fetched."""


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


def _default_parse(html: str, url: str):
    from product_parser import parse_product

    return parse_product(html, url)


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
    return and_(cond, BikeDiscovery.source == source) if source else cond


def _expire_exhausted_leases(s, now: datetime, source: Optional[str]) -> int:
    """A stale in_progress row that already used its last attempt becomes failed, not stuck."""
    q = s.query(BikeDiscovery).filter(
        BikeDiscovery.status == IN_PROGRESS, _stale_lease(now), BikeDiscovery.attempts >= MAX_ATTEMPTS,
    )
    if source:
        q = q.filter(BikeDiscovery.source == source)
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
            q = q.filter(BikeDiscovery.source == source)
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


def _finish(row_id: int, lease: Optional[datetime], **fields) -> bool:
    """Write the outcome only if this run still holds the lease; False (nothing written) otherwise."""
    fields.update(locked_at=None, updated_at=utcnow())
    with _tx() as s:
        result = s.execute(update(BikeDiscovery).where(_owned([row_id], lease)).values(**fields))
        return result.rowcount == 1


def process_row(row_id: int, fetch: Fetch = http_fetch, parse=None, claimed_at: Optional[datetime] = None) -> str:
    """Fetch, parse and store one claimed row; returns its final status. Never raises (bar Ctrl+C).

    `claimed_at` (the claim's locked_at) makes the lease check exact; without it
    any in_progress row is taken.
    """
    parse = parse or _default_parse
    lease = _take_lease(row_id, claimed_at)
    if lease is None:
        logger.warning("lost | row %s | no longer in_progress on our lease, left alone", row_id)
        return LOST
    with session() as s:
        row = s.get(BikeDiscovery, row_id)
        url, attempts, pid = row.details_link, row.attempts, row.source_product_id

    def finish(outcome: str, **fields) -> str:
        if _finish(row_id, lease, status=outcome, **fields):
            return outcome
        logger.warning("lost | %s | lease taken over before %s could be written", pid, outcome)
        return LOST

    try:
        if not url:
            raise ValueError("row has no details_link")
        status, html = fetch(check_url(url))
        if status in GONE_STATUSES:
            logger.info("skipped | %s | HTTP %s | %s", pid, status, url)
            return finish(SKIPPED, last_error=f"HTTP {status}: product gone", next_attempt_at=None)
        if status != 200:
            raise FetchError(f"HTTP {status} for {url}")

        parsed = parse(html, url)
        outcome, bike_id, company, model, response = store_details(
            parsed.brand, parsed.model, parsed.to_details_response)
        if outcome == KEPT:  # fresh details (AI- or earlier-parsed) win; nothing overwritten
            logger.info("skipped | %s | fresh details for bike %s %r %r", pid, bike_id, company, model)
            return finish(SKIPPED, bike_id=bike_id, company=company, model=model,
                          last_error=None, next_attempt_at=None)
        cache_outcome = cache_details(company, model, response)
        logger.info("done | %s | bike %s %r %r | cache %s", pid, bike_id, company, model, cache_outcome)
        return finish(DONE, bike_id=bike_id, company=company, model=model,
                      last_error=None, next_attempt_at=None)
    except KeyboardInterrupt:
        release_rows([row_id], lease)
        raise
    except Exception as exc:  # one bad page never stops the batch
        error = f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LEN]
        logger.warning("failed | %s | attempt %s | %s", pid, attempts, error)
        return finish(FAILED, last_error=error, next_attempt_at=utcnow() + backoff_for(attempts))


def sync_cache(source: Optional[str], dry_run: bool = False) -> dict[str, int]:
    """--sync-cache: put the stored details of every done row's bike into the generic details cache.

    No fetching, no claiming. Missing = the bike has no fresh details (> TTL or gone).
    A dry run counts what would be written and writes nothing.
    """
    counts = {CACHE_WRITTEN: 0, CACHE_PRESENT: 0, CACHE_MISSING: 0, CACHE_FAILED: 0}
    with session() as s:
        q = (s.query(models.Bike.brand, models.Bike.model)
             .join(BikeDiscovery, BikeDiscovery.bike_id == models.Bike.id)
             .filter(BikeDiscovery.status == DONE).distinct())
        if source:
            q = q.filter(BikeDiscovery.source == source)
        bikes = sorted(q.all())
    for brand, model in bikes:
        details = repository.get_bike_details(brand, model)
        outcome = CACHE_MISSING if details is None else cache_details(brand, model, details, write=not dry_run)
        counts[outcome] += 1
    return counts


def _table_exists() -> bool:
    return inspect(models.get_engine()).has_table(BikeDiscovery.__tablename__)


def dry_run(limit: int, source: Optional[str], retry_failed: bool, delay: float,
            fetch: Fetch = http_fetch, parse=None) -> int:
    """Fetch + parse the rows a real run would claim and print them; claims and writes nothing."""
    parse = parse or _default_parse
    if not _table_exists():
        print("bike_discovery does not exist yet — run scrape_rowery.py first")
        return 0
    now = utcnow()
    with session() as s:
        cond = _claimable(now, source)
        if retry_failed:
            failed = BikeDiscovery.status == FAILED
            cond = or_(cond, and_(failed, BikeDiscovery.source == source) if source else failed)
        rows = [(r.source_product_id, r.details_link)
                for r in s.query(BikeDiscovery).filter(cond).order_by(BikeDiscovery.id).limit(limit)]
        s.rollback()
    for i, (pid, url) in enumerate(rows):
        if i:
            time.sleep(delay)
        try:
            status, html = fetch(check_url(url))
            if status != 200:
                print(f"{pid}: HTTP {status} {url}")
                continue
            p = parse(html, url)
            n_specs = sum(len(el.specs) for c in p.components for sub in c.subcategories for el in sub.elements)
            print(f"{pid}: {p.brand!r} {p.model!r} type={p.bike_type!r} electric={p.is_electric} "
                  f"sizes={p.frame_sizes} photos={len(p.photos)} categories={len(p.components)} specs={n_specs}")
        except Exception as exc:
            print(f"{pid}: ERROR {type(exc).__name__}: {exc}")
    print(f"dry run: {len(rows)} rows, nothing written")
    return len(rows)


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
    ap.add_argument("--limit", type=int, default=20, help="rows to claim (default 20)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between page fetches (default 1.0)")
    ap.add_argument("--source", default=None, help=f"only this source, e.g. {SOURCE}")
    ap.add_argument("--retry-failed", action="store_true", help="re-queue failed rows, even after 3 attempts")
    ap.add_argument("--dry-run", action="store_true", help="fetch + parse + print; claim and write nothing")
    ap.add_argument("--allow-remote", action="store_true", help="allow writing to a non-local database")
    ap.add_argument("--sync-cache", action="store_true",
                    help="no fetching: copy stored details of done rows into the /v1/bike/details cache")
    args = ap.parse_args(argv)
    if args.limit < 1 or args.delay < 0:
        ap.error("--limit must be >= 1 and --delay >= 0")
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # A dry run writes nothing, so it only prints the target instead of refusing a remote one.
    target = db.check_target(allow_remote=args.allow_remote or args.dry_run)
    logger.info("database: %s", target)
    if args.sync_cache:
        if not _table_exists():
            print("bike_discovery does not exist yet — nothing to sync")
            return 0
        c = sync_cache(args.source, dry_run=args.dry_run)
        verb = "would write" if args.dry_run else "written"
        print(f"cache sync: {verb}={c[CACHE_WRITTEN]} already present={c[CACHE_PRESENT]} "
              f"missing details={c[CACHE_MISSING]} failed={c[CACHE_FAILED]}")
        return 0
    if args.dry_run:
        dry_run(args.limit, args.source, args.retry_failed, args.delay, fetch=http_fetch, parse=_default_parse)
        return 0
    try:
        counts = run(args.limit, args.source, args.delay, args.retry_failed, fetch=http_fetch, parse=_default_parse)
    except KeyboardInterrupt:
        print("interrupted")
        return 130
    lost = f" lost={counts[LOST]}" if counts[LOST] else ""
    print(f"done={counts[DONE]} skipped={counts[SKIPPED]} failed={counts[FAILED]}{lost}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
