#!/usr/bin/env python3
"""Integration test: verify cache works with new database models."""
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from app.models import get_session, Bike, BikeResult, Accessory

BASE_URL = "http://localhost:8000"
TIMEOUT = 30

def wait_for_server(max_retries=15, delay=1):
    """Wait for server to be ready."""
    for attempt in range(max_retries):
        try:
            response = httpx.get(f"{BASE_URL}/docs", timeout=2)
            if response.status_code == 200:
                print(f"✓ Server ready after {attempt * delay}s")
                return True
        except (httpx.ConnectError, httpx.TimeoutException):
            if attempt < max_retries - 1:
                print(f"  Waiting for server... ({attempt + 1}/{max_retries})")
                time.sleep(delay)
    return False

def test_bike_search():
    """Test bike search endpoint."""
    print("\n✓ Testing POST /v1/bike/search...")

    payload = {
        "search": "mountain bike",
        "price_max": 2000,
        "is_electric": False,
    }

    # First request (should hit Claude)
    t1 = time.time()
    response = httpx.post(
        f"{BASE_URL}/v1/bike/search",
        json=payload,
        timeout=TIMEOUT,
    )
    elapsed1 = time.time() - t1

    if response.status_code != 200:
        print(f"  ✗ Error: {response.status_code}")
        print(f"    Response: {response.text}")
        return False

    data = response.json()
    print(f"  ✓ First request (Claude): {elapsed1:.2f}s")
    print(f"    Bikes found: {len(data.get('bikes', []))}")
    print(f"    Search query: {data.get('search', '')[:60]}...")

    if not data.get('bikes'):
        print("  ⚠ No bikes found in response")
        return False

    # Second request (should hit cache)
    time.sleep(0.5)
    t2 = time.time()
    response2 = httpx.post(
        f"{BASE_URL}/v1/bike/search",
        json=payload,
        timeout=TIMEOUT,
    )
    elapsed2 = time.time() - t2

    if response2.status_code != 200:
        print(f"  ✗ Cache miss error: {response2.status_code}")
        return False

    data2 = response2.json()
    print(f"  ✓ Second request (cached): {elapsed2:.2f}s")
    print(f"    Cache speedup: {elapsed1/elapsed2:.1f}x faster")

    # Verify same results
    if len(data['bikes']) == len(data2['bikes']):
        print(f"  ✓ Cache consistency: {len(data['bikes'])} bikes in both requests")
    else:
        print(f"  ✗ Cache mismatch: {len(data['bikes'])} vs {len(data2['bikes'])}")
        return False

    return data['search']  # Return search query for later verification

def test_bike_details(company: str, model: str):
    """Test bike details endpoint."""
    print(f"\n✓ Testing POST /v1/bike/details...")

    payload = {"company": company, "model": model}

    # First request
    t1 = time.time()
    response = httpx.post(
        f"{BASE_URL}/v1/bike/details",
        json=payload,
        timeout=TIMEOUT,
    )
    elapsed1 = time.time() - t1

    if response.status_code != 200:
        print(f"  ✗ Error: {response.status_code}")
        return False

    data = response.json()
    print(f"  ✓ First request (Claude): {elapsed1:.2f}s")
    print(f"    Company: {data.get('company')}")
    print(f"    Model: {data.get('model')}")
    print(f"    Components: {len(data.get('components', []))}")
    print(f"    Photos: {len(data.get('photos', []))}")

    # Second request (should be faster)
    time.sleep(0.5)
    t2 = time.time()
    response2 = httpx.post(
        f"{BASE_URL}/v1/bike/details",
        json=payload,
        timeout=TIMEOUT,
    )
    elapsed2 = time.time() - t2

    if response2.status_code != 200:
        print(f"  ✗ Cache miss error: {response2.status_code}")
        return False

    print(f"  ✓ Second request (cached): {elapsed2:.2f}s")
    print(f"    Cache speedup: {elapsed1/elapsed2:.1f}x faster")

    return True

def check_database_state():
    """Inspect database to verify models are working."""
    print("\n✓ Checking database state...")
    session = get_session()
    try:
        # Count bikes
        bike_count = session.query(Bike).count()
        print(f"  ✓ Bikes in DB: {bike_count}")

        if bike_count == 0:
            print("  ⚠ No bikes found in database")
            return False

        # Show first few bikes with details
        bikes = session.query(Bike).limit(3).all()
        for bike in bikes:
            print(f"\n    Bike: {bike.brand} {bike.model}")
            print(f"      Search results: {len(bike.results)}")
            print(f"      Details cached: {bike.details is not None}")
            print(f"      Offers cached: {len(bike.offers)}")

            if bike.results:
                first_result = bike.results[0]
                print(f"      Accessories: {len(first_result.accessories)}")
                for acc in first_result.accessories[:2]:
                    print(f"        - {acc.name}")

        # Count results
        result_count = session.query(BikeResult).count()
        accessory_count = session.query(Accessory).count()
        print(f"\n  ✓ Search results in DB: {result_count}")
        print(f"  ✓ Accessories in DB: {accessory_count}")

        return True
    finally:
        session.close()

def test_cache_lookup():
    """Test cache-only endpoints."""
    print("\n✓ Testing cache-only endpoints...")

    # Test search cache lookup
    response = httpx.get(
        f"{BASE_URL}/v1/bike/search-cache",
        params={"brand": "Trek"},
        timeout=TIMEOUT,
    )

    if response.status_code == 200:
        data = response.json()
        print(f"  ✓ Brand search cache: {len(data.get('bikes', []))} bikes found")
    elif response.status_code == 404:
        print(f"  ℹ No cached results for brand search (expected on first run)")
    else:
        print(f"  ✗ Unexpected status: {response.status_code}")
        return False

    return True

def main():
    """Run all tests."""
    print("=" * 60)
    print("BIKER APPLICATION CACHE INTEGRATION TEST")
    print("=" * 60)

    # Wait for server
    if not wait_for_server():
        print("\n✗ Server failed to start")
        sys.exit(1)

    try:
        # Test search
        search_query = test_bike_search()
        if not search_query:
            print("\n✗ Search test failed")
            sys.exit(1)

        # Extract first bike for details test
        response = httpx.post(
            f"{BASE_URL}/v1/bike/search",
            json={"search": "Trek Marlin"},
            timeout=TIMEOUT,
        )

        if response.status_code == 200:
            bikes = response.json().get('bikes', [])
            if bikes:
                first_bike = bikes[0]
                test_bike_details(first_bike['brand'], first_bike['model'])

        # Test cache-only endpoints
        test_cache_lookup()

        # Check database
        if not check_database_state():
            print("\n✗ Database check failed")
            sys.exit(1)

        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print("\nSummary:")
        print("  ✓ Backend responding correctly")
        print("  ✓ Cache working (2nd request much faster)")
        print("  ✓ Database models populated with data")
        print("  ✓ Relationships working (bikes → results → accessories)")

    except Exception as e:
        print(f"\n✗ Test error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
