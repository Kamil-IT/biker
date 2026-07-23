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

# Smoke test: /v1/equipment/details returns a component tree + inferred/echoed category
EQUIP_URL = "http://localhost:8000/v1/equipment/details"
equip_payload = {"company": "POC", "model": "Octal MIPS", "category": "helmets"}

print(f"\nPOST {EQUIP_URL}")
print(f"Body: {json.dumps(equip_payload)}\n")

equip_resp = httpx.post(EQUIP_URL, json=equip_payload, timeout=120)
assert equip_resp.status_code == 200, f"Expected 200, got {equip_resp.status_code}"
equip_data = equip_resp.json()
assert equip_data.get("category") == "helmets", \
    f"Expected category 'helmets', got: {equip_data.get('category')!r}"
assert isinstance(equip_data.get("components"), list), "Expected components to be a list"
# Hard constraint: no offer/buy links anywhere in the equipment response
equip_blob = json.dumps(equip_data).lower()
for _banned in ["allegro.pl", "olx.pl", "ceneo.pl", "decathlon.pl"]:
    assert _banned not in equip_blob, f"Found forbidden offer reference {_banned!r} in equipment details"
print(f"OK -- equipment details category={equip_data['category']!r}, no offer links")

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

# ── Follow-up cache: GET /v1/bike/search-cache?query= (pure cache read) ──
SEARCH_CACHE_URL = "http://localhost:8000/v1/bike/search-cache"
print("\n-- Follow-up cache: GET /v1/bike/search-cache?query= (served from cache) --")
enriched_query = resp.json()["search"]
t0 = _time.perf_counter()
fu_resp = httpx.get(SEARCH_CACHE_URL, params={"query": enriched_query}, timeout=10)
elapsed_fu = _time.perf_counter() - t0
assert fu_resp.status_code == 200, f"Expected 200, got {fu_resp.status_code}"
fu_data = fu_resp.json()
assert fu_data["cached"] is True, "Expected cached=True"
assert fu_data["bikes"] == resp.json()["bikes"], "Follow-up bikes differ from original search"
assert elapsed_fu < 3.0, f"Follow-up cache read took {elapsed_fu:.2f}s — expected < 3s (no web/Claude call)"
print(f"OK -- search-cache query hit in {elapsed_fu:.3f}s with {len(fu_data['bikes'])} bikes")

# ── Follow-up cache: lookup-by-attribute (brand) ──
print("\n-- Follow-up cache: GET /v1/bike/search-cache?brand= (lookup by attribute) --")
some_brand = resp.json()["bikes"][0]["brand"]
brand_resp = httpx.get(SEARCH_CACHE_URL, params={"brand": some_brand}, timeout=10)
assert brand_resp.status_code == 200, f"Expected 200, got {brand_resp.status_code}"
brand_data = brand_resp.json()
assert isinstance(brand_data["bikes"], list), "Expected bikes to be a list"
assert all(b["brand"].strip().lower() == some_brand.strip().lower() for b in brand_data["bikes"]), \
    f"All returned bikes must match brand {some_brand!r}"
assert len(brand_data["bikes"]) >= 1, "Expected at least one bike for a brand from the last search"
print(f"OK -- search-cache brand lookup returned {len(brand_data['bikes'])} {some_brand!r} bike(s)")

# ── Follow-up cache: missing params → 422 ──
print("\n-- Follow-up cache: no query/brand → 422 --")
fu_empty = httpx.get(SEARCH_CACHE_URL, timeout=10)
assert fu_empty.status_code == 422, f"Expected 422, got {fu_empty.status_code}"
print("OK -- search-cache with no params correctly rejected with 422")

# ── Follow-up cache: unknown query → 404 ──
print("\n-- Follow-up cache: unknown query → 404 --")
fu_404 = httpx.get(SEARCH_CACHE_URL, params={"query": "no such query ever cached zzz999"}, timeout=10)
assert fu_404.status_code == 404, f"Expected 404, got {fu_404.status_code}"
print("OK -- unknown query correctly returned 404")

