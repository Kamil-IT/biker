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
print("OK -- response status is 200")

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
print(f"OK -- description present")

# Cache hit verification -- second calls must be fast and return identical JSON
print("\n-- Cache hit test: POST /v1/bike/search (second call should be fast) --")
t0 = _time.perf_counter()
resp2 = httpx.post(URL, json=payload, timeout=10)
elapsed2 = _time.perf_counter() - t0

assert resp2.status_code == 200, f"Expected 200 on cached call, got {resp2.status_code}"
assert resp2.json() == resp.json(), "Cached response differs from original response"
assert elapsed2 < 5.0, f"Cache hit took {elapsed2:.2f}s -- expected < 5s (cache miss?)"
print(f"OK -- cache hit returned in {elapsed2:.3f}s")

print("\n-- Cache hit test: POST /v1/bike/details (second call should be fast) --")
t0 = _time.perf_counter()
details_resp2 = httpx.post(DETAILS_URL, json=details_payload, timeout=10)
elapsed_details2 = _time.perf_counter() - t0

assert details_resp2.status_code == 200, f"Expected 200 on cached details call, got {details_resp2.status_code}"
assert details_resp2.json() == details_resp.json(), "Cached details response differs from original"
assert elapsed_details2 < 5.0, f"Details cache hit took {elapsed_details2:.2f}s -- expected < 5s"
print(f"OK -- details cache hit returned in {elapsed_details2:.3f}s")

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
print(f"OK -- /v1/bike/used returned {len(used_data['offers'])} offers")

# Cache hit for /v1/bike/used
print("\n-- Cache hit test: POST /v1/bike/used (second call should be fast) --")
t0 = _time.perf_counter()
used_resp2 = httpx.post(USED_URL, json=used_payload, timeout=10)
elapsed_used2 = _time.perf_counter() - t0

assert used_resp2.status_code == 200, f"Expected 200 on cached used call, got {used_resp2.status_code}"
assert used_resp2.json() == used_data, "Cached used response differs from original"
assert elapsed_used2 < 10.0, f"Used cache hit took {elapsed_used2:.2f}s -- expected < 10s (cache miss?)"
print(f"OK -- used cache hit returned in {elapsed_used2:.3f}s")

# Fallback: unknown brand/model must return HTTP 200 with empty or graceful offers list
print("\n-- Fallback test: POST /v1/bike/used with unknown brand/model --")
fallback_payload = {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}
fallback_resp = httpx.post(USED_URL, json=fallback_payload, timeout=120)

assert fallback_resp.status_code == 200, \
    f"Expected 200 for unknown bike, got {fallback_resp.status_code}"
fallback_data = fallback_resp.json()
assert isinstance(fallback_data.get("offers"), list), \
    "Expected offers to be a list even for unknown bike"
print(f"OK -- fallback returned HTTP 200 with {len(fallback_data['offers'])} offers")

# -- Structured search: brand + model only, no free text --
print("\n-- Structured search: brand + model only --")
struct_payload = {"brand": "Canyon", "model": "Grail CF 7"}
resp_struct = httpx.post(URL, json=struct_payload, timeout=120)
assert resp_struct.status_code == 200, f"Expected 200, got {resp_struct.status_code}"
data_struct = resp_struct.json()
assert data_struct["search"].startswith("Brand: Canyon"), \
    f"Expected enriched query to start with 'Brand: Canyon', got: {data_struct['search']!r}"
assert isinstance(data_struct["bikes"], list) and len(data_struct["bikes"]) > 0, \
    "Expected at least one bike result"
print(f"OK -- structured search returned {len(data_struct['bikes'])} bikes")
print(f"     enriched query: {data_struct['search']!r}")

# -- Combined search: free text + structured fields --
print("\n-- Combined search: free text + year + electric flag --")
combined_payload = {"search": "for trail riding", "year": 2023, "wheel_size": '29"', "is_electric": False}
resp_combined = httpx.post(URL, json=combined_payload, timeout=120)
assert resp_combined.status_code == 200, f"Expected 200, got {resp_combined.status_code}"
data_combined = resp_combined.json()
assert "Year: 2023" in data_combined["search"], \
    f"Expected 'Year: 2023' in enriched query, got: {data_combined['search']!r}"
