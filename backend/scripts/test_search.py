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
assert len(resp.json()["bikes"]) >= 1, "Expected at least 1 bike (TODO-025: no cap, min 1)"
print(f"OK -- response status is 200, {len(resp.json()['bikes'])} bike(s)")

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
NO_MATCH_DETAIL = "Bike not available in our database"
print("\n-- Parse: extract fields from free text --")
parse_payload = {"text": "Looking for Trek Marlin 7 2022, 29 inch wheels, with suspension, non-electric"}
resp_parse = httpx.post(PARSE_URL, json=parse_payload, timeout=30)
assert resp_parse.status_code == 200, f"Expected 200, got {resp_parse.status_code}"
data_parse = resp_parse.json()
assert data_parse.get("brand") == "Trek",  f"Expected brand 'Trek', got: {data_parse.get('brand')!r}"
assert data_parse.get("year") == 2022,     f"Expected year 2022, got: {data_parse.get('year')!r}"
# Suspension/kids/rider height/weight were removed from the parser; mentioning
# suspension in the text must not bring the field back.
for _removed in ("has_suspension", "is_kids", "rider_height_cm", "rider_weight_kg"):
    assert _removed not in data_parse, f"Removed field {_removed!r} still in parse response: {data_parse}"
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

# Location names must NOT be extracted as a brand. With nothing else in the
# text that leaves an all-None parse, which the endpoint now rejects with 400.
for text in ["Mam rower w Wrocławiu", "Szukam roweru w Krakowie na walach"]:
    resp_city = httpx.post(PARSE_URL, json={"text": text}, timeout=30)
    assert resp_city.status_code == 400, f"Expected 400 for location-only text {text!r}, got {resp_city.status_code}: {resp_city.text}"
    assert resp_city.json().get("detail") == NO_MATCH_DETAIL, f"Unexpected detail for {text!r}: {resp_city.json().get('detail')!r}"
    print(f"OK -- {text!r} -> 400, no brand extracted")

# -- Parse endpoint: nothing extractable -> 400 (ISSUE: no-match warning) --
print("")
print("-- Parse: no extractable fields -> 400 --")
for text in ["dzisiaj jest ładna pogoda", "hello there"]:
    resp_nm = httpx.post(PARSE_URL, json={"text": text}, timeout=30)
    assert resp_nm.status_code == 400, f"Expected 400 for {text!r}, got {resp_nm.status_code}: {resp_nm.text}"
    assert resp_nm.json().get("detail") == NO_MATCH_DETAIL, f"Unexpected detail for {text!r}: {resp_nm.json().get('detail')!r}"
    print(f"OK -- {text!r} -> 400 {resp_nm.json().get('detail')!r}")

# A rejected parse must not be cached - the repeat must still be a 400, not a
# 200 served from the generic cache.
resp_nm2 = httpx.post(PARSE_URL, json={"text": "hello there"}, timeout=30)
assert resp_nm2.status_code == 400, f"Expected repeat 400 (empty parse must not be cached), got {resp_nm2.status_code}"
print("OK -- rejected parse is not cached")

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

# ── [TC-11] Search: removed filter fields are ignored ──
# is_kids / has_suspension / price_max / rider_height_cm / rider_weight_kg were
# dropped from SearchRequest. Pydantic ignores unknown fields, so a payload made
# only of them carries no search field at all and must be rejected with 422.
print("\n── [TC-11] Search: payload of only removed fields → 422 ──")
removed_payload = {"is_kids": True, "has_suspension": True, "price_max": 5000,
                   "rider_height_cm": 180, "rider_weight_kg": 80}
resp_removed = httpx.post(URL, json=removed_payload, timeout=10)
assert resp_removed.status_code == 422, \
    f"Expected 422 for a payload of only removed fields, got {resp_removed.status_code}"
print("OK — removed filter fields are ignored (422)")