# ── Follow-up cache: GET /v1/bike/details-cache (pure cache read) ──
DETAILS_CACHE_URL = "http://localhost:8000/v1/bike/details-cache"
print("\n-- Follow-up cache: GET /v1/bike/details-cache (served from cache) --")
t0 = _time.perf_counter()
dc_resp = httpx.get(DETAILS_CACHE_URL, params={"company": "Canyon", "model": "Grizl CF 7 ESC"}, timeout=10)
elapsed_dc = _time.perf_counter() - t0
assert dc_resp.status_code == 200, f"Expected 200, got {dc_resp.status_code}"
dc_data = dc_resp.json()
assert dc_data["company"] and dc_data["model"], "Expected company/model in cached details"
assert isinstance(dc_data["components"], list), "Expected components list"
assert elapsed_dc < 3.0, f"Details-cache read took {elapsed_dc:.2f}s — expected < 3s (no web/Claude call)"
print(f"OK -- details-cache hit in {elapsed_dc:.3f}s")

# ── Follow-up cache: unknown bike → 404 ──
print("\n-- Follow-up cache: details-cache unknown bike → 404 --")
dc_404 = httpx.get(DETAILS_CACHE_URL, params={"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=10)
assert dc_404.status_code == 404, f"Expected 404, got {dc_404.status_code}"
print("OK -- unknown bike correctly returned 404")

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

# -- Parse endpoint: brand-constraint phrasing (ISSUE-003) --
print("\n-- Parse: brand-constraint phrasing --")
brand_cases = [
    ("Szukam roweru na podróże po wrocławiu na wałach. Mam 185cm wzrostu i waze 100kg. Firma tylko Tesla", "Tesla"),
    ("Chcę rower, marka Trek", "Trek"),
    ("tylko Specialized", "Specialized"),
    ("brand only Canyon", "Canyon"),
    ("Firma tylko TREK", "TREK"),
]
for text, expected_brand in brand_cases:
    resp_bc = httpx.post(PARSE_URL, json={"text": text}, timeout=30)
    assert resp_bc.status_code == 200, f"Expected 200, got {resp_bc.status_code}"
    data_bc = resp_bc.json()
    assert data_bc.get("brand") == expected_brand, \
        f"Expected brand {expected_brand!r} for {text!r}, got: {data_bc.get('brand')!r}"
    print(f"OK -- {text!r} -> brand={data_bc.get('brand')!r}")

# Location names must NOT be extracted as a brand
for text in ["Mam rower w Wrocławiu", "Szukam roweru w Krakowie na walach"]:
    resp_city = httpx.post(PARSE_URL, json={"text": text}, timeout=30)
    assert resp_city.status_code == 200, f"Expected 200, got {resp_city.status_code}"
    assert resp_city.json().get("brand") is None, \
        f"Expected no brand for location text {text!r}, got: {resp_city.json().get('brand')!r}"
    print(f"OK -- {text!r} -> no brand extracted")

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
# Conditional on purpose: the backend only calls set_cached when `offers` is
# non-empty (see CLAUDE.md, "only cache when the result is non-empty"). When
# allegro.pl genuinely has no listing for the bike, TC-17 returns offers: []
# and nothing is cached — so a second call re-runs the ~30 s web search and
# returns different text. Asserting a cache hit unconditionally makes this test
# fail whenever live allegro data is thin, which has nothing to do with caching.
# Do not remove the guard.
print("\n── [TC-18] Offer: cache hit ──")
if offer_data["offers"]:
    t0 = _time.perf_counter()
    resp_offer2 = httpx.post(OFFER_URL, json=offer_payload, timeout=10)
    elapsed_offer2 = _time.perf_counter() - t0
    assert resp_offer2.status_code == 200, f"Expected 200 on cached offer, got {resp_offer2.status_code}"
    assert resp_offer2.json() == offer_data, "Cached offer response differs from original"
    assert elapsed_offer2 < 5.0, f"Offer cache hit took {elapsed_offer2:.2f}s — expected < 5s"
    print(f"OK — offer cache hit in {elapsed_offer2:.3f}s")
else:
    print("SKIP — TC-17 found no allegro offers, so nothing was cached (by design)")

# ── [TC-19] Offer: empty model → 422 ──
print("\n── [TC-19] Offer: empty model → 422 ──")
resp_offer_empty = httpx.post(OFFER_URL, json={"company": "Canyon", "model": ""}, timeout=10)
assert resp_offer_empty.status_code == 422, \
    f"Expected 422 for empty model, got {resp_offer_empty.status_code}"
print("OK — empty model in offer correctly rejected with 422")


# ══════════════════════════════════════════════════════════════════════════
# TODO_009 — DB-first search cascade: brand+model → search_cache, AI fallback
#
# These tests seed their own cache.db fixtures and remove them afterwards, so
# the suite passes on a cold or aged database. Do not make them depend on rows
# that happen to be in cache.db: search_cache has a 24 h TTL, so any test that
# leans on pre-existing seed data silently stops testing the DB path a day
# later and then fails as if TODO_009 had regressed.
# ══════════════════════════════════════════════════════════════════════════
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR / "cache.db"
sys.path.insert(0, str(BACKEND_DIR))
from app.price_parse import parse_price  # noqa: E402 — needs BACKEND_DIR on sys.path

SEARCH_TTL = 24 * 60 * 60
OFFER_ENDPOINTS = ("/v1/bike/offer", "/v1/bike/ceneo", "/v1/bike/decathlon", "/v1/bike/used")


def _db():
    return sqlite3.connect(str(DB_PATH))


def _norm_key(fields: dict) -> str:
    """Mirror cache.py:_normalise() + main.py's field stringification so we can
    address the exact generic-cache row for a /v1/bike/search request."""
    return json.dumps(
        {k: str(v).strip().lower() for k, v in fields.items()},
        sort_keys=True,
        separators=(",", ":"),
    )


def _cache_row_exists(endpoint: str, request_key: str) -> bool:
    conn = _db()
    try:
        return conn.execute(
            "SELECT 1 FROM cache WHERE endpoint = ? AND request = ?",
            (endpoint, request_key),
        ).fetchone() is not None
    finally:
        conn.close()


def _cache_row_delete(endpoint: str, request_key: str) -> None:
    """Drop a generic-cache row this suite owns, so the AI-fallback tests really
    exercise the fallback on every run instead of hitting the cache."""
    conn = _db()
    try:
        conn.execute(
            "DELETE FROM cache WHERE endpoint = ? AND request = ?", (endpoint, request_key)
        )
        conn.commit()
    finally:
        conn.close()


def _bike(brand: str, model: str, note: str) -> dict:
    return {
        "brand": brand, "model": model,
        "accessories": ["TODO-009 fixture"], "match_score": 8.5,
        "explanation": note,
    }


def _seed_search_row(query: str, bikes: list[dict], age_seconds: int = 0) -> None:
    """Insert a search_cache row owned by this suite. `age_seconds` backdates
    time_stored — 0 is fresh, > SEARCH_TTL is stale."""
    stored = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO search_cache (query, bikes, time_stored, ttl) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(query) DO UPDATE SET bikes=excluded.bikes, "
            "time_stored=excluded.time_stored, ttl=excluded.ttl",
            (query, json.dumps(bikes), stored, SEARCH_TTL),
        )
        conn.commit()
    finally:
        conn.close()


def _drop_search_row(query: str) -> None:
    conn = _db()
    try:
        conn.execute("DELETE FROM search_cache WHERE query = ?", (query,))
        conn.commit()
    finally:
        conn.close()


def _offer_key(company: str, model: str) -> str:
    return _norm_key({"company": company, "model": model})


def _seed_offer_rows_if_missing(company: str, model: str, by_endpoint: dict) -> list[str]:
    """Seed offer rows for the price join, but only where none exist yet.

    Offer rows live in the generic `cache` table, which has no TTL, so on a warm
    database the real scraped rows are already there and this is a no-op. On a
    cold database nothing would join and the price gate would pass leniently for
    the wrong reason, so we insert equivalents. Returns the endpoints we created
    — and only those get deleted afterwards, so real data is never touched.
    """
    key = _offer_key(company, model)
    created: list[str] = []
    conn = _db()
    try:
        for endpoint, prices in by_endpoint.items():
            if conn.execute(
                "SELECT 1 FROM cache WHERE endpoint = ? AND request = ?", (endpoint, key)
            ).fetchone() is not None:
                continue
            response = {
                "offers": [
                    {"brand": company, "model": model, "price": p, "is_new": False,
                     "url": f"https://example.invalid/todo-009-fixture/{i}",
                     "photos": [], "source": endpoint.rsplit("/", 1)[-1]}
                    for i, p in enumerate(prices)
                ],
                "info": "TODO-009 test fixture",
            }
            conn.execute(
                "INSERT INTO cache (endpoint, request, response, time_stored) VALUES (?, ?, ?, ?)",
                (endpoint, key, json.dumps(response), datetime.now(timezone.utc).isoformat()),
            )
            created.append(endpoint)
        conn.commit()
    finally:
        conn.close()
    return created


def _drop_offer_rows(company: str, model: str, endpoints: list[str]) -> None:
    if not endpoints:
        return
    key = _offer_key(company, model)
    conn = _db()
    try:
        for endpoint in endpoints:
            conn.execute(
                "DELETE FROM cache WHERE endpoint = ? AND request = ?", (endpoint, key)
            )
        conn.commit()
    finally:
        conn.close()


def _joined_prices(company: str, model: str) -> list[float]:
    """Independent reimplementation of store.find_offer_prices() — reads the
    same rows through the same parser, so the assertion checks the data rather
    than trusting the code under test."""
    key = _offer_key(company, model)
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT response FROM cache WHERE endpoint IN (?, ?, ?, ?) AND request = ?",
            (*OFFER_ENDPOINTS, key),
        ).fetchall()
    finally:
        conn.close()
    prices = []
    for (response,) in rows:
        for offer in json.loads(response).get("offers", []):
            value = parse_price(offer.get("price") or "")
            if value is not None:
                prices.append(value)
    return prices


