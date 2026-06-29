import json
import time as _time
import httpx

DETAILS_URL = "http://localhost:8000/v1/equipment/details"
REVIEW_URL = "http://localhost:8000/v1/equipment/review"

details_payload = {"company": "POC", "model": "Octal MIPS", "category": "helmets"}

print(f"POST {DETAILS_URL}")
print(f"Body: {json.dumps(details_payload)}\n")

resp = httpx.post(DETAILS_URL, json=details_payload, timeout=180)
print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
print()

assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"

data = resp.json()
assert data["company"] == details_payload["company"], "company mismatch"
assert data["model"] == details_payload["model"], "model mismatch"
assert data["category"] == "helmets", f"Expected category 'helmets', got {data['category']!r}"
assert isinstance(data["components"], list), "'components' must be a list"
assert len(data["components"]) > 0, "Expected at least one category"
assert isinstance(data.get("description"), dict) and data["description"], \
    f"Expected non-empty description dict, got: {data.get('description')!r}"

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

assert "photos" in data and isinstance(data["photos"], list), "'photos' must be a list"
for p in data["photos"]:
    assert isinstance(p, str) and p.startswith("http"), f"invalid photo URL: {p!r}"

# Hard constraint: no offer/buy links anywhere in the response
blob = json.dumps(data).lower()
for banned in ["allegro.pl", "olx.pl", "ceneo.pl", "decathlon.pl", "/oferta/", "/offer"]:
    assert banned not in blob, f"Found forbidden offer reference {banned!r} in equipment details"

print(f"OK -- {len(data['components'])} categories, {len(data['photos'])} photos, no offer links")

# Cache hit -- second call must be fast and identical
print("\n-- Cache hit: POST /v1/equipment/details --")
t0 = _time.perf_counter()
resp2 = httpx.post(DETAILS_URL, json=details_payload, timeout=10)
elapsed2 = _time.perf_counter() - t0
assert resp2.status_code == 200, f"Expected 200 on cached call, got {resp2.status_code}"
assert resp2.json() == data, "Cached details response differs from original"
assert elapsed2 < 5.0, f"Details cache hit took {elapsed2:.2f}s -- expected < 5s"
print(f"OK -- details cache hit in {elapsed2:.3f}s")

# Category inference -- omit category, expect it to be inferred
print("\n-- Inference: omit category, expect 'lights' inferred --")
infer_payload = {"company": "Bontrager", "model": "Ion 200 RT front light"}
resp_infer = httpx.post(DETAILS_URL, json=infer_payload, timeout=180)
assert resp_infer.status_code == 200, f"Expected 200, got {resp_infer.status_code}"
infer_data = resp_infer.json()
assert infer_data["category"] == "lights", f"Expected inferred 'lights', got {infer_data['category']!r}"
print(f"OK -- inferred category={infer_data['category']!r}")

# Details: empty model -> 422
print("\n-- Details: empty model -> 422 --")
resp_empty = httpx.post(DETAILS_URL, json={"company": "POC", "model": ""}, timeout=10)
assert resp_empty.status_code == 422, f"Expected 422 for empty model, got {resp_empty.status_code}"
print("OK -- empty model rejected with 422")

# Review: basic 200 + schema
print(f"\n-- Review: POST {REVIEW_URL} --")
review_payload = {"company": "POC", "model": "Octal MIPS"}
resp_review = httpx.post(REVIEW_URL, json=review_payload, timeout=180)
assert resp_review.status_code == 200, f"Expected 200, got {resp_review.status_code}"
review_data = resp_review.json()
assert isinstance(review_data["score"], int) and 0 <= review_data["score"] <= 10, "score must be 0-10 int"
assert isinstance(review_data["explanation"], str) and review_data["explanation"], "explanation must be non-empty"
assert isinstance(review_data["ref"], list), "ref must be a list"
review_blob = json.dumps(review_data).lower()
for banned in ["allegro.pl", "olx.pl", "ceneo.pl", "decathlon.pl"]:
    assert banned not in review_blob, f"Found forbidden offer reference {banned!r} in equipment review"
print(f"OK -- review score={review_data['score']}, refs={len(review_data['ref'])}, no offer links")

# Review: cache hit (only when ref non-empty)
if review_data["ref"]:
    print("\n-- Review: cache hit --")
    t0 = _time.perf_counter()
    resp_review2 = httpx.post(REVIEW_URL, json=review_payload, timeout=10)
    elapsed_r2 = _time.perf_counter() - t0
    assert resp_review2.status_code == 200, f"Expected 200 on cached review, got {resp_review2.status_code}"
    assert resp_review2.json() == review_data, "Cached review response differs from original"
    assert elapsed_r2 < 5.0, f"Review cache hit took {elapsed_r2:.2f}s -- expected < 5s"
    print(f"OK -- review cache hit in {elapsed_r2:.3f}s")
else:
    print("\n-- Review: no refs -> skipping cache-hit check (fallback is not cached) --")

# Review: empty model -> 422
print("\n-- Review: empty model -> 422 --")
resp_review_empty = httpx.post(REVIEW_URL, json={"company": "POC", "model": ""}, timeout=10)
assert resp_review_empty.status_code == 422, f"Expected 422 for empty model, got {resp_review_empty.status_code}"
print("OK -- empty model in review rejected with 422")

# Fallback: unknown item must still return HTTP 200
print("\n-- Fallback: unknown item -> HTTP 200 --")
fallback_payload = {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}
fb_details = httpx.post(DETAILS_URL, json=fallback_payload, timeout=180)
assert fb_details.status_code == 200, f"Expected 200 for unknown item details, got {fb_details.status_code}"
assert isinstance(fb_details.json().get("components"), list), "components must be a list even for unknown item"
fb_review = httpx.post(REVIEW_URL, json=fallback_payload, timeout=180)
assert fb_review.status_code == 200, f"Expected 200 for unknown item review, got {fb_review.status_code}"
assert isinstance(fb_review.json().get("ref"), list), "ref must be a list even for unknown item"
print("OK -- fallback returned HTTP 200 for both endpoints")

print("\nALL EQUIPMENT SMOKE TESTS PASSED")