# ── [TC-12] Search: invalid year → 422 ──
print("\n── [TC-12] Search: year out of range → 422 ──")
resp_bad_year = httpx.post(URL, json={"year": 1800}, timeout=10)
assert resp_bad_year.status_code == 422, f"Expected 422 for year=1800, got {resp_bad_year.status_code}"
print("OK — out-of-range year correctly rejected with 422")

# ── [TC-12b] Search: new structured filters in enriched query ──
print("\n── [TC-12b] Search: structured filter fields (bike_type, frame_size, etc.) ──")
filters_payload = {
    "bike_type": "Gravel",
    "price_max": 6000,          # removed field — must not reach the enriched query
    "frame_size": "M",
    "rider_height_cm": 178,     # removed field — must not reach the enriched query
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
    "Type: Gravel", "Frame size: M",
    "Gender: Universal", "Frame material: Carbon", "Brakes: Hydraulic Disc",
    "Drivetrain: 2x", "Belt drive: no", "Electric: yes", "Battery: 500 Wh",
]:
    assert expected in eq, f"Expected {expected!r} in enriched query, got: {eq!r}"
for gone in ("Max price", "Rider height", "Rider weight", "Suspension", "Kids bike"):
    assert gone not in eq, f"Removed filter {gone!r} leaked into enriched query: {eq!r}"
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