def _show(label: str, req_body: dict, response) -> dict:
    print(f"{label} request:  {json.dumps(req_body, ensure_ascii=False)}")
    print(f"{label} response: HTTP {response.status_code}")
    print(json.dumps(response.json(), indent=2, ensure_ascii=False))
    return response.json()


def _matches(bike: dict, brand: str, model: str) -> bool:
    return (bike["brand"].strip().lower() == brand.strip().lower()
            and bike["model"].strip().lower() == model.strip().lower())


# Fixture identities. The search_cache query strings are namespaced so they can
# never collide with a real enriched query, and every one is deleted on the way
# out of its test.
FIX_MARLIN_QUERY = "todo-009 fixture: trek marlin 5"
FIX_TALON_QUERY = "todo-009 fixture: giant talon 3"
FIX_STALE_QUERY = "todo-009 fixture: stale row"
# Mirrors the real scraped values for trek/marlin 5 — /v1/bike/offer 2319 zl and
# five OLX listings whose cheapest is 1000 zl. Only inserted if absent.
FIX_MARLIN_OFFERS = {
    "/v1/bike/offer": ["2319 zł"],
    "/v1/bike/used": ["1 000 zł", "1 000 zł", "1 090 zł", "1 599 zł", "2 400 zł"],
}


# ── [TC-20] DB hit: brand+model served straight from search_cache ──
print("\n── [TC-20] DB hit: Trek Marlin 5 served from search_cache (no AI) ──")
tc20_body = {"brand": "Trek", "model": "Marlin 5"}
tc20_key = _norm_key(tc20_body)
_seed_search_row(FIX_MARLIN_QUERY, [_bike("Trek", "Marlin 5", "Seeded by TC-20.")])
try:
    _cache_row_delete("/v1/bike/search", tc20_key)  # the DB path must be reachable
    t0 = _time.perf_counter()
    resp_tc20 = httpx.post(URL, json=tc20_body, timeout=180)
    elapsed_tc20 = _time.perf_counter() - t0
    data_tc20 = _show("[TC-20]", tc20_body, resp_tc20)
    assert resp_tc20.status_code == 200, f"Expected 200, got {resp_tc20.status_code}"
    assert len(data_tc20["bikes"]) >= 1, "Expected at least one bike from the DB hit"
    for b in data_tc20["bikes"]:
        assert _matches(b, "Trek", "Marlin 5"), \
            f"DB hit must return only the requested bike, got {b['brand']!r} {b['model']!r}"
    assert elapsed_tc20 < 5.0, \
        f"DB hit took {elapsed_tc20:.2f}s — expected < 5s (AI pipeline ran?)"
    # Decision 5: the DB-hit path must never call set_cached.
    assert not _cache_row_exists("/v1/bike/search", tc20_key), \
        "Decision 5 violated: a generic `cache` row was written on the DB-hit path"
    print(f"OK — DB hit in {elapsed_tc20:.3f}s, {len(data_tc20['bikes'])} matching bike(s), "
          f"no generic-cache row written")
