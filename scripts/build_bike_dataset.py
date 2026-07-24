"""Build docs/bike-brands-models.json from the raw collections in docs/sources/.

Merges the four per-source files, then normalises the model rows:
  1. drop rows whose model name is a bare Wikidata QID
  2. strip a redundant brand prefix ("Bombtrack Arise" -> "Arise")
  3. lift a trailing/embedded year out of the title into the `year` field
  4. cut promotional bundle suffixes ("... + FREE Cargo Package")
  5. drop component/apparel rows that leaked past the collector's filter
  6. collapse colour/spec variants that share a common base title
  7. re-deduplicate on (brand, model, source)

Re-runnable: python scripts/build_bike_dataset.py
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "docs", "sources")
OUT = os.path.join(ROOT, "docs", "bike-brands-models.json")
RETRIEVED = "2026-07-23"

SEPARATORS = " -–—|:·,"

# product_type values that positively identify a complete bike or frameset
BIKE_TYPE = re.compile(
    r"(bike|bicycle|cycle|trike|frame|fork|tandem|ebike|e-bike|velo|rower)", re.I
)
# titles/types that identify a part, accessory or garment
PART = re.compile(
    r"(seat ?post|derailleur|hanger|\bstems?\b|handlebar|\bgrips?\b|saddle|\btyres?\b"
    r"|\btires?\b|wheel ?set|\bcassette|crankset|\bcrank\b|headset|bottom bracket"
    r"|\brotors?\b|\bhubs?\b|\bspokes?\b|fender|mudguard|bottle|\bcages?\b|\bpumps?\b"
    r"|\btools?\b|\bjersey|\bgloves?\b|\bhelmets?\b|\bshoes?\b|\bsocks?\b|t-?shirt"
    r"|\bbags?\b|pannier|\blocks?\b|\bpedals?\b|bearing|\bbolts?\b|\bcables?\b"
    r"|\bstickers?\b|decal|gift card|\bchainring|\bshifter|\bbrake pad)", re.I
)
# frameset kits: contain part words but ARE a named model - keep, flag low confidence
FRAMESET = re.compile(r"(frame\s*(set|\s*[&+,]|/)|frameset|frame\s*\+\s*fork)", re.I)
YEAR = re.compile(r"[\(\[]\s*((?:19|20)\d{2})\s*[\)\]]|(?:^|\s)((?:19|20)\d{2})\s*$")
QID = re.compile(r"^Q\d+$")
BUNDLE = re.compile(r"\s*[+]\s*(free\b|gratis\b).*$", re.I)
REGION_TAG = re.compile(r"\s*\[[A-Z]{2}\]\s*$")
# words too generic to serve as a model name or a variant-collapse base
GENERIC = {
    "bicycle", "bicycles", "bike", "bikes", "e-bike", "ebike", "e-bikes", "ebikes",
    "frame", "frames", "frameset", "framesets", "complete bike", "complete",
    "rower", "velo", "cycle", "cycles",
}


def load(name):
    with open(os.path.join(SRC, name), encoding="utf-8") as f:
        return json.load(f)


def strip_brand_prefix(brand, model):
    """Remove a leading repeat of the brand name, plus any dangling separator."""
    if not brand or not model:
        return model, False
    b = brand.strip().lower()
    m = model.strip()
    candidates = [b]
    # "State Bicycle Co." also appears as "State Bicycle"; try progressively shorter forms
    parts = b.split()
    if len(parts) > 1:
        candidates.append(" ".join(parts[:-1]))
    for cand in candidates:
        if m.lower().startswith(cand + " ") or m.lower() == cand:
            rest = m[len(cand):].lstrip(SEPARATORS).strip()
            # guard: never strip down to nothing or a fragment
            if len(rest) >= 2:
                return rest, True
    return m, False


def lift_year(model):
    """Pull a (YYYY) or trailing YYYY out of the title. Returns (title, year|None)."""
    mt = YEAR.search(model or "")
    if not mt:
        return model, None
    year = mt.group(1) or mt.group(2)
    cleaned = YEAR.sub(" ", model).strip().strip(SEPARATORS).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return (cleaned or model), year


def is_part(title, ptype):
    """True when the row is a component/garment rather than a bike.

    The title wins over product_type: some storefronts file every product under a
    bike-ish type (State Bicycle Co. lists Fizik saddles as product_type "Bicycles"),
    so a bike-ish type cannot clear a part-ish title.
    """
    if FRAMESET.search(f"{title} {ptype or ''}"):
        return False          # frameset kit - a real named model
    if PART.search(title or ""):
        return True
    if ptype and PART.search(ptype) and not BIKE_TYPE.search(ptype):
        return True
    return False


def drop_generic_lead(model):
    """Strip a leading generic segment ('Bicycle - R1 - Pebble' -> 'R1 - Pebble').

    Kinesis titles are 'Kinesis - Bicycle - R1 - Pebble'; once the brand is removed
    the leading 'Bicycle' would otherwise become the variant-collapse base and merge
    every Kinesis model into one row.
    """
    t = (model or "").strip()
    for _ in range(3):
        for sep in (" - ", " – ", " — "):
            if sep in t:
                head, rest = t.split(sep, 1)
                if head.strip().lower() in GENERIC and len(rest.strip()) >= 2:
                    t = rest.strip()
                    break
        else:
            break
    return t


def base_title(model):
    """Title with a trailing ' - <variant>' and/or '(<spec>)' suffix removed."""
    t = re.sub(r"\s*\([^()]*\)\s*$", "", model or "").strip()
    for sep in (" - ", " – ", " — "):
        if sep in t:
            head = t.split(sep)[0].strip()
            # never collapse onto a generic word - it would merge unrelated models
            if len(head) >= 3 and head.lower() not in GENERIC:
                return head
    return t


# --------------------------------------------------------------------- load
bi, sp, sh, wd = (load(f) for f in (
    "brands-bikeindex.json", "models-specialized.json",
    "models-shopify.json", "models-wikidata.json"))

raw = []
for m in sp["models"]:
    raw.append({"brand": "Specialized", "model": m.get("model"), "year": None,
                "url": m.get("url"), "source": "specialized-sitemap",
                "confidence": m.get("confidence", "high"), "ref": m.get("product_id"),
                "product_type": None})
for m in sh["models"]:
    raw.append({"brand": m.get("brand"), "model": m.get("model"), "year": None,
                "url": m.get("url"), "source": "shopify-storefront",
                "confidence": "high",
                "ref": str(m["product_id"]) if m.get("product_id") is not None else None,
                "price": m.get("price"), "currency": m.get("currency"),
                "product_type": m.get("product_type")})
for m in wd["models"]:
    raw.append({"brand": m.get("brand"), "model": m.get("model"), "year": m.get("year"),
                "url": m.get("wikidata_url"), "source": "wikidata", "confidence": "high",
                "ref": m.get("qid"), "country": m.get("country"), "product_type": None})

# ---------------------------------------------------------------- normalise
audit = Counter()
rows = []
for m in raw:
    title = (m.get("model") or "").strip()
    if not title:
        audit["dropped_empty"] += 1
        continue
    if QID.match(title):
        audit["dropped_qid"] += 1
        continue

    raw_title = title

    cut = BUNDLE.sub("", title).strip(SEPARATORS).strip()
    if cut != title and len(cut) >= 3:
        title, _ = cut, audit.update(["bundle_suffix_cut"])

    title, stripped = strip_brand_prefix(m.get("brand"), title)
    if stripped:
        audit["brand_prefix_stripped"] += 1

    lead = drop_generic_lead(title)
    if lead != title:
        title = lead
        audit["generic_lead_dropped"] += 1

    tag = REGION_TAG.sub("", title).strip()
    if tag != title and len(tag) >= 3:
        title = tag
        audit["region_tag_stripped"] += 1

    title, year = lift_year(title)
    if year and not m.get("year"):
        m["year"] = year
        audit["year_lifted"] += 1

    if is_part(title, m.get("product_type")):
        audit["dropped_component"] += 1
        continue

    if FRAMESET.search(f"{title} {m.get('product_type') or ''}"):
        m["confidence"] = "low"

    m["model"] = title
    if raw_title != title:
        m["raw_title"] = raw_title
    rows.append(m)

# ------------------------------------------------- collapse colour variants
groups = defaultdict(list)
for m in rows:
    groups[(( m.get("brand") or "").lower(), base_title(m["model"]).lower(),
            m["source"])].append(m)

collapsed = []
for (_, _, _), members in groups.items():
    if len(members) > 1:
        base = base_title(members[0]["model"])
        # keep the row whose title is already closest to the base
        keep = min(members, key=lambda x: len(x["model"]))
        keep["model"] = base or keep["model"]
        keep["variants"] = len(members)
        # a year lifted off a discarded variant still describes this model
        if not keep.get("year"):
            for other in members:
                if other.get("year"):
                    keep["year"] = other["year"]
                    break
        audit["variants_collapsed"] += len(members) - 1
        collapsed.append(keep)
    else:
        collapsed.append(members[0])

seen, models = set(), []
for m in sorted(collapsed, key=lambda x: ((x.get("brand") or "~").lower(),
                                          x["model"].lower())):
    key = ((m.get("brand") or "").lower(), m["model"].lower(), m["source"])
    if key in seen:
        audit["dropped_duplicate"] += 1
        continue
    seen.add(key)
    m.pop("product_type", None)
    models.append(m)

# ------------------------------------------------------------------ brands
brands = {}


def add_brand(name, **kw):
    if not name or not str(name).strip():
        return
    name = str(name).strip()
    b = brands.setdefault(name.lower(), {
        "name": name, "short_name": None, "company_url": None,
        "sources": [], "model_count": 0})
    for f in ("short_name", "company_url"):
        if kw.get(f) and not b[f]:
            b[f] = kw[f]
    if kw.get("source") and kw["source"] not in b["sources"]:
        b["sources"].append(kw["source"])


for b in bi["brands"]:
    add_brand(b.get("name"), short_name=b.get("short_name"),
              company_url=b.get("company_url"), source="bikeindex")
for m in models:
    add_brand(m.get("brand"), source=m["source"])
for m in models:
    k = (m.get("brand") or "").lower()
    if k in brands:
        brands[k]["model_count"] += 1

brand_list = sorted(brands.values(), key=lambda b: b["name"].lower())

# ------------------------------------------------------------------- write
doc = {
    "schema_version": "1.1",
    "generated": RETRIEVED,
    "description": (
        "Bicycle brands and models aggregated from openly-licensed / publicly-published "
        "sources only. This is NOT a complete catalogue of every bicycle ever made - no "
        "such database exists (bicycles have no VIN-equivalent identifier, and pre-1990 "
        "models survive only as scanned catalogues). Model titles are normalised by "
        "scripts/build_bike_dataset.py; see docs/README-bike-dataset.md."
    ),
    "sources": [
        {"id": "bikeindex", "name": "Bike Index API v3 (manufacturers)",
         "url": "https://bikeindex.org/api/v3/manufacturers",
         "licence": "Software AGPL-3.0; data licence UNSTATED by operator",
         "retrieved": RETRIEVED, "provides": "brands"},
        {"id": "specialized-sitemap", "name": "Specialized public product sitemap (PL locale)",
         "url": "https://media.specialized.com/sitemaps/PL-Product-pl-PLN.xml",
         "licence": "Public sitemap; URLs and model names only - no page content scraped",
         "retrieved": RETRIEVED, "provides": "models"},
        {"id": "shopify-storefront",
         "name": "Shopify storefront /products.json (public, unauthenticated)",
         "url": "https://<brand-domain>/products.json",
         "licence": "Public storefront JSON; titles and identifiers only",
         "retrieved": RETRIEVED, "provides": "models"},
        {"id": "wikidata", "name": "Wikidata SPARQL",
         "url": "https://query.wikidata.org/sparql",
         "licence": "CC0 1.0 Public Domain", "retrieved": RETRIEVED, "provides": "models"},
    ],
    "excluded_sources": [
        {"name": "99 Spokes", "models": 139027,
         "reason": "Terms of Service forbid using the site to build a similar or competitive "
                   "website; robots.txt Disallow for ClaudeBot with Content-Signal "
                   "ai-train=no (EU DSM Art.4 reservation). Licensing via data@99spokes.com "
                   "is the only legitimate route."},
        {"name": "Geometry Geeks", "models": 9000,
         "reason": "ToS explicitly prohibits systematic or automated data collection."},
        {"name": "Bike Insights", "models": None,
         "reason": "ToS forbids obtaining data by means not intentionally made available."},
        {"name": "Bicycle Blue Book", "models": None,
         "reason": "ToS forbids commercial use and comparative analysis intended for "
                   "publication."},
    ],
    "normalisation": dict(sorted(audit.items())),
    "stats": {
        "brands_total": len(brand_list),
        "brands_with_models": sum(1 for b in brand_list if b["model_count"]),
        "models_total": len(models),
        "models_by_source": dict(Counter(m["source"] for m in models)),
        "models_with_year": sum(1 for m in models if m.get("year")),
        "models_low_confidence": sum(1 for m in models if m.get("confidence") == "low"),
    },
    "brands": brand_list,
    "models": models,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2, ensure_ascii=False)
with open(OUT, encoding="utf-8") as f:
    json.load(f)

print("wrote", OUT, os.path.getsize(OUT), "bytes")
print(json.dumps({"normalisation": doc["normalisation"], "stats": doc["stats"]}, indent=2))
