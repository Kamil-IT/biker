"""Happy-path smoke test for POST /v1/equipment/review (calls the Anthropic API when uncached).

One known-good real product; fails if the endpoint answers with the
'Review unavailable.' fallback.
"""
import json
import sys

import httpx

URL = "http://localhost:8000/v1/equipment/review"
payload = {"company": "POC", "model": "Octal MIPS"}

print(f"POST {URL}")
print(f"Body: {json.dumps(payload)}")
resp = httpx.post(URL, json=payload, timeout=180)
print(f"HTTP {resp.status_code}")
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"

data = resp.json()
print(json.dumps(data, indent=2, ensure_ascii=False))

assert isinstance(data["score"], int) and 0 <= data["score"] <= 10, "score must be 0-10"
assert isinstance(data["explanation"], str) and data["explanation"], "explanation non-empty"
assert isinstance(data["ref"], list), "ref must be list"
assert data["explanation"].strip() != "Review unavailable.", "got the fallback, not a real review"
blob = json.dumps(data).lower()
for banned in ["allegro.pl", "olx.pl", "ceneo.pl", "decathlon.pl"]:
    assert banned not in blob, f"Found forbidden offer reference {banned!r} in equipment review"

print(f"OK -- review score={data['score']}, refs={len(data['ref'])}, no offer links")
sys.exit(0)
