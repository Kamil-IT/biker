"""Insert researcher spool files into cache.db via the live ORM writer.

Used by the backfill swarm's `db-writer` agent (see docs/bike-db-backfill-prompt.md).
Re-runnable: an existing fresh row is reported as `skipped_fresh`, never duplicated.

Usage (from backend/, venv active):
    python scripts/backfill_details.py scratch/backfill/inbox/<slug>.json
    python scripts/backfill_details.py --all          # every file in inbox/
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"
sys.path.insert(0, str(BACKEND))

from app.models import init_db  # noqa: E402
from app.repository import get_bike_details, save_bike_details  # noqa: E402
from app.schemas import (  # noqa: E402
    BikeCategory,
    BikeDescription,
    BikeDetailsResponse,
    BikeSubcategory,
    ComponentElement,
    SpecItem,
)

SPOOL = Path(__file__).resolve().parent / "scratch" / "backfill"
INBOX, DONE, FAILED = SPOOL / "inbox", SPOOL / "done", SPOOL / "failed"


def _to_response(doc: dict) -> BikeDetailsResponse:
    return BikeDetailsResponse(
        company=doc["brand"],
        model=doc["model"],
        description=BikeDescription(text=doc.get("description", ""), segments=[], citations=[]),
        components=[
            BikeCategory(
                category=c.get("category", ""),
                subcategories=[
                    BikeSubcategory(
                        subcategory=s.get("subcategory", ""),
                        elements=[
                            ComponentElement(
                                name=e.get("name", ""),
                                description=e.get("description", ""),
                                specs=[
                                    SpecItem(key=sp.get("key", ""), value=sp.get("value", ""))
                                    for sp in e.get("specs", [])
                                ],
                            )
                            for e in s.get("elements", [])
                        ],
                    )
                    for s in c.get("subcategories", [])
                ],
            )
            for c in doc.get("components", [])
        ],
        photos=doc.get("photos", []),
    )


def store_spool(spool_path: str | Path) -> dict:
    """Insert one researcher spool file. Returns the WRITE_ACK payload."""
    path = Path(spool_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    brand, model = doc["brand"], doc["model"]

    if get_bike_details(brand, model) is not None:
        return {"brand": brand, "model": model, "status": "skipped_fresh",
                "verified": True, "db_rows": {}, "error": None}

    save_bike_details(brand, model, _to_response(doc))

    # save_bike_details swallows its own exceptions (logs a warning, rolls back),
    # so a successful return proves nothing — read it back instead.
    check = get_bike_details(brand, model)
    ok = check is not None and bool(check.components)
    return {
        "brand": brand,
        "model": model,
        "status": "stored" if ok else "failed",
        "verified": ok,
        "db_rows": {
            "bike_detail_component": sum(
                len(e.specs) or 1
                for c in (check.components if ok else [])
                for s in c.subcategories
                for e in s.elements
            ),
            "bike_detail_photos": len(check.photos) if ok else 0,
        },
        "error": None if ok else "read-back failed after save_bike_details",
    }


def _slug_move(path: Path, ack: dict) -> None:
    dest_dir = DONE if ack["status"] in ("stored", "skipped_fresh") else FAILED
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(dest_dir / path.name))
    if ack["status"] == "failed":
        (dest_dir / f"{path.stem}.error.txt").write_text(
            ack.get("error") or "unknown error", encoding="utf-8"
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("spool", nargs="*", help="spool JSON file(s) to insert")
    ap.add_argument("--all", action="store_true", help="process every file in inbox/")
    args = ap.parse_args()

    init_db()  # no-op on an existing cache.db

    targets = [Path(p) for p in args.spool]
    if args.all:
        targets += sorted(INBOX.glob("*.json"))
    if not targets:
        ap.error("give a spool path or --all")

    failures = 0
    for path in targets:
        try:
            ack = store_spool(path)
        except Exception as exc:  # malformed spool file
            ack = {"brand": path.stem, "model": "", "status": "failed", "verified": False,
                   "db_rows": {}, "error": f"{type(exc).__name__}: {exc}"}
        if ack["status"] == "failed":
            failures += 1
        _slug_move(path, ack)
        print(json.dumps(ack, ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
