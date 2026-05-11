import json
import sys
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
