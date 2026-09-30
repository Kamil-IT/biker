"""Copy the generic-cache bike reviews into bike_review / bike_review_source (TODO-037).

Before TODO-037, POST /v1/bike/review kept each answer as a JSON blob in the
generic cache (`endpoint_req_to_body_cache`, endpoint '/v1/bike/review'). The
endpoint now reads only the review tables, so this one-off script carries the
existing answers over. The cache rows themselves are left in place (dead rows).

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/copy_review_cache_to_table.py --dry-run
    python scripts/copy_review_cache_to_table.py
    python scripts/copy_review_cache_to_table.py --db path/to/copy.db
    python scripts/copy_review_cache_to_table.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker
    python scripts/copy_review_cache_to_table.py --force   # overwrite reviews already in bike_review

Rules:
  - request JSON -> company/model; response JSON -> BikeReviewResponse. Either
    unreadable -> counted as `unparseable`.
  - only `ref` URLs passing the searcher's is_safe_review_url rule are kept
    (http(s) + host, <= 2048 chars, not escapecollective.com / velominati.com;
    others dropped, counted as `dropped_urls`); a row left with no URL counts as degenerate.
  - only rows with a non-empty `ref` AND sources_used >= 1 are copied (the
    same bar the searcher applies before storing); the rest -> `skipped_degenerate`.
  - the bike is looked up by Python-normalised brand/model (strip().lower(),
    oldest id wins) and never created; a miss -> `skipped_unknown_bike`, listed.
  - a bike that already has a bike_review row -> `skipped_existing`, unless
    --force, which replaces the review and its sources (updated_at never goes
    backwards). Cache rows are read newest first, so when several map to one
    bike the newest wins and the rest count as `skipped_existing`.
  - missing bike_review tables are created (init_db()) unless --dry-run, so it
    can run on a database before the searcher is deployed there.
  - `ref` order becomes display_order 0..n-1; created_at / updated_at = the
    cache row's time_stored.
Everything runs in ONE transaction through the app's SQLAlchemy engine
(SQLite and PostgreSQL); --dry-run rolls it back. Re-running changes nothing.
Also importable: `copy_reviews(url_or_path=None, dry_run=False, force=False, verbose=True) -> dict`.

Exit code: 0 on success, 1 when the run failed (database unchanged).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import ValidationError
from sqlalchemy import inspect, select

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.models import (  # noqa: E402
    Bike, BikeReview, BikeReviewSource, configure_db, endpoint_req_to_body_cache,
    get_engine, get_session, init_db,
)
from app.schemas import BikeReviewResponse  # noqa: E402

REVIEW_ENDPOINT = "/v1/bike/review"
COUNTERS = ("copied", "skipped_existing", "skipped_unknown_bike", "skipped_degenerate", "unparseable")


# Duplicates searcher/app/review_finder.py is_safe_review_url (the backend cannot
# import the searcher) — keep the two identical.
BANNED_REVIEW_DOMAINS = frozenset({"escapecollective.com", "velominati.com"})
URL_MAX_LEN = 2048  # bike_review_source.url is String(2048)


def _host(value: str) -> str:
    """Lower-cased host of a URL or bare domain ("www." stripped), "" when there is none."""
    value = value.strip()
    if "://" not in value:
        value = "//" + value
    try:
        host = (urlsplit(value).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _is_banned(value: str) -> bool:
    host = _host(value)
    return any(host == d or host.endswith("." + d) for d in BANNED_REVIEW_DOMAINS)


def _safe_url(url) -> bool:
    """http/https with a host, <= URL_MAX_LEN chars, no surrounding whitespace, not a banned domain."""
    if not isinstance(url, str) or not url or len(url) > URL_MAX_LEN or url != url.strip():
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.netloc) and not _is_banned(url)


def _norm(value: str) -> str:
    return value.strip().lower()


def _parse_time(raw) -> datetime:
    """The cache row's ISO-8601 time_stored as an aware UTC datetime; now when unreadable."""
    try:
        ts = datetime.fromisoformat(str(raw))
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def _naive_utc(ts: datetime) -> datetime:
    """Comparable form: the DB hands back naive UTC, the parsed cache stamp is aware."""
    return ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts


def _parse_row(request: str, response: str):
    """(company, model, BikeReviewResponse) or None when either JSON is unreadable."""
    try:
        req = json.loads(request)
        company, model = req["company"], req["model"]
        if not isinstance(company, str) or not isinstance(model, str) or not model.strip():
            return None
        return company, model, BikeReviewResponse.model_validate_json(response)
    except (TypeError, ValueError, KeyError, ValidationError):
        return None


