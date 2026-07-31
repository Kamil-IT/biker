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
# `pipeline.*` lives under docs/bikes/ since the archive move.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.common import BIKES_FILE, ROUNDS_FILE, STATE  # noqa: E402

# The consolidated index: {brand, model, url} per bike, already de-duplicated and
# already stripped of everything present in the DB at build time. It supersedes
# docs/bike-brands-models.json because it carries an authoritative product URL.
DATASET = Path(__file__).resolve().parents[1] / "bikes_to_save.json"
QUEUE_FILE = STATE / "queue.json"
# Bikes a researcher investigated and correctly rejected (framesets, archive
# listings, non-products). Nothing about them reaches the DB, so without this
# they would be re-picked and re-rejected every round.
SKIPPED_FILE = STATE / "skipped.json"

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
    # NOTE `[\s_-]*` not `\s*` on the two-word forms: round 7 stored "Lyfe EBike
    # Large Ex-Display" because `ex\s*display` cannot match a hyphenated
    # "Ex-Display". A separator class is the difference between catching these
    # and shipping them as product names.
    r":|\bdeal\b|\bused\b|\bsale\b|\d+\s*cm\b|ex[\s_-]*display|ex[\s_-]*demo|\bnos\b|"
    # Round 6 leak: "- Bicycle - R1 - Pebble Discontinued" was stored verbatim and
    # became that bike's display name. A model string that starts with punctuation,
    # says "discontinued", or repeats the word "bicycle" is a listing title, not a
    # model. The model IS the display casing, so a bad one is not cosmetic.
    r"\bdiscontinued\b|\bbicycle\b|^\s*[-–—]|"
    # Round 7: size, colourway and promo qualifiers are listing facets, not model
    # identity — "Hoot Ti - Large - SRAM XO T-Type - Fancy Show Bike!",
    # "Mars 3.0 (VIP only)", "2022 Switch 6 Pro, Large, Norlando Grey, Custom".
    # Two rows differing only by size/colour are also the same bike twice.
    r"\b(?:small|medium|large|x-?large|xl|show\s*bike|vip\s*only|custom|"
    r"pre-?owned|refurbished|display\s*model)\b|!",
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

# --- URL-derived filters (round 6) -----------------------------------------
# The consolidated dataset carries a product URL, and the URL knows things the
# model name does not. Round 6's first pick list showed why: Canfield "BALANCE"
# reads like a complete bike but its URL is `balance-frameset-...`; Esker's
# "Portage Dropout" and "Pre-Order Deposit" are a spare part and a payment;
# Lectric's "...Special Offer" resolves to `special-launch-bundle`. None of
# these are catchable from the model string alone.
URL_REJECT_RX = re.compile(
    # `\bframes[-/]` catches Chromag's `frames-stylus-19` / `frames-sam65` handle
    # convention, which "frameset" alone misses — round 8 spent 3 slots
    # rediscovering that these are frame-only listings.
    # `[-/]frames?$` catches Production Privee's `shan-gt-ti-frame`, which reached
    # round 8's queue and had to be reasoned out by an agent. A handle ENDING in
    # -frame/-frames is a frameset listing; `frameset` and `frames-` both miss it.
    r"(frameset|\bframes[-/]|[-/]frames?$|"
    r"pre-?order|deposit|gift-?card|hanger|dropout|bundle|combo|"
    r"special-launch|warranty|voucher|spare|replacement)",
    re.I,
)
# Wikidata/Wikipedia entries are historical marque records, not product pages —
# they carry no component table, so they cost a full research cycle and yield a
# thin record or a skip. Round 5 produced exactly one good one (an 1868
# boneshaker, via a museum API) out of several attempts. With 3,400+ candidates
# still queued, manufacturer pages are the better use of a slot.
NON_PRODUCT_HOST_RX = re.compile(r"(wikidata\.org|wikipedia\.org|wikimedia\.)", re.I)
# Parts that PART_RX misses because they are not generic bike-part nouns.
# `frankset` = frameset + crankset (Otso). A portmanteau no generic part-noun list
# would contain, and it reads as a model name until you open the page.
PART_EXTRA_RX = re.compile(r"\b(dropout|hanger|deposit|pre-?order|udh|frankset)\b", re.I)

MAX_PER_BRAND = 2