finally:
    _drop_search_row(FIX_MARLIN_QUERY)


# ── [TC-21] AI fallback: unknown brand+model falls through to the pipeline ──
print("\n── [TC-21] AI fallback: unknown brand+model ──")
tc21_body = {"brand": "Zzyzx", "model": "Nonesuch QQ999"}
tc21_key = _norm_key(tc21_body)
_cache_row_delete("/v1/bike/search", tc21_key)  # force a real fallback each run
resp_tc21 = httpx.post(URL, json=tc21_body, timeout=300)
data_tc21 = _show("[TC-21]", tc21_body, resp_tc21)
assert resp_tc21.status_code == 200, f"Expected 200, got {resp_tc21.status_code}"
assert isinstance(data_tc21["bikes"], list) and len(data_tc21["bikes"]) > 0, \
    "AI fallback must still return bikes"
assert not any(_matches(b, "Zzyzx", "Nonesuch QQ999") for b in data_tc21["bikes"]), \
    "The nonsense bike is in no cache — it must not appear in the result"
# The AI path *does* warm the generic cache (unlike the DB path).
assert _cache_row_exists("/v1/bike/search", tc21_key), \
    "AI-fallback path should have written a generic-cache row"
print(f"OK — AI fallback returned {len(data_tc21['bikes'])} bikes and warmed the cache")


