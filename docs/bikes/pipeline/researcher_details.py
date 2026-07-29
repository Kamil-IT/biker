"""Researcher 1 — bike_detail + bike_detail_component (port 9102).

Mirrors app/bike_details_finder.py: one focused search per component category,
same 8 categories, same per-category system prompts, same extract_json parsing
and the same tolerant _parse_* coercion. The difference is where the LLM call
happens — this service hands out a work order and an agent (running on the
Claude Code subscription, no API key) performs the search and posts back raw
text. Parsing stays here so it is deterministic and testable.

Run:  .venv/Scripts/python.exe -m uvicorn pipeline.researcher_details:app --port 9102
"""
import logging

from fastapi import FastAPI
from pydantic import BaseModel

from pipeline.common import (
    BUILD_KIT_RULE,
    DETAIL_CATEGORIES,
    EXTRA_SUBCATEGORIES_RULE,
    prompt_path,
    SHOPIFY_PITFALLS,
    SIBLING_RULE,
    SOURCE_LADDER,
)
from app.json_extract import extract_json
from app.schemas import BikeCategory, BikeSubcategory, ComponentElement, SpecItem

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("pipeline.researcher_details")

app = FastAPI(title="researcher-details")


# --- parsing, lifted from bike_details_finder so behaviour matches exactly ---

def _parse_spec(raw: object, idx: int) -> SpecItem:
    if not isinstance(raw, dict):
        logger.error("spec[%d] is not a dict: %r", idx, raw)
        return SpecItem(key="", value="")
    return SpecItem(key=str(raw.get("key", "")), value=str(raw.get("value", "")))


def _parse_element(raw: object, idx: int) -> ComponentElement:
    if not isinstance(raw, dict):
        logger.error("element[%d] is not a dict: %r", idx, raw)
        return ComponentElement(name="", description="", specs=[])
    return ComponentElement(
        name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        specs=[_parse_spec(s, i) for i, s in enumerate(raw.get("specs", []) or [])],
    )


def _parse_subcategory(raw: object, idx: int) -> BikeSubcategory:
    if not isinstance(raw, dict):
        logger.error("subcategory[%d] is not a dict: %r", idx, raw)
        return BikeSubcategory(subcategory="", elements=[])
    return BikeSubcategory(
        subcategory=str(raw.get("subcategory", "")),
        elements=[_parse_element(e, i) for i, e in enumerate(raw.get("elements", []) or [])],
    )


def _parse_category(raw: object, idx: int) -> BikeCategory:
    if not isinstance(raw, dict):
        logger.error("category[%d] is not a dict: %r", idx, raw)
        return BikeCategory(category="", subcategories=[])
    return BikeCategory(
        category=str(raw.get("category", "")),
        subcategories=[_parse_subcategory(s, i) for i, s in enumerate(raw.get("subcategories", []) or [])],
    )


class RawSubmission(BaseModel):
    brand: str
    model: str
    # Two accepted shapes, because round 1 showed the per-category one fights the
    # efficient method:
    #   raw  = {category_slug: raw model output}  — one search per category
    #   blob = raw text holding the WHOLE bike as a JSON array of categories
    # `blob` is the natural output of "read one manufacturer spec table, answer
    # every category from it", which is the method that actually worked.
    raw: dict[str, str] = {}
    blob: str = ""
    description: str = ""
    source_urls: list[str] = []


@app.get("/health")
def health() -> dict:
    return {"service": "researcher_details", "categories": len(DETAIL_CATEGORIES)}


@app.get("/task")
def task(brand: str, model: str, missing: str = "") -> dict:
    """Work order: one search instruction per category, with its system prompt.

    `missing` optionally narrows the order to specific category slugs, so a
    re-fetch costs one category rather than all eight.
    """
    wanted = {s.strip() for s in missing.split(",") if s.strip()}
    orders = []
    for category_name, slug in DETAIL_CATEGORIES:
        if wanted and slug not in wanted:
            continue
        prompt_file = prompt_path(f"bike_details_{slug}.md")
        orders.append({
            "category": category_name,
            "slug": slug,
            "system_prompt_file": str(prompt_file),
            "system_prompt": prompt_file.read_text(encoding="utf-8") if prompt_file.exists() else "",
            "user_message": f"Search for the {category_name} specifications for the {brand} {model} bicycle.",
        })
    return {
        "brand": brand,
        "model": model,
        "preferred_method": (
            "Find ONE good specification table and answer every category from it. "
            "Post the whole-bike JSON array as `blob` to /submit. Only fall back to "
            "per-category searching for categories that table does not cover, posting "
            "those under `raw` keyed by slug. Both shapes may be sent together."
        ),
        "source_ladder": SOURCE_LADDER,
        "shopify_pitfalls": SHOPIFY_PITFALLS,
        "build_kit_rule": BUILD_KIT_RULE,
        "extra_subcategories_rule": EXTRA_SUBCATEGORIES_RULE,
        "sibling_rule": SIBLING_RULE,
        "rules": [
            'Unknown value => "" — never null, "N/A", "unknown" or "TBD".',
            '"None" IS allowed when truthful (Suspension: None on a rigid fork; '
            'Front Derailleur: None on a 1x). It is a real spec, not a placeholder.',
            "Never invent a component. If the bike lacks a part, omit that subcategory.",
            "Cockpit: give Handlebar and Stem as SEPARATE subcategories. Use Bar Tape for "
            "drop bars and Grips for flat bars — do not force tape onto a flat-bar bike.",
            "Accessories: the Tool subcategory is OPTIONAL and usually absent — omit it "
            "unless the manufacturer actually publishes a tool spec.",
            "Electric / Powertrain applies to e-bikes only; return [] for a non-electric bike.",
            "Raw text with narration or code fences is fine — this service extracts the JSON.",
        ],
        "orders": orders,
        "submit_to": "/submit",
    }


def _collect(data: object, sink: list[BikeCategory]) -> None:
    if isinstance(data, dict):
        cat = _parse_category(data, 0)
        if cat.category:
            sink.append(cat)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            cat = _parse_category(item, i)
            if cat.category:
                sink.append(cat)


@app.post("/submit")
def submit(sub: RawSubmission) -> dict:
    categories: list[BikeCategory] = []
    empty: list[str] = []

    # Whole-bike blob: one spec table read once, all categories at once.
    if sub.blob:
        data = extract_json(sub.blob)
        if data is None:
            logger.error("blob contained no JSON | raw=%r", sub.blob[:300])
            empty.append("blob")
        else:
            _collect(data, categories)

    for _, slug in DETAIL_CATEGORIES:
        raw = sub.raw.get(slug)
        if not raw:
            continue
        data = extract_json(raw)
        if data is None:
            logger.error("category=%r no JSON found | raw=%r", slug, raw[:300])
            empty.append(slug)
            continue
        before = len(categories)
        _collect(data, categories)
        if len(categories) == before:
            empty.append(slug)

    payload = {
        "description": sub.description,
        "components": [c.model_dump() for c in categories],
        "source_urls": sub.source_urls,
        "categories_found": len(categories),
        "unparseable_slugs": empty,
    }
    logger.info("parsed | %s %s | categories=%d unparseable=%s",
                sub.brand, sub.model, len(categories), empty)
    return {"ok": True, "payload": payload}