assert "Electric: no" in data_combined["search"], \
    f"Expected 'Electric: no' in enriched query, got: {data_combined['search']!r}"
print(f"OK -- combined search returned {len(data_combined['bikes'])} bikes")
print(f"     enriched query: {data_combined['search']!r}")

# -- Validation: empty payload must return 422 --
print("\n-- Validation: empty payload -> 422 --")
resp_empty = httpx.post(URL, json={}, timeout=10)
assert resp_empty.status_code == 422, \
    f"Expected 422 for empty payload, got {resp_empty.status_code}"
print("OK -- empty payload correctly rejected with 422")

# -- Parse endpoint: extract structured fields from free text --
PARSE_URL = "http://localhost:8000/v1/bike/parse"
print("\n-- Parse: extract fields from free text --")
parse_payload = {"text": "Looking for Trek Marlin 7 2022, 29 inch wheels, with suspension, non-electric"}
resp_parse = httpx.post(PARSE_URL, json=parse_payload, timeout=30)
assert resp_parse.status_code == 200, f"Expected 200, got {resp_parse.status_code}"
data_parse = resp_parse.json()
assert data_parse.get("brand") == "Trek",  f"Expected brand 'Trek', got: {data_parse.get('brand')!r}"
assert data_parse.get("year") == 2022,     f"Expected year 2022, got: {data_parse.get('year')!r}"
assert data_parse.get("has_suspension") is True, f"Expected has_suspension=true, got: {data_parse.get('has_suspension')!r}"
assert data_parse.get("is_electric") is False,   f"Expected is_electric=false, got: {data_parse.get('is_electric')!r}"
print(f"OK -- parse returned: {data_parse}")

# -- Parse endpoint: empty text must return 422 --
print("\n-- Parse: empty text -> 422 --")
resp_parse_empty = httpx.post(PARSE_URL, json={"text": ""}, timeout=10)
assert resp_parse_empty.status_code == 422, \
    f"Expected 422 for empty text, got {resp_parse_empty.status_code}"
print("OK -- empty text correctly rejected with 422")

# -- Parse endpoint: cache hit --
print("\n-- Parse: cache hit --")
t0 = _time.perf_counter()
resp_parse2 = httpx.post(PARSE_URL, json=parse_payload, timeout=10)
elapsed_parse2 = _time.perf_counter() - t0
assert resp_parse2.status_code == 200, f"Expected 200, got {resp_parse2.status_code}"
assert resp_parse2.json() == data_parse, "Cached parse response differs from original"
assert elapsed_parse2 < 5.0, f"Parse cache hit took {elapsed_parse2:.2f}s — expected < 5s"
print(f"OK — parse cache hit in {elapsed_parse2:.3f}s")

# ── Ceneo offer endpoint ──
print("\n── Ceneo: find offers on ceneo.pl ──")
CENEO_URL = "http://localhost:8000/v1/bike/ceneo"
ceneo_payload = {"company": "INDIANA", "model": "Rock Jr 24"}
resp_ceneo = httpx.post(CENEO_URL, json=ceneo_payload, timeout=120)
assert resp_ceneo.status_code == 200, f"Expected 200, got {resp_ceneo.status_code}"
ceneo_data = resp_ceneo.json()
assert isinstance(ceneo_data["offers"], list), "Expected offers to be a list"
assert len(ceneo_data["offers"]) >= 1, f"Expected at least 1 offer, got {len(ceneo_data['offers'])}"
for offer in ceneo_data["offers"]:
    assert offer["brand"], "offer.brand must be non-empty"
    assert offer["model"], "offer.model must be non-empty"
    assert offer["price"], "offer.price must be non-empty"
    assert isinstance(offer["is_new"], bool), "offer.is_new must be bool"
    assert offer["url"], "offer.url must be non-empty"
    assert isinstance(offer["photos"], list), "offer.photos must be a list"
    assert offer["source"] == "ceneo.pl", f"Expected source 'ceneo.pl', got {offer['source']!r}"
