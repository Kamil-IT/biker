"""Delete the generic-cache rows of POST /v1/bike/details (TODO-041).

`/v1/bike/details` is a pure DB read now; its old `endpoint_req_to_body_cache`
rows (endpoint '/v1/bike/details') are dead — nothing reads them. This removes
exactly those rows and nothing else (equipment details, ceneo, ... stay). Run it
locally; on production only on an explicit decision.

    # database defaults to $DATABASE_URL (backend/.env), else backend/cache.db
    python scripts/purge_details_cache.py --dry-run
    python scripts/purge_details_cache.py
    python scripts/purge_details_cache.py --db path/to/copy.db
    python scripts/purge_details_cache.py --url postgresql+psycopg://biker:biker@127.0.0.1:5432/biker

Importable: `purge(url_or_path=None, dry_run=False, verbose=True) -> dict`
(`status` "purged" / "dry-run" / "absent" / "failed", `rows` = rows matched/deleted).
Idempotent. Exit code 0 on success, 1 on failure.
"""
import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

from app.models import DEFAULT_DB_PATH  # noqa: E402

TABLE = "endpoint_req_to_body_cache"
ENDPOINT = "/v1/bike/details"


def _url(url_or_path) -> str:
    if url_or_path is None:
        return os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_DB_PATH}"
    value = str(url_or_path)
    return value if "://" in value else f"sqlite:///{Path(value)}"


def purge(url_or_path=None, dry_run: bool = False, verbose: bool = True) -> dict:
    say = print if verbose else (lambda *a, **k: None)
    url = _url(url_or_path)
    engine = create_engine(url)
    report = {"database": make_url(url).render_as_string(hide_password=True),
              "status": "", "rows": 0, "error": None}
    say(f"database: {report['database']}")
    try:
        if not inspect(engine).has_table(TABLE):
            report["status"] = "absent"
            say(f"{TABLE} does not exist — nothing to purge")
            return report
        with engine.begin() as conn:
            report["rows"] = conn.execute(
                text(f"SELECT COUNT(*) FROM {TABLE} WHERE endpoint = :e"), {"e": ENDPOINT}).scalar_one()
            if dry_run:
                report["status"] = "dry-run"
                say(f"dry run: {report['rows']} rows for endpoint {ENDPOINT!r} would be deleted — nothing written")
                return report
            conn.execute(text(f"DELETE FROM {TABLE} WHERE endpoint = :e"), {"e": ENDPOINT})
        report["status"] = "purged"
        say(f"deleted {report['rows']} rows for endpoint {ENDPOINT!r}")
        return report
    except Exception as exc:  # noqa: BLE001
        report["status"], report["error"] = "failed", str(exc)
        say(f"FAILED — {exc}")
        return report
    finally:
        engine.dispose()


def main() -> int:
    load_dotenv(BACKEND_DIR / ".env")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = ap.add_mutually_exclusive_group()
    target.add_argument("--db", type=Path, help="SQLite file")
    target.add_argument("--url", help="SQLAlchemy URL (default: $DATABASE_URL, else backend/cache.db)")
    ap.add_argument("--dry-run", action="store_true", help="count the rows, delete nothing")
    args = ap.parse_args()
    if args.db is not None and not args.db.exists():
        print(f"SQLite file not found: {args.db}")
        return 1
    report = purge(args.db or args.url, dry_run=args.dry_run)
    print("\nRESULT:", report["status"])
    return 0 if report["status"] != "failed" else 1


if __name__ == "__main__":
    sys.exit(main())
