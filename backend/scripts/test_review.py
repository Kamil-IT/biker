import json
import time
import httpx

URL = "http://localhost:8000/v1/bike/review"
payload = {"company": "Canyon", "model": "Grizl CF 7 ESC"}

print(f"POST {URL}")
print(f"Body: {json.dumps(payload)}\n")

resp = httpx.post(URL, json=payload, timeout=120)

print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
print()

assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

data = resp.json()
assert isinstance(data["score"], int), "score must be int"
assert 0 <= data["score"] <= 10, "score must be 0–10"
assert isinstance(data["explanation"], str) and data["explanation"], "explanation must be non-empty string"
assert isinstance(data["ref"], list), "ref must be a list"

# TODO-014: aggregate rating fields
assert "rating" in data, "response must include rating"
assert isinstance(data["rating"], (int, float)), "rating must be a number"
assert 0 <= data["rating"] <= 10, "rating must be 0–10"
assert "sources_used" in data, "response must include sources_used"
assert isinstance(data["sources_used"], int), "sources_used must be int"
assert data["sources_used"] >= 0, "sources_used must be >= 0"

print("OK — response status is 200, rating + sources_used present and in range")

# Second call should hit the cache and return the same rating.
t = time.perf_counter()
resp2 = httpx.post(URL, json=payload, timeout=120)
elapsed2 = time.perf_counter() - t
assert resp2.status_code == 200, f"Expected 200 on 2nd call, got {resp2.status_code}"
data2 = resp2.json()
assert data2["rating"] == data["rating"], "cached rating must match first call"
assert data2["sources_used"] == data["sources_used"], "cached sources_used must match"
print(f"OK — 2nd call consistent (cache) in {elapsed2:.2f}s")
