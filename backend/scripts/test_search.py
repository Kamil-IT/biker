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
print("\n-- Cache hit test: POST /v1/bike/search (second call should be fast) --")
t0 = _time.perf_counter()
resp2 = httpx.post(URL, json=payload, timeout=10)
elapsed2 = _time.perf_counter() - t0

assert resp2.status_code == 200, f"Expected 200 on cached call, got {resp2.status_code}"
assert resp2.json() == resp.json(), "Cached response differs from original response"
assert elapsed2 < 1.0, f"Cache hit took {elapsed2:.2f}s — expected < 1s (cache miss?)"
print(f"OK — cache hit returned in {elapsed2:.3f}s")

print("\n-- Cache hit test: POST /v1/bike/details (second call should be fast) --")
t0 = _time.perf_counter()
details_resp2 = httpx.post(DETAILS_URL, json=details_payload, timeout=10)
elapsed_details2 = _time.perf_counter() - t0

assert details_resp2.status_code == 200, f"Expected 200 on cached details call, got {details_resp2.status_code}"
assert details_resp2.json() == details_resp.json(), "Cached details response differs from original"
assert elapsed_details2 < 1.0, f"Details cache hit took {elapsed_details2:.2f}s — expected < 1s"
print(f"OK — details cache hit returned in {elapsed_details2:.3f}s")

# Smoke test: /v1/bike/used happy path
USED_URL = "http://localhost:8000/v1/bike/used"
used_payload = {"company": "Trek", "model": "Marlin 5"}

print(f"\nPOST {USED_URL}")
print(f"Body: {json.dumps(used_payload)}\n")

used_resp = httpx.post(USED_URL, json=used_payload, timeout=120)

assert used_resp.status_code == 200, f"Expected 200, got {used_resp.status_code}"
used_data = used_resp.json()
assert isinstance(used_data.get("offers"), list), \
    f"Expected offers to be a list, got: {type(used_data.get('offers'))}"
assert isinstance(used_data.get("info"), str), \
    f"Expected info to be a string, got: {type(used_data.get('info'))}"
print(f"OK — /v1/bike/used returned {len(used_data['offers'])} offers")

# Cache hit for /v1/bike/used
print("\n-- Cache hit test: POST /v1/bike/used (second call should be fast) --")
t0 = _time.perf_counter()
used_resp2 = httpx.post(USED_URL, json=used_payload, timeout=10)
elapsed_used2 = _time.perf_counter() - t0

assert used_resp2.status_code == 200, f"Expected 200 on cached used call, got {used_resp2.status_code}"
assert used_resp2.json() == used_data, "Cached used response differs from original"
assert elapsed_used2 < 10.0, f"Used cache hit took {elapsed_used2:.2f}s — expected < 10s (cache miss?)"
print(f"OK — used cache hit returned in {elapsed_used2:.3f}s")

# Fallback: unknown brand/model must return HTTP 200 with empty or graceful offers list
print("\n-- Fallback test: POST /v1/bike/used with unknown brand/model --")
fallback_payload = {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}
fallback_resp = httpx.post(USED_URL, json=fallback_payload, timeout=120)

assert fallback_resp.status_code == 200, \
    f"Expected 200 for unknown bike, got {fallback_resp.status_code}"
fallback_data = fallback_resp.json()
assert isinstance(fallback_data.get("offers"), list), \
    "Expected offers to be a list even for unknown bike"
print(f"OK — fallback returned HTTP 200 with {len(fallback_data['offers'])} offers")
