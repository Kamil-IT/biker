"""Prepare the next round: refill bikes.txt, reset the queue, log the last round.

Run from backend/:  .venv/Scripts/python.exe pipeline/round_prep.py [batch_size]

Picks bikes not already stored, applies the round-1 selection lessons (skip
framesets/parts, cap per brand, skip near-duplicate identities since this DB has
no brand_norm/model_norm), and carries a build kit into the queue entry when the
dataset row has one.
"""
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# This pipeline was archived to docs/bikes/pipeline/. The app it reads and
# writes (cache.db, app/models.py, app/prompts) still lives in backend/.
BACKEND = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(BACKEND))

from pipeline.common import BIKES_FILE, ROUNDS_FILE, STATE  # noqa: E402

DATASET = BACKEND.parent / "docs" / "bike-brands-models.json"
QUEUE_FILE = STATE / "queue.json"

PART_RX = re.compile(
    r"\b(frame|frameset|jersey|sock|glove|cap|tee|t-shirt|hoodie|bottle|sticker|"
    r"gift\s*card|tube|tyre|tire|chain|saddle|grip|pedal|helmet|wheelset|wheel|"
    r"fork|shock|kit|spare|part|tool|rack|fender|bag|attachment|mount|strap|bar|"
    r"stem|seatpost|hub|rim|axle|cage|light|pump|lock|apparel|shirt|short|bib|"
    r"jacket|shoe|demos?|samples?|warehouse|refurb|clearance|b-stock|open\s*box)\b",
    re.I,
)
# Listing artefacts rather than models: "Warehouse Deal: Wythe", "Ex Demo 54cm"
LISTING_RX = re.compile(
    r":|\bdeal\b|\bused\b|\bsale\b|\d+\s*cm\b|ex\s*display|ex\s*demo|\bnos\b",
    re.I,
)
COMBO_RX = re.compile(r"&|\+\s*$")
# Bundle/combo listings are the SAME physical bike as their base model, sold with
# luggage or accessories — Priority "600ADX Adventure Bundle" vs "600ADX", Engwe
# "Engine X Combo" vs "Engine X", Heybike "ALPHA-Combo" vs "ALPHA". Lectric adds
# an "eTrike" suffix to the same product. Storing both mints a duplicate identity,
# and this DB has no brand_norm/model_norm to catch it.
BUNDLE_RX = re.compile(r"\b(?:combo|bundle|package|etrike|w/|with)\b|[-\s]combo\b", re.I)
# Any non-ASCII in a brand or model is far more often a mojibake artefact of
# the source dataset than a real character - and it becomes display casing.
MOJIBAKE_RX = re.compile(r"[^ -~]")
MAX_PER_BRAND = 2


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def log_round(conn: sqlite3.Connection) -> dict:
    """Snapshot DB counts and append to rounds.json."""
    counts = {
        t: conn.execute(f"select count(*) from {t}").fetchone()[0]
        for t in ("bike", "bike_detail", "bike_detail_component", "bike_detail_photos")
    }
    rounds = json.loads(ROUNDS_FILE.read_text(encoding="utf-8")) if ROUNDS_FILE.exists() else []

    outcome = {}
    if QUEUE_FILE.exists():
        q = json.loads(QUEUE_FILE.read_text(encoding="utf-8"))
        for item in q["items"].values():
            outcome[item["state"]] = outcome.get(item["state"], 0) + 1
        # photo quality is the round-2 thing we are actually testing
        photo_counts = [len((i["photos"] or {}).get("photos", [])) for i in q["items"].values() if i["photos"]]
        if photo_counts:
            outcome["photos_total"] = sum(photo_counts)
            outcome["photos_zero"] = sum(1 for n in photo_counts if n == 0)
            outcome["photos_ge4"] = sum(1 for n in photo_counts if n >= 4)

    entry = {
        "round": len(rounds) + 1,
        "finished": datetime.now(timezone.utc).isoformat(),
        "db": counts,
        "outcome": outcome,
    }
    if rounds:
        prev = rounds[-1]["db"]
        entry["delta"] = {k: counts[k] - prev.get(k, 0) for k in counts}
    rounds.append(entry)
    ROUNDS_FILE.write_text(json.dumps(rounds, indent=2), encoding="utf-8")
    return entry


def pick(conn: sqlite3.Connection, n: int) -> list[str]:
    data = json.loads(DATASET.read_text(encoding="utf-8"))
    stored_exact = {(b.strip().lower(), m.strip().lower()) for b, m in conn.execute("select brand,model from bike")}
    stored_by_brand: dict[str, list[str]] = {}
    for b, m in conn.execute("select brand,model from bike"):
        stored_by_brand.setdefault(norm(b), []).append(norm(m))

    picked: list[str] = []
    per_brand: dict[str, int] = {}
    for r in data["models"]:
        if len(picked) >= n:
            break
        if r.get("confidence") == "low":
            continue
        brand, model = (r.get("brand") or "").strip(), (r.get("model") or "").strip()
        if not brand or not model:
            continue
        if MOJIBAKE_RX.search(brand) or MOJIBAKE_RX.search(model):
            continue
        if (PART_RX.search(model) or COMBO_RX.search(model)
                or LISTING_RX.search(model) or BUNDLE_RX.search(model)):
            continue
        if (brand.lower(), model.lower()) in stored_exact:
            continue
        # No brand_norm/model_norm on this DB, so guard identity by hand:
        # skip when a stored model of the same brand contains this one or vice versa.
        nm = norm(model)
        if any(nm == sm or nm in sm or sm in nm for sm in stored_by_brand.get(norm(brand), [])):
            continue
        if per_brand.get(brand, 0) >= MAX_PER_BRAND:
            continue
        per_brand[brand] = per_brand.get(brand, 0) + 1
        picked.append(f"{brand} | {model}")
    return picked


def main() -> int:
    batch = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    conn = sqlite3.connect(BACKEND / "cache.db")

    entry = log_round(conn)
    print(f"round {entry['round'] - 1} closed: db={entry['db']} delta={entry.get('delta')}"
          f" outcome={entry['outcome']}")

    bikes = pick(conn, batch)
    if not bikes:
        print("NO BIKES LEFT — dataset exhausted for the current filters.")
        return 2

    BIKES_FILE.write_text(
        "# brand | model — regenerated by round_prep.py\n" + "\n".join(bikes) + "\n",
        encoding="utf-8",
    )
    QUEUE_FILE.unlink(missing_ok=True)
    print(f"\nnext round: {len(bikes)} bikes")
    for b in bikes:
        print("  ", b)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
