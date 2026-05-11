import json
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

print("OK — response status is 200")
