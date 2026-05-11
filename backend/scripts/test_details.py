import json
import sys
import httpx

URL = "http://localhost:8000/v1/bike/details"
payload = {"company": "Canyon", "model": "Grizl CF 7 ESC"}

print(f"POST {URL}")
print(f"Body: {json.dumps(payload)}\n")

resp = httpx.post(URL, json=payload, timeout=180)

print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
print()

assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

data = resp.json()
assert data["company"] == payload["company"], "company mismatch"
assert data["model"] == payload["model"], "model mismatch"
assert isinstance(data["components"], list), "'components' must be a list"
assert len(data["components"]) > 0, "Expected at least one category"

for cat in data["components"]:
    assert "category" in cat, f"Missing 'category' in {cat}"
    assert "subcategories" in cat, f"Missing 'subcategories' in {cat}"
    for sub in cat["subcategories"]:
        assert "subcategory" in sub, f"Missing 'subcategory' in {sub}"
        assert "elements" in sub, f"Missing 'elements' in {sub}"
        for elem in sub["elements"]:
            assert "name" in elem, f"Missing 'name' in {elem}"
            assert "specs" in elem, f"Missing 'specs' in {elem}"
            for spec in elem["specs"]:
                assert "key" in spec, f"Missing 'key' in spec {spec}"
                assert "value" in spec, f"Missing 'value' in spec {spec}"

print(f"OK — {len(data['components'])} categories returned")
