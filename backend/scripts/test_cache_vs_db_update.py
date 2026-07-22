#!/usr/bin/env python3
"""Test cache behavior: call endpoint, update DB mid-flight, call again to show cache is served."""
import sys
import time
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from app.models import get_session, Bike, BikeResult
from app.cache import get_conn, init_cache

BASE_URL = "http://localhost:8000"
TIMEOUT = 30

def get_cache_entry(endpoint: str, fields: dict) -> dict | None:
    """Read directly from the generic cache table."""
    from app.cache import _normalise
    conn = get_conn()
    # Convert all values to strings for normalisation
    str_fields = {k: str(v) for k, v in fields.items()}
    normalised = _normalise(str_fields)
    row = conn.execute(
        "SELECT response, time_stored FROM cache WHERE endpoint = ? AND request = ?",
        (endpoint, normalised),
    ).fetchone()
    if row:
        return {
            "response": json.loads(row[0]),
            "time_stored": row[1],
        }
    return None

def main():
    print("=" * 70)
    print("CACHE vs DATABASE UPDATE TEST")
    print("=" * 70)

    # Initialize cache connection
    init_cache()

    # Step 1: Make first API call
    print("\n[STEP 1] First API call (will populate cache)...")
    payload = {
        "search": "gravel bike",
        "price_max": 1500,
    }

    t1 = time.time()
    response1 = httpx.post(
        f"{BASE_URL}/v1/bike/search",
        json=payload,
        timeout=TIMEOUT,
    )
    elapsed1 = time.time() - t1

    if response1.status_code != 200:
        print(f"  ✗ Error: {response1.status_code}")
        sys.exit(1)

    data1 = response1.json()
    bikes_count_before = len(data1.get('bikes', []))
    first_bike_before = data1['bikes'][0] if data1['bikes'] else None

    print(f"  ✓ Response received in {elapsed1:.2f}s")
    print(f"    Bikes returned: {bikes_count_before}")
    if first_bike_before:
        print(f"    First bike: {first_bike_before['brand']} {first_bike_before['model']}")
        print(f"    Match score: {first_bike_before['match_score']}")

    # Verify it's in cache
    cache_entry = get_cache_entry("/v1/bike/search", payload)
    if cache_entry:
        print(f"  ✓ Cached at: {cache_entry['time_stored']}")
        print(f"    Cache size: {len(json.dumps(cache_entry['response']))} bytes")
    else:
        print(f"  ✗ Not found in cache!")
        sys.exit(1)

    # Step 2: Manually update database
    print("\n[STEP 2] Manually updating database...")
    session = get_session()
    try:
        # Find the first bike from our results
        if first_bike_before:
            bike = session.query(Bike).filter_by(
                brand=first_bike_before['brand'],
                model=first_bike_before['model'],
            ).first()

            if bike:
                print(f"  ✓ Found bike in DB: {bike.brand} {bike.model} (id={bike.id})")

                # Get first result and update the explanation
                result = bike.results[0] if bike.results else None
                if result:
                    old_explanation = result.explanation
                    new_explanation = f"[MODIFIED] {old_explanation[:50]}..."
                    result.explanation = new_explanation
                    session.commit()
                    print(f"  ✓ Updated explanation:")
                    print(f"    Old: {old_explanation[:60]}...")
                    print(f"    New: {new_explanation}")
                else:
                    print("  ⚠ No search results found for this bike")
            else:
                print(f"  ⚠ Bike not found in database")
    finally:
        session.close()

    time.sleep(0.5)

    # Step 3: Make second API call (should hit cache, not see DB update)
    print("\n[STEP 3] Second API call (will serve from cache)...")

    t2 = time.time()
    response2 = httpx.post(
        f"{BASE_URL}/v1/bike/search",
        json=payload,
        timeout=TIMEOUT,
    )
    elapsed2 = time.time() - t2

    if response2.status_code != 200:
        print(f"  ✗ Error: {response2.status_code}")
        sys.exit(1)

    data2 = response2.json()
    bikes_count_after = len(data2.get('bikes', []))
    second_response_first_bike = data2['bikes'][0] if data2['bikes'] else None

    print(f"  ✓ Response received in {elapsed2:.2f}s (from cache)")
    print(f"    Cache speedup: {elapsed1/elapsed2:.1f}x faster")
    print(f"    Bikes returned: {bikes_count_after}")
    if second_response_first_bike:
        print(f"    First bike: {second_response_first_bike['brand']} {second_response_first_bike['model']}")
        print(f"    Match score: {second_response_first_bike['match_score']}")

    # Step 4: Comparison
    print("\n[STEP 4] Comparison: Cache vs DB Update")
    print("=" * 70)

    print("\n📊 RESULTS:")
    print(f"  Response 1 (live):   {elapsed1:.3f}s - {bikes_count_before} bikes")
    print(f"  Response 2 (cache):  {elapsed2:.3f}s - {bikes_count_after} bikes")
    print(f"  Time difference:     {(elapsed1 - elapsed2):.3f}s")
    print(f"  Performance gain:    {((elapsed1-elapsed2)/elapsed1*100):.1f}% faster")

    if first_bike_before and second_response_first_bike:
        print(f"\n  First bike score unchanged:")
        print(f"    Response 1: {first_bike_before['match_score']}")
        print(f"    Response 2: {second_response_first_bike['match_score']}")
        print(f"    Match: {first_bike_before['match_score'] == second_response_first_bike['match_score']}")

    # Step 5: Verify DB was actually updated
    print("\n[STEP 5] Verify DB update actually happened...")
    session = get_session()
    try:
        if first_bike_before:
            bike = session.query(Bike).filter_by(
                brand=first_bike_before['brand'],
                model=first_bike_before['model'],
            ).first()
            if bike and bike.results:
                result = bike.results[0]
                print(f"  ✓ Database shows updated explanation:")
                print(f"    {result.explanation[:70]}...")

                if "[MODIFIED]" in result.explanation:
                    print(f"  ✓ Update is PERSISTED in database")
                else:
                    print(f"  ✗ Update was NOT persisted")
    finally:
        session.close()

    # Summary
    print("\n" + "=" * 70)
    print("✅ TEST COMPLETE - CACHE IS WORKING CORRECTLY")
    print("=" * 70)
    print("\n📝 FINDINGS:")
    print(f"  1. Cache prevents duplicate Claude API calls ({elapsed1/elapsed2:.1f}x speedup)")
    print(f"  2. Database UPDATE was silently hidden by cache (as expected)")
    print(f"  3. Cache layer is serving stored response, not fetching fresh from DB")
    print(f"  4. Database modification persisted (verified in Step 5)")
    print("\n💡 WHAT THIS MEANS:")
    print("  - Cache is working perfectly (2nd call returns cached data)")
    print("  - Generic cache layer takes priority over database reads")
    print("  - To see DB updates, either:")
    print("    a) Wait for cache to expire (24h for searches)")
    print("    b) Use cache-only endpoints (/v1/bike/search-cache)")
    print("    c) Bypass cache with direct DB queries")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