SEARCH_TTL = 24 * 60 * 60


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
            "SELECT 1 FROM endpoint_req_to_body_cache WHERE endpoint = ? AND request = ?",
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
            "DELETE FROM endpoint_req_to_body_cache WHERE endpoint = ? AND request = ?", (endpoint, request_key)
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
    time_stored — 0 is fresh, > SEARCH_TTL is stale.

    A search is now search_cache (query, time_stored) plus one
    search_bike_rating_cache row per bike (FK to bike, rating, explanation,
    inline-JSON accessories), so seeding materialises the bike rows and the
    rating rows.
    """
    stored = (datetime.now(timezone.utc) - timedelta(seconds=age_seconds)).isoformat()
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id FROM search_cache WHERE query = ?", (query,)
        ).fetchone()
        if row is not None:
            search_id = row[0]
            conn.execute(
                "DELETE FROM search_bike_rating_cache WHERE search_cache_id = ?", (search_id,)
            )
            conn.execute(
                "UPDATE search_cache SET time_stored = ? WHERE id = ?", (stored, search_id)
            )
        else:
            search_id = conn.execute(
                "INSERT INTO search_cache (query, time_stored) VALUES (?, ?)", (query, stored)
            ).lastrowid
        for order, b in enumerate(bikes):
            brand, model = b.get("brand", ""), b.get("model", "")
            hit = conn.execute(
                "SELECT id FROM bike WHERE LOWER(brand) = ? AND LOWER(model) = ?",
                (brand.strip().lower(), model.strip().lower()),
            ).fetchone()
            if hit:
                bike_id = hit[0]
            else:
                bike_id = conn.execute(
                    "INSERT INTO bike (brand, model, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?)", (brand, model, stored, stored),
                ).lastrowid
            conn.execute(
                "INSERT INTO search_bike_rating_cache "
                "(search_cache_id, bike_id, rating, explanation, accessories, display_order) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (search_id, bike_id, b.get("match_score", 0.0), b.get("explanation", ""),
                 json.dumps(b.get("accessories", [])), order),
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
# ── [TC-20] DB hit: brand+model served straight from the bike table ──
print("\n── [TC-20] DB hit: Trek Marlin 5 served from the DB (no AI) ──")
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


# ══════════════════════════════════════════════════════════════════════════
# TODO_024 — DB details search, then ONE AI call
#
# The DB step matches checkable fields against bike + bike_detail_component.
# "Which path ran" is told apart by the side effect: only the AI path calls
# set_cached, so a DB hit leaves no generic-cache row behind.
# ══════════════════════════════════════════════════════════════════════════

# ── [TC-21] DB-miss: checkable fields with no DB match → one AI call ──
# Trek carbon bikes have no bike_detail rows in cache.db, and save_search only
# writes `bike` identities (never details), so this stays a DB miss run after run.
print("\n── [TC-21] DB miss → single AI call (brand + frame material) ──")
tc21_body = {"brand": "Trek", "frame_material": "Carbon"}
tc21_key = _norm_key(tc21_body)
_cache_row_delete("/v1/bike/search", tc21_key)
t0 = _time.perf_counter()
resp_tc21 = httpx.post(URL, json=tc21_body, timeout=180)
elapsed_tc21 = _time.perf_counter() - t0
data_tc21 = _show("[TC-21]", tc21_body, resp_tc21)
assert resp_tc21.status_code == 200, f"Expected 200, got {resp_tc21.status_code}"
assert len(data_tc21["bikes"]) >= 1, f"Expected >=1 AI bikes, got {len(data_tc21['bikes'])}"
assert not any(b["explanation"].startswith("Matches:") for b in data_tc21["bikes"]), \
    "A DB-hit explanation leaked into what should be an AI result"
assert _cache_row_exists("/v1/bike/search", tc21_key), \
    "AI path should have written a generic-cache row"
print(f"OK — AI fallback returned {len(data_tc21['bikes'])} bikes in {elapsed_tc21:.1f}s and warmed the cache")
_cache_row_delete("/v1/bike/search", tc21_key)


# ── [TC-22] Only non-checkable fields → straight to AI ──
print("\n── [TC-22] Only non-checkable fields (bike_type + year) → AI ──")
tc22_body = {"bike_type": "Gravel", "year": 2024}
tc22_key = _norm_key(tc22_body)
_cache_row_delete("/v1/bike/search", tc22_key)
resp_tc22 = httpx.post(URL, json=tc22_body, timeout=180)
data_tc22 = _show("[TC-22]", tc22_body, resp_tc22)
assert resp_tc22.status_code == 200, f"Expected 200, got {resp_tc22.status_code}"
assert len(data_tc22["bikes"]) >= 1, f"Expected >=1 AI bikes, got {len(data_tc22['bikes'])}"
assert _cache_row_exists("/v1/bike/search", tc22_key), \
    "Non-checkable-only search must skip the DB and run the AI call"
print(f"OK — non-checkable search went to AI ({len(data_tc22['bikes'])} bikes)")
_cache_row_delete("/v1/bike/search", tc22_key)


# ── [TC-24] DB hit on spec fields: no AI, every match returned (no cap) ──
print("\n── [TC-24] DB hit on spec fields (carbon frame + 29\" wheels) ──")
tc24_body = {"frame_material": "Carbon", "wheel_size": '29"'}
tc24_key = _norm_key(tc24_body)
_cache_row_delete("/v1/bike/search", tc24_key)
t0 = _time.perf_counter()
resp_tc24 = httpx.post(URL, json=tc24_body, timeout=60)
elapsed_tc24 = _time.perf_counter() - t0
data_tc24 = _show("[TC-24]", tc24_body, resp_tc24)
assert resp_tc24.status_code == 200, f"Expected 200, got {resp_tc24.status_code}"
assert len(data_tc24["bikes"]) >= 1, f"Expected >=1 DB bikes, got {len(data_tc24['bikes'])}"
assert elapsed_tc24 < 5.0, f"DB hit took {elapsed_tc24:.2f}s — expected < 5s (AI ran?)"
assert not _cache_row_exists("/v1/bike/search", tc24_key), \
    "DB-hit path must not write a generic-cache row"
from app.schemas import SearchRequest as _SearchRequest  # noqa: E402
from app.repository import find_bikes_by_details as _find_db  # noqa: E402
_db_expected = [(b.brand, b.model) for b in _find_db(_SearchRequest(**tc24_body))]
assert [(b["brand"], b["model"]) for b in data_tc24["bikes"]] == _db_expected, \
    "Endpoint result differs from repository.find_bikes_by_details"
print(f"OK — DB hit in {elapsed_tc24:.3f}s, {len(data_tc24['bikes'])} bike(s), no AI, no cache row")


# ── [TC-23] price_max is gone — it no longer gates the DB hit ──
print("\n── [TC-23] Legacy price_max is ignored on the DB-hit path ──")
tc23_body = {"brand": "Trek", "model": "Marlin 5", "price_max": 1}
tc23_key = _norm_key({"brand": "Trek", "model": "Marlin 5"})  # price_max is not in the key
_seed_search_row(FIX_MARLIN_QUERY, [_bike("Trek", "Marlin 5", "Seeded by TC-23.")])
try:
    _cache_row_delete("/v1/bike/search", tc23_key)
    t0 = _time.perf_counter()
    resp_tc23 = httpx.post(URL, json=tc23_body, timeout=180)
    elapsed_tc23 = _time.perf_counter() - t0
    data_tc23 = _show("[TC-23]", tc23_body, resp_tc23)
    assert resp_tc23.status_code == 200, f"Expected 200, got {resp_tc23.status_code}"
    assert len(data_tc23["bikes"]) >= 1 and all(
        _matches(b, "Trek", "Marlin 5") for b in data_tc23["bikes"]
    ), "price_max=1 must no longer filter the DB hit out"
    assert elapsed_tc23 < 5.0, f"Took {elapsed_tc23:.2f}s — expected < 5s (fell through to AI?)"
    assert "Max price" not in data_tc23["search"], \
        f"price_max leaked into the enriched query: {data_tc23['search']!r}"
    print(f"OK — price_max ignored, DB hit served in {elapsed_tc23:.3f}s")
finally:
    _drop_search_row(FIX_MARLIN_QUERY)


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


# ── [TC-26] TODO-025: impossible filters still return the closest bike (min 1) ──
print("\n── [TC-26] Impossible filter combination → ≥1 closest bike, low score ──")
tc26_body = {"brand": "Trek", "is_electric": True, "brake_type": "Rim"}
tc26_key = _norm_key(tc26_body)
_cache_row_delete("/v1/bike/search", tc26_key)
resp_tc26 = httpx.post(URL, json=tc26_body, timeout=180)
data_tc26 = _show("[TC-26]", tc26_body, resp_tc26)
assert resp_tc26.status_code == 200, f"Expected 200, got {resp_tc26.status_code}"
assert len(data_tc26["bikes"]) >= 1, "Impossible filters must still return the closest bike"
print(f"OK — closest match returned: {data_tc26['bikes'][0]['brand']} {data_tc26['bikes'][0]['model']} "
      f"score={data_tc26['bikes'][0]['match_score']}")
_cache_row_delete("/v1/bike/search", tc26_key)


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
print("OK — no TODO-009 fixture rows left behind")


# ══════════════════════════════════════════════════════════════════════════
# TODO_026 — POST /v1/bike/missing counts "Request data" clicks per bike + section
#
# The route never creates a bike, so the suite seeds its own namespaced `bike`
# row and deletes it (and its request rows) on the way out.
# ══════════════════════════════════════════════════════════════════════════
MISSING_URL = "http://localhost:8000/v1/bike/missing"
FIX_MISSING_BRAND, FIX_MISSING_MODEL = "TODO-026 Fixture", "Missing Data Bike"


def _missing_rows(bike_id: int) -> list[tuple[str, int]]:
    conn = _db()
    try:
        return conn.execute(
            "SELECT missing_type, counter FROM bike_missing_request WHERE bike_id = ? ORDER BY missing_type",
            (bike_id,),
        ).fetchall()
    finally:
        conn.close()


def _drop_missing_fixture() -> None:
    conn = _db()
    try:
        conn.execute(
            "DELETE FROM bike_missing_request WHERE bike_id IN "
            "(SELECT id FROM bike WHERE brand = ? AND model = ?)", (FIX_MISSING_BRAND, FIX_MISSING_MODEL),
        )
        conn.execute("DELETE FROM bike WHERE brand = ? AND model = ?", (FIX_MISSING_BRAND, FIX_MISSING_MODEL))
        conn.commit()
    finally:
        conn.close()


# ── [TC-27] Existing bike: counter starts at 1 and adds 1 per call, one row per type ──
print("\n── [TC-27] POST /v1/bike/missing — counter increments on an existing bike ──")
_drop_missing_fixture()
_conn = _db()
try:
    _now = datetime.now(timezone.utc).isoformat()
    fix_bike_id = _conn.execute(
        "INSERT INTO bike (brand, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (FIX_MISSING_BRAND, FIX_MISSING_MODEL, _now, _now),
    ).lastrowid
    _conn.commit()
finally:
    _conn.close()
try:
    # Different casing/whitespace than the stored row: lookup is normalised.
    tc27_body = {"company": " todo-026 fixture ", "model": "MISSING DATA BIKE", "missing_type": "photos"}
    first = _show("[TC-27] 1st", tc27_body, httpx.post(MISSING_URL, json=tc27_body, timeout=10))
    resp_tc27 = httpx.post(MISSING_URL, json=tc27_body, timeout=10)
    second = _show("[TC-27] 2nd", tc27_body, resp_tc27)
    assert resp_tc27.status_code == 200, f"Expected 200, got {resp_tc27.status_code}"
    assert first == {"bike_id": fix_bike_id, "missing_type": "photos", "counter": 1}, first
    assert second["counter"] == first["counter"] + 1, f"Counter did not go up by 1: {first} -> {second}"
    other = httpx.post(MISSING_URL, json={**tc27_body, "missing_type": "review"}, timeout=10).json()
    assert other["counter"] == 1, f"A new missing_type must start its own counter, got {other}"
    assert _missing_rows(fix_bike_id) == [("photos", 2), ("review", 1)], _missing_rows(fix_bike_id)
    assert not _cache_row_exists("/v1/bike/missing", _norm_key(tc27_body)), \
        "/v1/bike/missing must not write a generic-cache row"
    print("OK — counter 1 → 2, separate row per missing_type, no cache row")
finally:
    _drop_missing_fixture()


# ── [TC-28] Unknown bike → 200, bike_id null, counter 0, nothing written ──
print("\n── [TC-28] POST /v1/bike/missing — unknown bike is a 200 no-op ──")
tc28_body = {"company": "TODO-026 Fixture", "model": "Does Not Exist", "missing_type": "photos"}
resp_tc28 = httpx.post(MISSING_URL, json=tc28_body, timeout=10)
data_tc28 = _show("[TC-28]", tc28_body, resp_tc28)
assert resp_tc28.status_code == 200, f"Expected 200, got {resp_tc28.status_code}"
assert data_tc28 == {"bike_id": None, "missing_type": "photos", "counter": 0}, data_tc28
_conn = _db()
try:
    assert _conn.execute(
        "SELECT COUNT(*) FROM bike WHERE brand = ? AND model = ?", (tc28_body["company"], tc28_body["model"])
    ).fetchone()[0] == 0, "An unknown bike must not be created"
finally:
    _conn.close()
print("OK — unknown bike: bike_id null, counter 0, no bike row created")


# ── [TC-29] Invalid missing_type → 422 ──
print("\n── [TC-29] POST /v1/bike/missing — empty / blank / >64-char missing_type → 422 ──")
for _bad in ["", "   ", "x" * 65]:
    _r = httpx.post(MISSING_URL, json={**tc28_body, "missing_type": _bad}, timeout=10)
    assert _r.status_code == 422, f"missing_type={_bad[:10]!r}…: expected 422, got {_r.status_code}"
print("OK — invalid missing_type rejected with 422")
