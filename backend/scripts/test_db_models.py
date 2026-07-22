#!/usr/bin/env python3
"""Quick test to verify database models and repository work."""
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models import init_db, Bike, BikeResult, get_session
from app.schemas import BikeResult as BikeResultSchema
from app.repository import save_search, get_search_by_query

def test_db_initialization():
    """Test that database initializes without errors."""
    print("✓ Testing database initialization...")
    init_db()
    print("  ✓ Database initialized successfully")

def test_save_and_retrieve():
    """Test save and retrieve operations."""
    print("\n✓ Testing save and retrieve...")

    # Create test data
    test_bikes = [
        BikeResultSchema(
            brand="Trek",
            model="Marlin 5",
            accessories=["Lights", "Kickstand"],
            match_score=9.5,
            explanation="Great entry-level MTB"
        ),
        BikeResultSchema(
            brand="Canyon",
            model="Grizl CF 7",
            accessories=["Bottle cage", "Fenders"],
            match_score=8.8,
            explanation="Excellent gravel bike"
        ),
    ]

    # Save
    query = "mountain bike under 2000"
    save_search(query, test_bikes)
    print(f"  ✓ Saved {len(test_bikes)} bikes for query: {query}")

    # Retrieve
    retrieved = get_search_by_query(query)
    if retrieved:
        print(f"  ✓ Retrieved {len(retrieved)} bikes from database")
        for bike in retrieved:
            print(f"    - {bike.brand} {bike.model} (score: {bike.match_score})")
    else:
        print("  ✗ Failed to retrieve bikes")
        return False

    return True

def test_bike_model():
    """Test that Bike model works directly."""
    print("\n✓ Testing Bike model directly...")
    session = get_session()

    # Query bikes
    bikes = session.query(Bike).all()
    print(f"  ✓ Found {len(bikes)} bikes in database")

    # Show details
    for bike in bikes:
        print(f"    - {bike.brand} {bike.model} (id: {bike.id})")
        print(f"      Results: {len(bike.results)}")
        print(f"      Details: {bike.details is not None}")
        print(f"      Offers: {len(bike.offers)}")

    session.close()
    return True

if __name__ == "__main__":
    try:
        test_db_initialization()
        if test_save_and_retrieve():
            test_bike_model()
            print("\n✅ All tests passed!")
        else:
            print("\n❌ Tests failed")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
