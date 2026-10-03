"""Fill bike_detail_photos.bg_color (the results tile's frame colour) for photos stored before it existed.

Run AFTER scripts/migrate_photo_bg_color.py. For every bike's COVER photo (the same rule as the
read path: `photo_cover.get_cover_photos` / `is_cover_candidate`) whose bg_color IS NULL, the image
is downloaded (size-capped), `photo_color.edge_color` computed and the row UPDATEd. `--all` takes
every photo row with a NULL instead of the covers only.

    python scripts/backfill_photo_bg_color.py --dry-run            # which photos would be fetched
    python scripts/backfill_photo_bg_color.py                      # covers, $DATABASE_URL (backend/.env) else cache.db
    python scripts/backfill_photo_bg_color.py --all --limit 200
    python scripts/backfill_photo_bg_color.py --db path/to/copy.db
    python scripts/backfill_photo_bg_color.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

A photo whose colour cannot be had (transparent corners, download failed) stays NULL and is retried
by the next run (a transparent PNG is re-downloaded each time - cheap, and the tile then uses the
light default). Idempotent: a second run only touches rows still NULL. Download workers: 4.

Database guard (like the discovery scripts): the target is printed with the password masked and a
non-local database is refused without `--allow-remote`. Local = SQLite, or host localhost / 127.0.0.1
/ ::1 on a port other than 6543 (the Cloud SQL proxy); port 6543 and /cloudsql sockets count as remote.
Never write to the production Cloud SQL without an explicit decision.

Summary: `checked / updated / no_colour (transparent or failed) / errors`.
"""
import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

from app.models import DEFAULT_DB_PATH  # noqa: E402
from app.photo_color import edge_color, fetch_image_bytes  # noqa: E402
from app.photo_cover import is_cover_candidate, pick_covers  # noqa: E402

WORKERS = 4
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
PROXY_PORT = 6543


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def is_local(url: str) -> bool:
    """SQLite, or localhost on a port other than the Cloud SQL proxy's 6543."""
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        return True
    host = (parsed.host or "").lower()
    if host.startswith("/") or "cloudsql" in host or "cloudsql" in str(parsed.query):
        return False
    return host in LOCAL_HOSTS and parsed.port != PROXY_PORT


def select_targets(rows, all_photos: bool) -> list[tuple[int, int, str]]:
    """(photo id, bike id, url) to colour, from `(id, bike_id, url, bg_color)` rows in display order.

    Covers only: the cover of each bike (`photo_cover.pick_covers`: first non-thumbnail candidate), when its bg_color is NULL. `all_photos`:
    every candidate photo with a NULL. (A cover whose colour is set is done, even if later photos
    are NULL.)
    """
    targets: list[tuple[int, int, str]] = []
    if all_photos:
        for photo_id, bike_id, url, bg_color in rows:
            if is_cover_candidate(url) and bg_color is None:
                targets.append((photo_id, bike_id, url))
        return targets
    # the same pick as the read path (first non-thumbnail candidate); the photo id rides in the colour slot
    covers = pick_covers((bike_id, url, (photo_id, bg_color)) for photo_id, bike_id, url, bg_color in rows)
    for bike_id, (url, (photo_id, bg_color)) in covers.items():
        if bg_color is None:
            targets.append((photo_id, bike_id, url))
    return targets


def _compute(target) -> tuple[int, str | None, bool]:
    """(photo id, colour or None, error) — never raises."""
    photo_id, _bike_id, url = target
    try:
        data = fetch_image_bytes(url)
        return photo_id, (edge_color(data) if data else None), False
    except Exception as exc:  # noqa: BLE001
        print(f"  error photo {photo_id}: {exc}")
        return photo_id, None, True


def backfill(url_or_path=None, *, all_photos: bool = False, limit: int | None = None,
             dry_run: bool = False, allow_remote: bool = False, verbose: bool = True) -> dict:
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    report = {"database": make_url(url).render_as_string(hide_password=True), "checked": 0, "updated": 0,
              "no_colour": 0, "errors": 0, "status": ""}
    say(f"database: {report['database']}")
    if not is_local(url) and not allow_remote:
        report["status"] = "refused"
        say("refusing a non-local database without --allow-remote")
        return report
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT id, bike_id, url, bg_color FROM bike_detail_photos ORDER BY bike_id, display_order, id"
            )).fetchall()
        targets = select_targets(rows, all_photos)
        if limit is not None:
            targets = targets[:limit]
        say(f"{len(targets)} photo(s) to colour ({'every photo' if all_photos else 'covers only'} with a NULL bg_color)")
        if dry_run:
            for photo_id, bike_id, photo_url in targets[:20]:
                say(f"  would fetch photo {photo_id} (bike {bike_id}) {photo_url}")
            report["status"] = "dry-run"
            return report
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            results = list(pool.map(_compute, targets))
        updates = []
        for photo_id, color, error in results:
            report["checked"] += 1
            if error:
                report["errors"] += 1
            elif color is None:
                report["no_colour"] += 1
            else:
                updates.append({"c": color, "i": photo_id})
        if updates:
            with engine.begin() as conn:
                conn.execute(text("UPDATE bike_detail_photos SET bg_color = :c WHERE id = :i AND bg_color IS NULL"), updates)
        report["updated"] = len(updates)
        report["status"] = "done"
        say(f"checked={report['checked']} updated={report['updated']} "
            f"no_colour={report['no_colour']} errors={report['errors']}")
        return report
    finally:
        engine.dispose()


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = ap.add_mutually_exclusive_group()
    target.add_argument("--db", type=Path, help="SQLite file")
    target.add_argument("--url", help="SQLAlchemy URL (default: $DATABASE_URL, else backend/cache.db)")
    ap.add_argument("--all", action="store_true", dest="all_photos", help="every photo with a NULL, not only the covers")
    ap.add_argument("--limit", type=int, help="at most N photos")
    ap.add_argument("--dry-run", action="store_true", help="list what would be fetched, write nothing")
    ap.add_argument("--allow-remote", action="store_true", help="permit a non-local database")
    args = ap.parse_args()
    if args.db is not None and not args.db.exists():
        print(f"SQLite file not found: {args.db}")
        return 1
    report = backfill(args.db or args.url, all_photos=args.all_photos, limit=args.limit,
                      dry_run=args.dry_run, allow_remote=args.allow_remote)
    return 1 if report["status"] == "refused" else 0


if __name__ == "__main__":
    sys.exit(main())