print(f"OK — ceneo returned {len(ceneo_data['offers'])} offer(s)")

# ── Ceneo: cache hit ──
print("\n── Ceneo: cache hit ──")
t0 = _time.perf_counter()
resp_ceneo2 = httpx.post(CENEO_URL, json=ceneo_payload, timeout=10)
elapsed_ceneo2 = _time.perf_counter() - t0
assert resp_ceneo2.status_code == 200, f"Expected 200 on cached ceneo call, got {resp_ceneo2.status_code}"
assert resp_ceneo2.json() == ceneo_data, "Cached ceneo response differs from original"
assert elapsed_ceneo2 < 5.0, f"Ceneo cache hit took {elapsed_ceneo2:.2f}s — expected < 5s"
print(f"OK — ceneo cache hit in {elapsed_ceneo2:.3f}s")

# ── Ceneo: fallback for unknown bike ──
print("\n── Ceneo: fallback for unknown bike ──")
resp_ceneo_fake = httpx.post(CENEO_URL, json={"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=120)
assert resp_ceneo_fake.status_code == 200, f"Expected 200 for fallback, got {resp_ceneo_fake.status_code}"
fallback_data = resp_ceneo_fake.json()
assert isinstance(fallback_data["offers"], list), "Fallback offers must be a list"
print(f"OK — ceneo fallback returned {len(fallback_data['offers'])} offers (expected 0 or empty)")

# ── Decathlon offer endpoint ──
print("\n── Decathlon: find offers on decathlon.pl ──")
DECATHLON_URL = "http://localhost:8000/v1/bike/decathlon"
decathlon_payload = {"company": "Rockrider", "model": "ST 100"}
resp_decathlon = httpx.post(DECATHLON_URL, json=decathlon_payload, timeout=120)
assert resp_decathlon.status_code == 200, f"Expected 200, got {resp_decathlon.status_code}"
decathlon_data = resp_decathlon.json()
assert isinstance(decathlon_data["offers"], list), "Expected offers to be a list"
assert isinstance(decathlon_data["info"], str), "Expected info to be a string"
for offer in decathlon_data["offers"]:
    assert offer["brand"], "offer.brand must be non-empty"
    assert offer["model"], "offer.model must be non-empty"
    assert offer["price"], "offer.price must be non-empty"
    assert isinstance(offer["is_new"], bool), "offer.is_new must be bool"
    assert offer["url"], "offer.url must be non-empty"
    assert isinstance(offer["photos"], list), "offer.photos must be a list"
    assert offer["source"] == "decathlon.pl", f"Expected source 'decathlon.pl', got {offer['source']!r}"
print(f"OK — decathlon returned {len(decathlon_data['offers'])} offer(s)")

# ── Decathlon: cache hit ──
print("\n── Decathlon: cache hit ──")
t0 = _time.perf_counter()
resp_decathlon2 = httpx.post(DECATHLON_URL, json=decathlon_payload, timeout=10)
elapsed_decathlon2 = _time.perf_counter() - t0
assert resp_decathlon2.status_code == 200, f"Expected 200 on cached decathlon call, got {resp_decathlon2.status_code}"
assert resp_decathlon2.json() == decathlon_data, "Cached decathlon response differs from original"
assert elapsed_decathlon2 < 5.0, f"Decathlon cache hit took {elapsed_decathlon2:.2f}s — expected < 5s"
print(f"OK — decathlon cache hit in {elapsed_decathlon2:.3f}s")

# ── Decathlon: fallback for unknown bike ──
print("\n── Decathlon: fallback for unknown bike ──")
resp_decathlon_fake = httpx.post(DECATHLON_URL, json={"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=120)
assert resp_decathlon_fake.status_code == 200, f"Expected 200 for fallback, got {resp_decathlon_fake.status_code}"
fallback_data = resp_decathlon_fake.json()
assert isinstance(fallback_data["offers"], list), "Fallback offers must be a list"
print(f"OK — decathlon fallback returned {len(fallback_data['offers'])} offers (expected 0 or empty)")

# ── [TC-10] Search response schema shape ──
print("\n── [TC-10] Search response schema: bikes have required fields ──")
first_bike = resp.json()["bikes"][0]
assert isinstance(first_bike["brand"], str) and first_bike["brand"], "brand must be non-empty string"
assert isinstance(first_bike["model"], str) and first_bike["model"], "model must be non-empty string"
assert isinstance(first_bike["accessories"], list), "accessories must be list"
assert isinstance(first_bike["match_score"], (int, float)), "match_score must be numeric"
assert 0 <= first_bike["match_score"] <= 10, "match_score must be 0–10"
assert isinstance(first_bike["explanation"], str) and first_bike["explanation"], "explanation must be non-empty string"
print("OK — bike result schema is correct")

# ── [TC-11] Search: is_kids=True structured flag ──
print("\n── [TC-11] Search: is_kids=True flag ──")
kids_payload = {"is_kids": True}
resp_kids = httpx.post(URL, json=kids_payload, timeout=120)
assert resp_kids.status_code == 200, f"Expected 200, got {resp_kids.status_code}"
data_kids = resp_kids.json()
assert "Kids bike: yes" in data_kids["search"], \
    f"Expected 'Kids bike: yes' in enriched query, got: {data_kids['search']!r}"
assert isinstance(data_kids["bikes"], list) and len(data_kids["bikes"]) > 0, "Expected at least one bike"
print(f"OK — kids flag search, enriched query: {data_kids['search']!r}")

# ── [TC-12] Search: invalid year → 422 ──
print("\n── [TC-12] Search: year out of range → 422 ──")
resp_bad_year = httpx.post(URL, json={"year": 1800}, timeout=10)
assert resp_bad_year.status_code == 422, f"Expected 422 for year=1800, got {resp_bad_year.status_code}"
print("OK — out-of-range year correctly rejected with 422")

# ── [TC-12b] Search: new structured filters in enriched query ──
print("\n── [TC-12b] Search: new filter fields (bike_type, price_max, frame_size, etc.) ──")
filters_payload = {
    "bike_type": "Gravel",
    "price_max": 6000,
    "frame_size": "M",
    "rider_height_cm": 178,
    "gender": "Universal",
    "frame_material": "Carbon",
    "brake_type": "Hydraulic Disc",
    "drivetrain": "2x",
    "belt_drive": False,
    "is_electric": True,
    "battery_capacity_wh": 500,
}
resp_filters = httpx.post(URL, json=filters_payload, timeout=120)
assert resp_filters.status_code == 200, f"Expected 200, got {resp_filters.status_code}"
data_filters = resp_filters.json()
eq = data_filters["search"]
for expected in [
    "Type: Gravel", "Max price: 6000 PLN", "Frame size: M", "Rider height: 178 cm",
    "Gender: Universal", "Frame material: Carbon", "Brakes: Hydraulic Disc",
    "Drivetrain: 2x", "Belt drive: no", "Electric: yes", "Battery: 500 Wh",
]:
    assert expected in eq, f"Expected {expected!r} in enriched query, got: {eq!r}"
assert isinstance(data_filters["bikes"], list) and len(data_filters["bikes"]) > 0, "Expected at least one bike"
print(f"OK — new filters enriched query: {eq!r}")

# ── [TC-13] Details: empty company string → 422 ──
print("\n── [TC-13] Details: empty company string → 422 ──")
resp_details_empty = httpx.post(DETAILS_URL, json={"company": "", "model": "Grizl CF 7"}, timeout=10)
assert resp_details_empty.status_code == 422, \
    f"Expected 422 for empty company, got {resp_details_empty.status_code}"
print("OK — empty company correctly rejected with 422")

# ── [TC-14] Review: basic 200 + schema ──
REVIEW_URL = "http://localhost:8000/v1/bike/review"
review_payload = {"company": "Canyon", "model": "Grizl CF 7 ESC"}
print(f"\n── [TC-14] Review: POST {REVIEW_URL} ──")
resp_review = httpx.post(REVIEW_URL, json=review_payload, timeout=120)
assert resp_review.status_code == 200, f"Expected 200, got {resp_review.status_code}"
review_data = resp_review.json()
assert isinstance(review_data["score"], int), "score must be int"
assert 0 <= review_data["score"] <= 10, "score must be 0–10"
assert isinstance(review_data["explanation"], str) and review_data["explanation"], "explanation must be non-empty"
assert isinstance(review_data["ref"], list), "ref must be a list"
print(f"OK — review score={review_data['score']}, refs={len(review_data['ref'])}")

# ── [TC-15] Review: cache hit ──
print("\n── [TC-15] Review: cache hit ──")
t0 = _time.perf_counter()
resp_review2 = httpx.post(REVIEW_URL, json=review_payload, timeout=10)
elapsed_review2 = _time.perf_counter() - t0
assert resp_review2.status_code == 200, f"Expected 200 on cached review, got {resp_review2.status_code}"
assert resp_review2.json() == review_data, "Cached review response differs from original"
assert elapsed_review2 < 5.0, f"Review cache hit took {elapsed_review2:.2f}s — expected < 5s"
print(f"OK — review cache hit in {elapsed_review2:.3f}s")

# ── [TC-16] Review: empty company → 422 ──
print("\n── [TC-16] Review: empty company → 422 ──")
resp_review_empty = httpx.post(REVIEW_URL, json={"company": "", "model": "Grizl"}, timeout=10)
assert resp_review_empty.status_code == 422, \
    f"Expected 422 for empty company, got {resp_review_empty.status_code}"
print("OK — empty company in review correctly rejected with 422")

# ── [TC-17] Offer (allegro): basic 200 + schema ──
OFFER_URL = "http://localhost:8000/v1/bike/offer"
offer_payload = {"company": "Canyon", "model": "Grizl CF 7 ESC"}
print(f"\n── [TC-17] Offer: POST {OFFER_URL} ──")
resp_offer = httpx.post(OFFER_URL, json=offer_payload, timeout=120)
assert resp_offer.status_code == 200, f"Expected 200, got {resp_offer.status_code}"
offer_data = resp_offer.json()
assert isinstance(offer_data["offers"], list), "offers must be a list"
assert isinstance(offer_data["info"], str), "info must be a string"
for o in offer_data["offers"]:
    assert isinstance(o["brand"], str), "offer brand must be string"
    assert isinstance(o["model"], str), "offer model must be string"
    assert isinstance(o["price"], str), "offer price must be string"
    assert isinstance(o["is_new"], bool), "offer is_new must be bool"
    assert isinstance(o["url"], str) and o["url"], "offer url must be non-empty string"
    assert isinstance(o["photos"], list), "offer photos must be list"
print(f"OK — allegro offer returned {len(offer_data['offers'])} offer(s)")

# ── [TC-18] Offer: cache hit ──
print("\n── [TC-18] Offer: cache hit ──")
t0 = _time.perf_counter()
resp_offer2 = httpx.post(OFFER_URL, json=offer_payload, timeout=10)
elapsed_offer2 = _time.perf_counter() - t0
assert resp_offer2.status_code == 200, f"Expected 200 on cached offer, got {resp_offer2.status_code}"
assert resp_offer2.json() == offer_data, "Cached offer response differs from original"
assert elapsed_offer2 < 5.0, f"Offer cache hit took {elapsed_offer2:.2f}s — expected < 5s"
print(f"OK — offer cache hit in {elapsed_offer2:.3f}s")

# ── [TC-19] Offer: empty model → 422 ──
print("\n── [TC-19] Offer: empty model → 422 ──")
resp_offer_empty = httpx.post(OFFER_URL, json={"company": "Canyon", "model": ""}, timeout=10)
assert resp_offer_empty.status_code == 422, \
    f"Expected 422 for empty model, got {resp_offer_empty.status_code}"
print("OK — empty model in offer correctly rejected with 422")