# ── [TC-22] Stale search_cache row is not served — request falls through to AI ──
print("\n── [TC-22] Stale search_cache row falls through to AI ──")
STALE_BRAND, STALE_MODEL = "StaleBrand", "OldModel X"
tc22_body = {"brand": STALE_BRAND, "model": STALE_MODEL}
tc22_key = _norm_key(tc22_body)
_seed_search_row(
    FIX_STALE_QUERY,
    [_bike(STALE_BRAND, STALE_MODEL, "Seeded by TC-22, deliberately expired.")],
    age_seconds=48 * 60 * 60,
)
print("     seeded a search_cache row aged 48 h against a 24 h TTL")
try:
    _cache_row_delete("/v1/bike/search", tc22_key)  # force a real fallback each run
    resp_tc22 = httpx.post(URL, json=tc22_body, timeout=300)
    data_tc22 = _show("[TC-22]", tc22_body, resp_tc22)
    assert resp_tc22.status_code == 200, f"Expected 200, got {resp_tc22.status_code}"
    assert not any(_matches(b, STALE_BRAND, STALE_MODEL) for b in data_tc22["bikes"]), \
        "A stale search_cache row must not be served — it leaked into the response"
    assert len(data_tc22["bikes"]) > 0, "Fallback must still return bikes"
    print(f"OK — stale row ignored, AI fallback returned {len(data_tc22['bikes'])} bikes")
finally:
    _drop_search_row(FIX_STALE_QUERY)
    _cache_row_delete("/v1/bike/search", tc22_key)