def copy_reviews(url_or_path=None, dry_run: bool = False, force: bool = False, verbose: bool = True) -> dict:
    """Copy one database's cached reviews; returns a report dict (counters + lists + status)."""
    say = print if verbose else (lambda *a, **k: None)
    if url_or_path is not None:
        configure_db(url_or_path)
    engine = get_engine()
    report = {
        "database": engine.url.render_as_string(hide_password=True),
        "status": "", "error": None, "cache_rows": 0,
        **{k: 0 for k in COUNTERS}, "dropped_urls": 0,
        "unknown_bikes": [], "copied_bikes": [],
    }
    say(f"database: {report['database']}")
    try:
        insp = inspect(engine)
        if not insp.has_table(endpoint_req_to_body_cache.name):
            report["status"] = "no-cache-table"
            say("endpoint_req_to_body_cache does not exist — nothing to copy")
            return report
        tables_exist = insp.has_table(BikeReview.__tablename__) and insp.has_table(BikeReviewSource.__tablename__)
        if not dry_run and not tables_exist:
            init_db()  # the review tables are new in TODO-037; create_all() adds only missing tables
            tables_exist = True

        t = endpoint_req_to_body_cache
        with get_session() as session:
            try:
                rows = session.execute(
                    select(t.c.request, t.c.response, t.c.time_stored)
                    .where(t.c.endpoint == REVIEW_ENDPOINT)
                    .order_by(t.c.time_stored.desc(), t.c.request)  # newest first: it wins a shared bike
                ).all()
                report["cache_rows"] = len(rows)

                bike_ids: dict[tuple[str, str], int] = {}
                for b in session.execute(select(Bike.id, Bike.brand, Bike.model).order_by(Bike.id)):
                    bike_ids.setdefault((_norm(b.brand), _norm(b.model)), b.id)
                existing: dict[int, BikeReview] = {}
                if tables_exist:
                    existing = {r.bike_id: r for r in session.query(BikeReview)}
                done: set[int] = set()

                for request, response, time_stored in rows:
                    parsed = _parse_row(request, response)
                    if parsed is None:
                        report["unparseable"] += 1
                        say(f"  unparseable: request={request[:120]!r}")
                        continue
                    company, model, review = parsed
                    safe_ref = [u for u in review.ref if _safe_url(u)]
                    report["dropped_urls"] += len(review.ref) - len(safe_ref)
                    review.ref = safe_ref
                    if not review.ref or review.sources_used < 1:
                        report["skipped_degenerate"] += 1
                        continue
                    bike_id = bike_ids.get((_norm(company), _norm(model)))
                    if bike_id is None:
                        report["skipped_unknown_bike"] += 1
                        report["unknown_bikes"].append(f"{company} / {model}")
                        continue
                    if bike_id in done or (bike_id in existing and not force):
                        report["skipped_existing"] += 1
                        continue

                    stamp = _parse_time(time_stored)
                    row = existing.get(bike_id)
                    if row is None:
                        row = BikeReview(bike_id=bike_id, created_at=stamp)
                        session.add(row)
                    row.score, row.explanation = review.score, review.explanation
                    row.rating, row.sources_used = review.rating, review.sources_used
                    # --force never moves updated_at backwards past what is already stored.
                    row.updated_at = max(_naive_utc(row.updated_at), _naive_utc(stamp)) if row.updated_at else stamp
                    row.sources = [BikeReviewSource(url=url, display_order=i) for i, url in enumerate(review.ref)]
                    done.add(bike_id)
                    report["copied"] += 1
                    report["copied_bikes"].append(f"{company} / {model}")

                if dry_run:
                    session.rollback()
                else:
                    session.commit()
            except BaseException:
                session.rollback()
                raise
        report["status"] = "dry-run" if dry_run else "copied"
    except Exception as exc:  # noqa: BLE001 — reported, exit code 1
        report["status"], report["error"] = "failed", str(exc)
        say(f"FAILED — rolled back, database unchanged.\n  {exc}")
        return report

    for name in report["unknown_bikes"]:
        say(f"  unknown bike (not in `bike`), skipped: {name}")
    verb = "would copy" if dry_run else "copied"
    say(f"{report['cache_rows']} cached review rows: {verb} {report['copied']}, "
        + ", ".join(f"{k} {report[k]}" for k in (*COUNTERS[1:], "dropped_urls"))
        + (" — dry run, nothing written" if dry_run else ""))
    return report


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")  # DATABASE_URL selects the database, as for the server
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = ap.add_mutually_exclusive_group()
    target.add_argument("--db", type=Path, help="SQLite file to copy into")
    target.add_argument("--url", help="SQLAlchemy URL (default: $DATABASE_URL, else backend/cache.db)")
    ap.add_argument("--dry-run", action="store_true", help="report what would be copied, write nothing")
    ap.add_argument("--force", action="store_true", help="overwrite reviews already stored in bike_review")
    args = ap.parse_args()
    if args.db is not None and not args.db.exists():
        print(f"SQLite file not found: {args.db}")
        return 1
    report = copy_reviews(args.db or args.url, dry_run=args.dry_run, force=args.force)
    print("\nRESULT:", report["status"])
    return 0 if report["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
