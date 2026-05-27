import json
import time as _time
import httpx

URL = "http://localhost:8000/v1/bike/search"
payload = {"search": "comfortable bike for daily 10 km city commute, mostly paved roads"}

print(f"POST {URL}")
print(f"Body: {json.dumps(payload)}\n")

resp = httpx.post(URL, json=payload, timeout=120)

print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
print()

assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
print("OK — response status is 200")

# Smoke test: /v1/bike/details description field
DETAILS_URL = "http://localhost:8000/v1/bike/details"
details_payload = {"company": "Canyon", "model": "Grizl CF 7 ESC"}

print(f"\nPOST {DETAILS_URL}")
print(f"Body: {json.dumps(details_payload)}\n")

details_resp = httpx.post(DETAILS_URL, json=details_payload, timeout=120)

assert details_resp.status_code == 200, f"Expected 200, got {details_resp.status_code}"
details_data = details_resp.json()
assert isinstance(details_data.get("description"), dict) and details_data["description"], \
    f"Expected non-empty description dict, got: {details_data.get('description')!r}"
print(f"OK — description present")

# Cache hit verification — second calls must be fast and return identical JSON
print("\n── Cache hit test: POST /v1/bike/search (second call should be fast) ──")
t0 = _time.perf_counter()
resp2 = httpx.post(URL, json=payload, timeout=10)
elapsed2 = _time.perf_counter() - t0

assert resp2.status_code == 200, f"Expected 200 on cached call, got {resp2.status_code}"
assert resp2.json() == resp.json(), "Cached response differs from original response"
assert elapsed2 < 5.0, f"Cache hit took {elapsed2:.2f}s — expected < 5s (cache miss?)"
print(f"OK — cache hit returned in {elapsed2:.3f}s")

print("\n── Cache hit test: POST /v1/bike/details (second call should be fast) ──")
t0 = _time.perf_counter()
details_resp2 = httpx.post(DETAILS_URL, json=details_payload, timeout=10)
elapsed_details2 = _time.perf_counter() - t0

assert details_resp2.status_code == 200, f"Expected 200 on cached details call, got {details_resp2.status_code}"
assert details_resp2.json() == details_resp.json(), "Cached details response differs from original"
assert elapsed_details2 < 5.0, f"Details cache hit took {elapsed_details2:.2f}s — expected < 5s"
print(f"OK — details cache hit returned in {elapsed_details2:.3f}s")

# ── Structured search: brand + model only, no free text ──
print("\n── Structured search: brand + model only ──")
struct_payload = {"brand": "Canyon", "model": "Grail CF 7"}
resp_struct = httpx.post(URL, json=struct_payload, timeout=120)
assert resp_struct.status_code == 200, f"Expected 200, got {resp_struct.status_code}"
data_struct = resp_struct.json()
assert data_struct["search"].startswith("Brand: Canyon"), \
    f"Expected enriched query to start with 'Brand: Canyon', got: {data_struct['search']!r}"
assert isinstance(data_struct["bikes"], list) and len(data_struct["bikes"]) > 0, \
    "Expected at least one bike result"
print(f"OK — structured search returned {len(data_struct['bikes'])} bikes")
print(f"     enriched query: {data_struct['search']!r}")

# ── Combined search: free text + structured fields ──
print("\n── Combined search: free text + year + electric flag ──")
combined_payload = {"search": "for trail riding", "year": 2023, "wheel_size": '29"', "is_electric": False}
resp_combined = httpx.post(URL, json=combined_payload, timeout=120)
assert resp_combined.status_code == 200, f"Expected 200, got {resp_combined.status_code}"
data_combined = resp_combined.json()
assert "Year: 2023" in data_combined["search"], \
    f"Expected 'Year: 2023' in enriched query, got: {data_combined['search']!r}"
assert "Electric: no" in data_combined["search"], \
    f"Expected 'Electric: no' in enriched query, got: {data_combined['search']!r}"
print(f"OK — combined search returned {len(data_combined['bikes'])} bikes")
print(f"     enriched query: {data_combined['search']!r}")

# ── Validation: empty payload must return 422 ──
print("\n── Validation: empty payload → 422 ──")
resp_empty = httpx.post(URL, json={}, timeout=10)
assert resp_empty.status_code == 422, \
    f"Expected 422 for empty payload, got {resp_empty.status_code}"
print("OK — empty payload correctly rejected with 422")

# ── Parse endpoint: extract structured fields from free text ──
PARSE_URL = "http://localhost:8000/v1/bike/parse"
print("\n── Parse: extract fields from free text ──")
parse_payload = {"text": "Looking for Trek Marlin 7 2022, 29 inch wheels, with suspension, non-electric"}
resp_parse = httpx.post(PARSE_URL, json=parse_payload, timeout=30)
assert resp_parse.status_code == 200, f"Expected 200, got {resp_parse.status_code}"
data_parse = resp_parse.json()
assert data_parse.get("brand") == "Trek",  f"Expected brand 'Trek', got: {data_parse.get('brand')!r}"
assert data_parse.get("year") == 2022,     f"Expected year 2022, got: {data_parse.get('year')!r}"
assert data_parse.get("has_suspension") is True, f"Expected has_suspension=true, got: {data_parse.get('has_suspension')!r}"
assert data_parse.get("is_electric") is False,   f"Expected is_electric=false, got: {data_parse.get('is_electric')!r}"
print(f"OK — parse returned: {data_parse}")

# ── Parse endpoint: empty text must return 422 ──
print("\n── Parse: empty text → 422 ──")
resp_parse_empty = httpx.post(PARSE_URL, json={"text": ""}, timeout=10)
assert resp_parse_empty.status_code == 422, \
    f"Expected 422 for empty text, got {resp_parse_empty.status_code}"
print("OK — empty text correctly rejected with 422")

# ── Parse endpoint: cache hit ──
print("\n── Parse: cache hit ──")
t0 = _time.perf_counter()
resp_parse2 = httpx.post(PARSE_URL, json=parse_payload, timeout=10)
elapsed_parse2 = _time.perf_counter() - t0
assert resp_parse2.status_code == 200, f"Expected 200, got {resp_parse2.status_code}"
assert resp_parse2.json() == data_parse, "Cached parse response differs from original"
assert elapsed_parse2 < 5.0, f"Parse cache hit took {elapsed_parse2:.2f}s — expected < 5s"
print(f"OK — parse cache hit in {elapsed_parse2:.3f}s")
