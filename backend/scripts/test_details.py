"""Integration tests for POST /v1/bike/details — component-search prompt validation.

These are INTEGRATION tests: they hit a LIVE server and make (potentially billed)
Claude calls. Keep the reference-bike set small.

Setup / run:
    cd backend
    .venv\\Scripts\\activate
    uvicorn app.main:app --reload --port 8000     # terminal 1
    python scripts/test_details.py                # terminal 2

What this validates (shape, not exact content — real web data varies):
  * Response conforms to BikeDetailsResponse (company, model, description, components[], photos[]).
  * Component categories are a subset of the 8 expected (Frame .. Accessories), no duplicates,
    every returned category having a non-empty name and well-formed subcategories/elements/specs.
  * No parsing artifacts: no ``` code fences, no leaked raw-JSON wrappers ({...}/[...]) in any text field.
  * Description is a plain string (the BikeDescription.text field), free of fences/JSON wrappers.
  * Photos are valid http(s) URLs.
  * The structurally universal categories (Frame, Drivetrain, Wheels, Brakes) are always
    present — every real bike has them, so a missing one is a pipeline defect, not a data gap.
  * Graceful degradation: an occasionally-empty optional category is fine (skipped, not 502).
  * Invalid input (empty company/model) → 422 validation error, never 502.

Exit code 0 = all passed; 1 = a failure (details printed).
"""

import json
import sys

import httpx

BASE_URL = "http://localhost:8000"
DETAILS_URL = f"{BASE_URL}/v1/bike/details"

# Fixed reference bikes — well-known models with stable, published component specs.
REFERENCE_BIKES = [
    {"company": "Canyon", "model": "Grizl CF 7 ESC"},
    {"company": "Trek", "model": "Marlin 5"},
]

# The 8 component categories the finder iterates (app/bike_details_finder.DETAIL_CATEGORIES).
EXPECTED_CATEGORIES = {
    "Frame",
    "Drivetrain",
    "Brakes",
    "Wheels",
    "Cockpit",
    "Saddle & Seatpost",
    "Lighting",
    "Accessories",
}

# Structurally universal — every real bicycle has these, so their absence is a
# pipeline defect (e.g. a dropped/unparsed response), never a web-data gap.
# Lighting and Accessories are genuinely optional; Cockpit and Saddle & Seatpost
# are frequently folded into other sections by manufacturers' spec sheets.
REQUIRED_CATEGORIES = {"Frame", "Drivetrain", "Wheels", "Brakes"}

# Markers that indicate the model leaked raw JSON / markdown into a text field.
_FENCE_MARKERS = ("```", "~~~")


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def _no_artifacts(value: str, where: str) -> None:
    """A text field must not carry code-fence or raw-JSON-wrapper artifacts."""
    for marker in _FENCE_MARKERS:
        _assert(marker not in value, f"{where}: code-fence artifact {marker!r} leaked into text: {value!r}")
    stripped = value.strip()
    # A field that is itself a JSON object/array string means the parser leaked a wrapper.
    if stripped.startswith(("{", "[")) and stripped.endswith(("}", "]")):
        _assert(False, f"{where}: field looks like a raw JSON wrapper, not clean text: {value!r}")