# A skip means "this is not a complete bike" — a settled fact about the product,
# safe to remember forever. It must NEVER mean "I could not fetch the page",
# which is a fact about one attempt. Round 10 skipped the Otso Warakin Stainless,
# a genuine complete bike, purely because the manufacturer runs a client-rendered
# Shogun page — and the skiplist would then have excluded it from every future
# round, turning one bad fetch into permanent data loss. These reasons send a skip
# back to the queue instead of into the skiplist.
RETRYABLE_SKIP_RX = re.compile(
    r"shogun|client[- ]side|client[- ]render|javascript|js[- ]only|no server[- ]render|"
    r"could ?n[o']t fetch|unable to fetch|fetch fail|timeout|timed out|429|5\d\d|"
    r"rate[- ]limit|blocked|no spec (?:table |content )?found|empty page",
    re.I,
)


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _record_skips(q: dict) -> None:
    """Persist skipped bikes so they are never researched twice.

    A skip is a real research result — "this is a frameset", "this is a 2017
    archive listing" — but it writes nothing to the DB, and `pick()` excludes
    only what the DB contains. So every skipped bike came back the next round
    and was re-investigated to the same conclusion: round 7 spent 2 of its 40
    slots re-skipping Chromag Samurai and Crust Geared Wombat, both already
    settled in round 6. Left alone this waste compounds as the skip list grows.
    """
    skips = json.loads(SKIPPED_FILE.read_text(encoding="utf-8")) if SKIPPED_FILE.exists() else {}
    for item in q["items"].values():
        if item["state"] != "skipped":
            continue
        reason = " ".join(str(n) for n in (item.get("notes") or []))[:300]
        # Fetch failures are about the attempt, not the product — let it come back.
        if RETRYABLE_SKIP_RX.search(reason):
            print(f"  retryable skip NOT persisted: {item['brand']} | {item['model']}")
            continue
        k = f"{norm(item['brand'])}|{norm(item['model'])}"
        if k not in skips:
            skips[k] = {"brand": item["brand"], "model": item["model"], "reason": reason}
    SKIPPED_FILE.write_text(json.dumps(skips, indent=2, ensure_ascii=False), encoding="utf-8")


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
        _record_skips(q)
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
    rows = data["bikes"] if isinstance(data, dict) else data
    stored_exact = {(b.strip().lower(), m.strip().lower()) for b, m in conn.execute("select brand,model from bike")}
    stored_by_brand: dict[str, list[str]] = {}
    for b, m in conn.execute("select brand,model from bike"):
        stored_by_brand.setdefault(norm(b), []).append(norm(m))

    already_skipped = (
        set(json.loads(SKIPPED_FILE.read_text(encoding="utf-8")))
        if SKIPPED_FILE.exists() else set()
    )

    picked: list[str] = []
    per_brand: dict[str, int] = {}
    seen_urls: set[str] = set()
    # Two entries whose models differ only by a parenthetical qualifier are one
    # bike: round 7 queued both "Mars 3.0" and "Mars 3.0 (VIP only)" under
    # different URLs, so neither the URL dedupe nor the stored-identity check saw
    # them, and both were researched and stored. Stripping only parentheticals is
    # deliberately conservative — real build variants ("Chilcotin 155 XT" vs
    # "... GX Transmission") differ outside the brackets and stay distinct.
    seen_identity: set[str] = set()
    for r in rows:
        if len(picked) >= n:
            break
        if r.get("confidence") == "low":
            continue
        brand = (r.get("brand") or "").strip()
        model = (r.get("model") or r.get("Model") or "").strip()
        url = (r.get("url") or "").strip()
        if not brand or not model:
            continue
        if MOJIBAKE_RX.search(brand) or MOJIBAKE_RX.search(model):
            continue
        if (PART_RX.search(model) or COMBO_RX.search(model)
                or LISTING_RX.search(model) or BUNDLE_RX.search(model)
                or PART_EXTRA_RX.search(model)):
            continue
        if url and (URL_REJECT_RX.search(url) or NON_PRODUCT_HOST_RX.search(url)):
            continue
        # Two dataset rows sharing one product URL are one bike under two names
        # ("Chromag Samurai" and "Samurai 2020" both resolve to `frames-sam65`).
        if url:
            if url.rstrip("/").lower() in seen_urls:
                continue
            seen_urls.add(url.rstrip("/").lower())
        if (brand.lower(), model.lower()) in stored_exact:
            continue
        # Already investigated and rejected in an earlier round — a settled result.
        if f"{norm(brand)}|{norm(model)}" in already_skipped:
            continue
        identity = f"{norm(brand)}|{norm(re.sub(r'\([^)]*\)', '', model))}"
        if identity in seen_identity:
            continue
        seen_identity.add(identity)
        # No brand_norm/model_norm on this DB, so guard identity by hand:
        # skip when a stored model of the same brand contains this one or vice versa.
        nm = norm(model)
        if any(nm == sm or nm in sm or sm in nm for sm in stored_by_brand.get(norm(brand), [])):
            continue
        if per_brand.get(brand, 0) >= MAX_PER_BRAND:
            continue
        per_brand[brand] = per_brand.get(brand, 0) + 1
        picked.append(f"{brand} | {model} | {url}" if url else f"{brand} | {model}")
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
