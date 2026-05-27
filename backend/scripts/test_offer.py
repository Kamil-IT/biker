import json
import httpx

URL = "http://localhost:8000/v1/bike/offer"
payload = {"company": "INDIANA", "model": "Rock Jr 24"}

print(f"POST {URL}")
print(f"Body: {json.dumps(payload)}\n")

resp = httpx.post(URL, json=payload, timeout=120)

print(json.dumps(resp.json(), indent=2, ensure_ascii=False))
print()

assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

data = resp.json()
assert isinstance(data["offers"], list), "offers must be a list"
assert len(data["offers"]) >= 1, f"expected at least 1 offer, got {len(data['offers'])}"

for offer in data["offers"]:
    assert isinstance(offer["brand"], str) and offer["brand"], "brand must be non-empty string"
    assert isinstance(offer["model"], str) and offer["model"], "model must be non-empty string"
    assert isinstance(offer["price"], str), "price must be string"
    assert isinstance(offer["is_new"], bool), "is_new must be bool"
    assert isinstance(offer["url"], str) and offer["url"], "url must be non-empty string"
    assert isinstance(offer["photos"], list), "photos must be list"
    assert isinstance(offer["source"], str), "source must be string"

print("OK — response status is 200")