def validate_bike(bike: dict) -> None:
    print(f"POST {DETAILS_URL}  body={json.dumps(bike)}")
    resp = httpx.post(DETAILS_URL, json=bike, timeout=300)
    _assert(resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}")

    data = resp.json()

    # --- top-level schema -------------------------------------------------
    _assert(data.get("company") == bike["company"], "company mismatch")
    _assert(data.get("model") == bike["model"], "model mismatch")
    _assert(isinstance(data.get("components"), list), "'components' must be a list")
    _assert(isinstance(data.get("photos"), list), "'photos' must be a list")
    _assert("description" in data, "'description' field missing")

    # --- description is a plain string (BikeDescription.text) --------------
    desc = data["description"]
    _assert(isinstance(desc, dict) and "text" in desc, "description must be a BikeDescription object with 'text'")
    desc_text = desc["text"]
    _assert(isinstance(desc_text, str), "description.text must be a string")
    _no_artifacts(desc_text, "description.text")

    # --- component categories: subset of the expected 8, no dupes ---------
    names = [c.get("category", "") for c in data["components"]]
    _assert(all(n for n in names), f"every category must have a non-empty name, got {names}")
    unknown = set(names) - EXPECTED_CATEGORIES
    _assert(not unknown, f"unexpected category name(s): {unknown}")
    _assert(len(names) == len(set(names)), f"duplicate categories returned: {names}")
    _assert(len(names) <= 8, f"more than 8 categories returned: {names}")
    # Graceful degradation: fewer than 8 is acceptable (web-data gaps), but not zero.
    _assert(len(names) >= 1, "expected at least one component category")
    # ...but the structurally universal categories are not a "web-data gap": every
    # real bike has a frame, a drivetrain, wheels and brakes. A silently dropped
    # one of these means the pipeline lost the data, not that the web lacked it.
    missing_required = REQUIRED_CATEGORIES - set(names)
    _assert(
        not missing_required,
        f"missing universal categories: {sorted(missing_required)} (got {names})",
    )
    if len(names) < 8:
        missing = EXPECTED_CATEGORIES - set(names)
        print(f"  note: {len(names)}/8 categories present (gracefully skipped: {sorted(missing)})")

    # --- deep shape + artifact checks -------------------------------------
    for cat in data["components"]:
        cname = cat.get("category", "")
        _no_artifacts(cname, "category.category")
        _assert(isinstance(cat.get("subcategories"), list), f"[{cname}] 'subcategories' must be a list")
        for sub in cat["subcategories"]:
            sname = sub.get("subcategory", "")
            _assert("subcategory" in sub, f"[{cname}] subcategory missing 'subcategory' key")
            _no_artifacts(sname, f"[{cname}] subcategory.subcategory")
            _assert(isinstance(sub.get("elements"), list), f"[{cname}/{sname}] 'elements' must be a list")
            for elem in sub["elements"]:
                ename = elem.get("name", "")
                _assert(isinstance(ename, str) and ename.strip() != "", f"[{cname}/{sname}] element has empty name")
                _no_artifacts(ename, f"[{cname}/{sname}] element.name")
                _no_artifacts(elem.get("description", ""), f"[{cname}/{sname}/{ename}] element.description")
                _assert(isinstance(elem.get("specs"), list), f"[{cname}/{sname}/{ename}] 'specs' must be a list")
                for spec in elem["specs"]:
                    _assert("key" in spec and "value" in spec, f"[{cname}/{sname}/{ename}] spec missing key/value: {spec}")
                    _no_artifacts(str(spec.get("key", "")), f"[{cname}/{sname}/{ename}] spec.key")
                    _no_artifacts(str(spec.get("value", "")), f"[{cname}/{sname}/{ename}] spec.value")

    # --- photos are valid URLs -------------------------------------------
    for p in data["photos"]:
        _assert(isinstance(p, str) and p.startswith(("http://", "https://")), f"invalid photo URL: {p!r}")

    print(f"  OK — {len(names)} categories, {len(data['photos'])} photos, no artifacts")


def validate_invalid_input() -> None:
    """Empty company/model must be rejected with a 422 validation error, never a 502."""
    for bad in ({"company": "", "model": ""}, {"company": "Trek", "model": ""}):
        print(f"POST {DETAILS_URL}  body={json.dumps(bad)}  (expecting 422)")
        resp = httpx.post(DETAILS_URL, json=bad, timeout=30)
        _assert(
            resp.status_code == 422,
            f"empty input should give 422, got {resp.status_code}: {resp.text[:200]}",
        )
        print("  OK — 422 validation error")


def main() -> int:
    failures = 0
    for bike in REFERENCE_BIKES:
        try:
            validate_bike(bike)
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL — {exc}")
        print()

    try:
        validate_invalid_input()
    except AssertionError as exc:
        failures += 1
        print(f"  FAIL — {exc}")
    print()

    if failures:
        print(f"{failures} check group(s) FAILED")
        return 1
    print("All component-prompt checks PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