# ── [TC-23] price_max gates the DB hit via the offer-cache join ──
# The cheapest parseable price across all four offer endpoints decides (decision
# 4), so the cutover for trek/marlin 5 sits at its cheapest OLX listing, 1000.
_tc23_created = _seed_offer_rows_if_missing("Trek", "Marlin 5", FIX_MARLIN_OFFERS)
if _tc23_created:
    print(f"     seeded offer rows for the join: {', '.join(_tc23_created)}")
try:
    _tc23_prices = _joined_prices("Trek", "Marlin 5")
    print(f"     joined offer prices for Trek/Marlin 5: {sorted(_tc23_prices)}")
    assert _tc23_prices, "The price join found nothing — TC-23 would pass leniently and prove nothing"
    assert min(_tc23_prices) == 1000.0, \
        f"Expected cheapest joined price 1000.0, got {min(_tc23_prices)}"

    print("\n── [TC-23a] price_max=2000 ≥ cheapest 1000 → DB hit kept ──")
    tc23a_body = {"brand": "Trek", "model": "Marlin 5", "price_max": 2000}
    tc23a_key = _norm_key(tc23a_body)
    _seed_search_row(FIX_MARLIN_QUERY, [_bike("Trek", "Marlin 5", "Seeded by TC-23.")])
    try:
        _cache_row_delete("/v1/bike/search", tc23a_key)
        t0 = _time.perf_counter()
        resp_tc23a = httpx.post(URL, json=tc23a_body, timeout=180)
        elapsed_tc23a = _time.perf_counter() - t0
        data_tc23a = _show("[TC-23a]", tc23a_body, resp_tc23a)
        assert resp_tc23a.status_code == 200, f"Expected 200, got {resp_tc23a.status_code}"
        assert len(data_tc23a["bikes"]) >= 1, "Expected the DB hit to survive price_max=2000"
        for b in data_tc23a["bikes"]:
            assert _matches(b, "Trek", "Marlin 5"), \
                f"Expected only Trek Marlin 5, got {b['brand']!r} {b['model']!r}"
        assert elapsed_tc23a < 5.0, \
            f"Took {elapsed_tc23a:.2f}s — expected < 5s (fell through to AI?)"
        assert not _cache_row_exists("/v1/bike/search", tc23a_key), \
            "Decision 5 violated: generic-cache row written on the DB-hit path"
        print(f"OK — kept under price_max=2000 in {elapsed_tc23a:.3f}s")

        # Boundary: the gate is `min(prices) <= price_max`, so the cheapest
        # price itself must still pass. Same seeded row, no extra AI call.
        print("\n── [TC-23b] price_max=1000 == cheapest 1000 → still kept (inclusive) ──")
        tc23b_body = {"brand": "Trek", "model": "Marlin 5", "price_max": 1000}
        tc23b_key = _norm_key(tc23b_body)
        _cache_row_delete("/v1/bike/search", tc23b_key)
        resp_tc23b = httpx.post(URL, json=tc23b_body, timeout=180)
        data_tc23b = _show("[TC-23b]", tc23b_body, resp_tc23b)
        assert resp_tc23b.status_code == 200, f"Expected 200, got {resp_tc23b.status_code}"
        assert len(data_tc23b["bikes"]) >= 1 and all(
            _matches(b, "Trek", "Marlin 5") for b in data_tc23b["bikes"]
        ), "price_max equal to the cheapest price must keep the bike"
        assert not _cache_row_exists("/v1/bike/search", tc23b_key), \
            "Decision 5 violated: generic-cache row written on the DB-hit path"
        print("OK — inclusive boundary confirmed at price_max=1000")

        print("\n── [TC-23c] price_max=500 < cheapest 1000 → filtered out, falls to AI ──")
        tc23c_body = {"brand": "Trek", "model": "Marlin 5", "price_max": 500}
        tc23c_key = _norm_key(tc23c_body)
        _cache_row_delete("/v1/bike/search", tc23c_key)  # force a real fallback each run
        resp_tc23c = httpx.post(URL, json=tc23c_body, timeout=300)
        data_tc23c = _show("[TC-23c]", tc23c_body, resp_tc23c)
        assert resp_tc23c.status_code == 200, f"Expected 200, got {resp_tc23c.status_code}"
        # The bike list cannot discriminate the two branches — the AI happily
        # returns a Marlin 5 too, budget notwithstanding. The side effect can:
        # only the AI path calls set_cached.
        assert _cache_row_exists("/v1/bike/search", tc23c_key), \
            ("price_max=500 should have filtered the DB hit out and fallen through to the "
             "AI pipeline, but no generic-cache row was written — the DB path served it")
        print(f"OK — price_max=500 filtered the DB hit out; AI pipeline ran "
              f"({len(data_tc23c['bikes'])} bikes)")
    finally:
        _drop_search_row(FIX_MARLIN_QUERY)
