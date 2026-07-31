"""Validator service (port 9104).

Checks that everything needed to save a bike_detail row is present and sane.
Returns which side to re-fetch so the coordinator can ask for a targeted
re-research instead of redoing the whole bike.

Run:  .venv/Scripts/python.exe -m uvicorn pipeline.validator:app --port 9104
"""
import logging
import re

from fastapi import FastAPI
from pydantic import BaseModel

from pipeline.common import DETAIL_CATEGORIES

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
logger = logging.getLogger("pipeline.validator")

app = FastAPI(title="validator")

# Electric / Powertrain applies to e-bikes only, and Lighting is empty on most
# mountain and gravel bikes (5 of 8 in round 1) — neither counts as missing.
OPTIONAL_CATEGORIES = {"Electric / Powertrain", "Lighting"}
KNOWN_CATEGORIES = {name for name, _ in DETAIL_CATEGORIES}
REQUIRED_CATEGORIES = KNOWN_CATEGORIES - OPTIONAL_CATEGORIES
MIN_CATEGORIES = 3
# A frameset clears the category floor on the strength of its Frame category
# alone, provided that category is genuinely detailed. Set high enough that it
# cannot become a shortcut for a lazy complete-bike record.
FRAMESET_MIN_FRAME_SPECS = 6


def _spec_rows_in(components: list, category: str) -> int:
    """Count spec rows belonging to one category."""
    n = 0
    for c in components:
        if not isinstance(c, dict) or c.get("category") != category:
            continue
        for s in c.get("subcategories", []) or []:
            for e in s.get("elements", []) or []:
                n += len(e.get("specs", []) or [])
    return n

# Placeholder sentinels. "None" is deliberately NOT here: "Suspension: None" on a
# rigid fork and "Front Derailleur: None" on a 1x are truthful specs, and
# rejecting them sends a researcher back to redo correct work.
BAD_VALUE = re.compile(r"^(n/?a|unknown|tbd|null|\?|-)$", re.I)


class Aggregate(BaseModel):
    brand: str
    model: str
    description: str = ""
    components: list = []
    photos: list = []
    source_urls: list = []


@app.get("/health")
def health() -> dict:
    return {"service": "validator"}


@app.post("/validate")
def validate(agg: Aggregate) -> dict:
    problems: list[str] = []
    refetch = None

    if not agg.brand.strip() or not agg.model.strip():
        problems.append("brand/model empty")

    if not isinstance(agg.components, list):
        problems.append("components is not a list")
        return {"valid": False, "problems": problems, "refetch": "details"}

    found = {c.get("category") for c in agg.components if isinstance(c, dict)}
    hit = found & REQUIRED_CATEGORIES
    missing_cats = sorted(REQUIRED_CATEGORIES - found)

    frame_specs = _spec_rows_in(agg.components, "Frame")

    # The >= 3 categories floor is a completeness heuristic for COMPLETE BIKES. A
    # genuine frameset has a frame and nothing else, and bouncing it was actively
    # harmful: it pressured agents into padding the record to get past the gate.
    # Round 5 worked around it by inventing a Wheels category; round 7 by spreading
    # frame-imposed standards (BB92, Boost 12x148) across Drivetrain/Wheels/Saddle.
    # The second is defensible, the first is not — but a validator that makes
    # fabrication the path of least resistance is the wrong validator. A frameset
    # documented in real depth is a complete record OF A FRAMESET.
    frameset_ok = "Frame" in found and frame_specs >= FRAMESET_MIN_FRAME_SPECS
    if len(hit) < MIN_CATEGORIES and not frameset_ok:
        problems.append(
            f"only {len(hit)} of 8 categories present (need >= {MIN_CATEGORIES}, "
            f"or a Frame category with >= {FRAMESET_MIN_FRAME_SPECS} spec rows for a frameset)"
        )
        refetch = "details"

    spec_count = 0
    for c in agg.components:
        if not isinstance(c, dict):
            continue
        for s in c.get("subcategories", []) or []:
            for e in s.get("elements", []) or []:
                if e.get("name") is None or e.get("description") is None:
                    problems.append(f"null name/description in {c.get('category')!r}")
                    refetch = "details"
                for sp in e.get("specs", []) or []:
                    spec_count += 1
                    v = sp.get("value")
                    if v is None or BAD_VALUE.match(str(v).strip()):
                        problems.append(f"placeholder spec value {v!r} in {c.get('category')!r}")
                        refetch = "details"

    if spec_count == 0:
        problems.append("no spec rows at all")
        refetch = "details"

    if not (agg.description or "").strip():
        problems.append("description empty")
        refetch = refetch or "details"

    if not agg.source_urls:
        problems.append("no source_urls — an unsourced spec is a fabricated spec")
        refetch = refetch or "details"

    # Photos are desirable but not required to save a row; flag, do not fail.
    warnings = [] if agg.photos else ["no photos (not fatal)"]

    valid = not problems
    logger.info("validate | %s %s | valid=%s problems=%d", agg.brand, agg.model, valid, len(problems))
    return {
        "valid": valid,
        "problems": problems,
        "warnings": warnings,
        "refetch": refetch,
        "missing_categories": missing_cats,
        "spec_rows": spec_count,
    }
