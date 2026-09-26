"""Happy-path smoke test for POST /v1/equipment/details (calls the Anthropic API when uncached)."""
import json

import httpx

DETAILS_URL = "http://localhost:8000/v1/equipment/details"

details_payload = {"company": "POC", "model": "Octal MIPS", "category": "helmets"}

print(f"POST {DETAILS_URL}")
print(f"Body: {json.dumps(details_payload)}\n")

resp = httpx.post(DETAILS_URL, json=details_payload, timeout=180)
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"

data = resp.json()
assert data["company"] == details_payload["company"], "company mismatch"
assert data["model"] == details_payload["model"], "model mismatch"
assert data["category"] == "helmets", f"Expected category 'helmets', got {data['category']!r}"
assert isinstance(data.get("description"), dict) and data["description"], \
    f"Expected non-empty description dict, got: {data.get('description')!r}"
assert isinstance(data["components"], list) and len(data["components"]) > 0, "Expected at least one category"

for cat in data["components"]:
    assert "category" in cat and "subcategories" in cat, f"Malformed category: {cat}"
    for sub in cat["subcategories"]:
        assert "subcategory" in sub and "elements" in sub, f"Malformed subcategory: {sub}"
        for elem in sub["elements"]:
            assert "name" in elem and "specs" in elem, f"Malformed element: {elem}"
            for spec in elem["specs"]:
                assert "key" in spec and "value" in spec, f"Malformed spec: {spec}"

assert isinstance(data.get("photos"), list), "'photos' must be a list"
for p in data["photos"]:
    assert isinstance(p, str) and p.startswith("http"), f"invalid photo URL: {p!r}"

# Hard constraint: no offer/buy links anywhere in the response
blob = json.dumps(data).lower()
for banned in ["allegro.pl", "olx.pl", "ceneo.pl", "decathlon.pl", "/oferta/", "/offer"]:
    assert banned not in blob, f"Found forbidden offer reference {banned!r} in equipment details"

print(f"OK -- {len(data['components'])} categories, {len(data['photos'])} photos, no offer links")