finally:
    _drop_offer_rows("Trek", "Marlin 5", _tc23_created)
    if _tc23_created:
        print("     seeded offer rows removed")


# ── [TC-24] Unknown price is lenient — no offer rows means the bike is kept ──
print("\n── [TC-24] Lenient unknown price: Giant Talon 3 + price_max=100 ──")
tc24_body = {"brand": "Giant", "model": "Talon 3", "price_max": 100}
tc24_key = _norm_key(tc24_body)
_seed_search_row(FIX_TALON_QUERY, [_bike("Giant", "Talon 3", "Seeded by TC-24.")])
try:
    # The fixture only works if this bike has no joinable price at all.
    assert not _joined_prices("Giant", "Talon 3"), \
        "Giant/Talon 3 now has offer rows — pick another bike for the lenient-path test"
    _cache_row_delete("/v1/bike/search", tc24_key)
    t0 = _time.perf_counter()
    resp_tc24 = httpx.post(URL, json=tc24_body, timeout=180)
    elapsed_tc24 = _time.perf_counter() - t0
    data_tc24 = _show("[TC-24]", tc24_body, resp_tc24)
    assert resp_tc24.status_code == 200, f"Expected 200, got {resp_tc24.status_code}"
    assert len(data_tc24["bikes"]) >= 1, \
        "Decision 3 is lenient: a bike with no parseable offer price must survive price_max"
    for b in data_tc24["bikes"]:
        assert _matches(b, "Giant", "Talon 3"), \
            f"Expected only Giant Talon 3, got {b['brand']!r} {b['model']!r}"
    assert elapsed_tc24 < 5.0, \
        f"Took {elapsed_tc24:.2f}s — expected < 5s (fell through to AI?)"
    assert not _cache_row_exists("/v1/bike/search", tc24_key), \
        "Decision 5 violated: generic-cache row written on the DB-hit path"
    print(f"OK — unknown price kept the bike under price_max=100 ({elapsed_tc24:.3f}s)")
finally:
    _drop_search_row(FIX_TALON_QUERY)


# ── [TC-25] No regression: the generic-cache path is unchanged ──
print("\n── [TC-25] No regression: free-text search still served by the generic cache ──")
t0 = _time.perf_counter()
resp_tc25 = httpx.post(URL, json=payload, timeout=30)
elapsed_tc25 = _time.perf_counter() - t0
assert resp_tc25.status_code == 200, f"Expected 200, got {resp_tc25.status_code}"
assert resp_tc25.json() == resp.json(), \
    "Generic-cache path regressed: free-text search no longer returns the cached response"
assert elapsed_tc25 < 5.0, f"Generic cache hit took {elapsed_tc25:.2f}s — expected < 5s"
print(f"OK — generic cache path unchanged ({elapsed_tc25:.3f}s, "
      f"{len(resp_tc25.json()['bikes'])} bikes)")


# ── TODO_009 fixture hygiene: nothing this suite seeded may survive ──
print("\n── TODO_009: fixture cleanup verification ──")
_conn = _db()
try:
    _leftover = _conn.execute(
        "SELECT COUNT(*) FROM search_cache WHERE query LIKE 'todo-009 fixture:%'"
    ).fetchone()[0]
finally:
    _conn.close()
assert _leftover == 0, f"{_leftover} TODO-009 fixture row(s) left in search_cache"
assert not _joined_prices("Giant", "Talon 3"), "TC-24 fixture leaked offer rows"
print("OK — no TODO-009 fixture rows left behind")
