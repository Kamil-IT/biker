"""Merge every bike source into one flat index: [{brand, model, url}, ...].

NOTE: `docs/sources/` has been removed from the working tree (it is still in git
history — `git checkout docs/sources` restores it). Without it this script can only
rebuild from the curated dataset and the pipeline queue, so the counts will be lower
than the shipped bikes_to_save.json. Restore the sources first for a full rebuild.

Sources, in descending order of URL trustworthiness:
  1. pipeline/state/queue.json  — product URLs a browser scout opened and CONFIRMED
     carry a real spec table. Small but verified.
  2. docs/sources/models-shopify.json      — 3188 products straight off brand storefronts
  3. docs/bike-brands-models.json          — 4055 curated rows (the working dataset)
  4. docs/sources/models-specialized.json  — 1873 Specialized SKUs
  5. docs/sources/models-wikidata.json     — 159 encyclopaedic entries (no product page)

Later sources never overwrite an earlier source's URL for the same brand+model, so a
scout-verified URL always wins over a guessed one.

Run:  backend/.venv/Scripts/python.exe docs/bikes/build_bikes_index.py
Out:  docs/bikes/bikes_to_save.json
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # repo root, from docs/bikes/
DOCS = ROOT / "docs"
OUT = Path(__file__).resolve().parent / "bikes_to_save.json"

# Listing artefacts and non-bikes, learned across five backfill rounds.
PART_RX = re.compile(
    r"\b(frames?|frameset|jersey|sock|glove|tee|t-shirt|hoodie|bottle|sticker|gift\s*card|"
    r"tube|tyre|tire|saddle|grip|pedal|helmet|wheelset|fork|shock|spare|tool|"
    r"fender|attachment|mount|strap|stem|seatpost|hub|rim|axle|cage|pump|lock|"
    r"apparel|shirt|bib|jacket|shoe|demos?|samples?|warehouse|refurb|clearance|"
    r"b-stock|open\s*box|bearing|top\s*cap|cable\s*guide|replacement)\b",
    re.I,
)
LISTING_RX = re.compile(r"\bdeal\b|\bex\s*display\b|\bex\s*demo\b|\bnos\b|\d+\s*cm\b", re.I)
BUNDLE_RX = re.compile(r"\b(?:combo|bundle|package)\b", re.I)
YEAR_SUFFIX_RX = re.compile(r"\s*\((?:19|20)\d{2}\)\s*$")


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def clean_model(m: str, brand: str = "") -> str:
    """Normalise a model name for identity purposes.

    Two fixes, both of which otherwise mint duplicates:
      * a trailing '(2027)' that Shopify titles carry
      * a redundant leading brand name — some storefronts title products
        "Bombtrack Hook" and others "Hook", which is the SAME bike. 525 of the
        4,014 rows collided this way.
    """
    m = YEAR_SUFFIX_RX.sub("", (m or "").strip()).strip()
    nb = norm(brand)
    if nb and norm(m).startswith(nb + " "):
        # Strip on the raw string, matching the normalised prefix length in words.
        words = m.split()
        brand_words = len(nb.split())
        stripped = " ".join(words[brand_words:]).strip()
        if stripped:
            m = stripped
    return m


# A bare Wikidata QID leaked in as a model name ("Antonov | Q97204225").
QID_RX = re.compile(r"^Q\d{4,}$", re.I)
# "Slacker & EXT Arma v4" is a frame+shock package, not a complete bike.
COMBO_RX = re.compile(r"&|\+\s*$")


def usable(brand: str, model: str) -> bool:
    if not brand or not model:
        return False
    if not re.search(r"[\x20-\x7e]", model):
        return False
    if QID_RX.match(model.strip()):
        return False
    if COMBO_RX.search(model):
        return False
    if PART_RX.search(model) or LISTING_RX.search(model) or BUNDLE_RX.search(model):
        return False
    return True


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    out: dict[tuple[str, str], dict] = {}
    stats: dict[str, int] = {}

    def add(brand: str, model: str, url: str, source: str) -> None:
        brand = (brand or "").strip()
        model = clean_model(model, brand)
        if not usable(brand, model):
            return
        k = (norm(brand), norm(model))
        if k in out:
            # Fill a missing URL from a lower-priority source, never replace one.
            if not out[k]["url"] and url:
                out[k]["url"] = url
            return
        out[k] = {"brand": brand, "model": model, "url": url or ""}
        stats[source] = stats.get(source, 0) + 1

    # 1. Scout-verified product URLs (highest trust)
    q = ROOT / "backend" / "pipeline" / "state" / "queue.json"
    if q.exists():
        for item in load(q)["items"].values():
            h = item.get("hints") or {}
            url = h.get("product_url") or (h.get("spec_urls") or [""])[0]
            add(item["brand"], item["model"], url, "scout-verified")

    # 2. Shopify storefront products
    p = DOCS / "sources" / "models-shopify.json"
    if p.exists():
        for m in load(p).get("models", []):
            add(m.get("brand", ""), m.get("model", ""), m.get("url", ""), "shopify")

    # 3. The curated working dataset
    p = DOCS / "bike-brands-models.json"
    if p.exists():
        for m in load(p).get("models", []):
            add(m.get("brand", ""), m.get("model", ""), m.get("url", ""), "curated")

    # 4. Specialized catalogue
    p = DOCS / "sources" / "models-specialized.json"
    if p.exists():
        d = load(p)
        brand = d.get("brand") or "Specialized"
        for m in d.get("models", []):
            add(brand, m.get("model", ""), m.get("url", ""), "specialized")

    # 5. Wikidata (encyclopaedic; url is a wikidata page, not a product page)
    p = DOCS / "sources" / "models-wikidata.json"
    if p.exists():
        for m in load(p).get("models", []):
            add(m.get("brand") or "", m.get("model", ""), m.get("wikidata_url", ""), "wikidata")

    # Drop anything already backfilled. This DB has no brand_norm/model_norm columns, so
    # match on the same Python-side normalisation the pipeline uses, and additionally
    # treat a stored model that contains (or is contained by) a candidate as the same
    # bike — that is how "Grizl" vs "Grizl CF 7" would otherwise be researched twice.
    import sqlite3

    db = ROOT / "backend" / "cache.db"
    stored_exact: set[tuple[str, str]] = set()
    stored_by_brand: dict[str, list[str]] = {}
    if db.exists():
        conn = sqlite3.connect(db)
        for brand, model in conn.execute(
            "select b.brand, b.model from bike b "
            "where exists (select 1 from bike_detail d where d.bike_id = b.id)"
        ):
            nb, nm = norm(brand), norm(model)
            stored_exact.add((nb, nm))
            stored_by_brand.setdefault(nb, []).append(nm)
        conn.close()

    kept, dropped_exact, dropped_near = [], 0, 0
    for b in out.values():
        nb, nm = norm(b["brand"]), norm(b["model"])
        if (nb, nm) in stored_exact:
            dropped_exact += 1
            continue
        if any(nm == sm or nm in sm or sm in nm for sm in stored_by_brand.get(nb, [])):
            dropped_near += 1
            continue
        kept.append(b)

    bikes = sorted(kept, key=lambda b: (b["brand"].lower(), b["model"].lower()))
    OUT.write_text(json.dumps(bikes, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  already in DB, dropped: {dropped_exact} exact + {dropped_near} near-duplicate")

    with_url = sum(1 for b in bikes if b["url"])
    brands = len({b["brand"].lower() for b in bikes})
    print(f"wrote {OUT.relative_to(ROOT)}")
    print(f"  bikes   : {len(bikes)}")
    print(f"  brands  : {brands}")
    print(f"  with url: {with_url} ({with_url * 100 // max(len(bikes), 1)}%)")
    print(f"  by source (first writer wins): {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
