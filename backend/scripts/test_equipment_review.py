"""Focused diagnostic for POST /v1/equipment/review.

Requests the endpoint for several item names (a generic component name like the
one in the UI, plus real product names) and prints the full response so we can
see when/why the review comes back as the 'Review unavailable.' fallback.
"""
import json
import sys
import httpx

URL = "http://localhost:8000/v1/equipment/review"

CASES = [
    {"model": "hydraulic disc brakes"},                 # generic component (UI repro)
    {"company": "Shimano", "model": "Altus RD-M315"},   # real product (new spec-name link)
    {"company": "POC", "model": "Octal MIPS"},          # known-good real product
]

fail = 0
for payload in CASES:
    print(f"\n=== POST {URL} ===")
    print(f"Body: {json.dumps(payload)}")
    resp = httpx.post(URL, json=payload, timeout=180)
    print(f"HTTP {resp.status_code}")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    data = resp.json()
    print(json.dumps(data, indent=2, ensure_ascii=False))

    # schema
    assert isinstance(data["score"], int) and 0 <= data["score"] <= 10, "score must be 0-10"
    assert isinstance(data["explanation"], str) and data["explanation"], "explanation non-empty"
    assert isinstance(data["ref"], list), "ref must be list"

    is_fallback = data["explanation"].strip() == "Review unavailable."
    has_content = data["score"] > 0 or bool(data["ref"]) or not is_fallback
    label = "FALLBACK (review unavailable)" if is_fallback else f"OK score={data['score']} refs={len(data['ref'])}"
    print(f"--> {label}")
    if is_fallback:
        fail += 1

print(f"\n{len(CASES)-fail}/{len(CASES)} cases returned a usable review; {fail} fell back.")
sys.exit(1 if fail else 0)
