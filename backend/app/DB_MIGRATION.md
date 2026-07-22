# Database Migration: JSON Cache → SQLAlchemy ORM

## Overview

This migration moves from JSON serialization in SQLite to a proper relational database schema using SQLAlchemy ORM.

### Old Approach
- Generic `cache` table with `(endpoint, request, response_json)`
- Searchable `search_cache` and `bike_details_cache` with JSON blobs
- No relationships or foreign keys
- TTL managed in application code

### New Approach
- Normalized `bikes` table — single source of truth for bike identity
- Related tables: `bike_results`, `bike_details`, `bike_offers`, `accessories`, `photos`
- Foreign key constraints
- TTL stored per record in the database
- Proper relationships via SQLAlchemy ORM

## Database Schema

### Core Tables

**`bikes`**
```
id (PK)
brand: str
model: str
created_at: datetime
updated_at: datetime
UNIQUE(brand, model)
```

**`bike_results`** — Search results, references bikes
```
id (PK)
bike_id (FK → bikes.id)
match_score: float
explanation: text
created_at: datetime
```

**`accessories`** — Items in search results, references bike_results
```
id (PK)
bike_result_id (FK → bike_results.id)
name: str
```

**`bike_details`** — Full specifications
```
id (PK)
bike_id (FK → bikes.id, UNIQUE)
description: text (JSON serialized BikeDescription)
components: text (JSON serialized list[BikeCategory])
created_at: datetime
updated_at: datetime
ttl_seconds: int (default 30 days)
```

**`bike_detail_photos`** — Photos for bike details
```
id (PK)
bike_details_id (FK → bike_details.id)
url: str
display_order: int
```

**`bike_offers`** — Marketplace listings
```
id (PK)
bike_id (FK → bikes.id)
price: str
is_new: bool
url: str (UNIQUE)
source: str (allegro.pl, olx.pl, ceneo.pl, decathlon.pl)
city: str (nullable, for used bikes)
created_at: datetime
created_at_list: datetime (when listed on marketplace)
UNIQUE(bike_id, url)
```

**`bike_offer_photos`** — Photos for offers
```
id (PK)
bike_offer_id (FK → bike_offers.id)
url: str
display_order: int
```

## Migration Steps

### 1. Install SQLAlchemy
```bash
pip install -r requirements.txt
```

### 2. Initialize Database (Backup First!)
```python
# In main.py or startup event:
from app.models import init_db
init_db()  # Creates all tables if they don't exist
```

### 3. Update Application Code

**Old:**
```python
from app import store
store.save_search(query, bikes)
result = store.get_search_by_query(query)
```

**New:**
```python
from app import repository
repository.save_search(query, bikes)
result = repository.get_search_by_query(query)
```

### 4. Migrate Existing Data (Optional)

If you have existing cache.db with JSON data:
```python
from app.store import get_search_by_query as old_get
from app.repository import save_search

# Read old data
old_data = old_get(query)
# Write to new schema
save_search(query, old_data)
```

## API Compatibility

Both `app.store` and `app.repository` provide identical interfaces:
- `save_search(query: str, bikes: list[BikeResult], ttl: int) → None`
- `get_search_by_query(query: str) → Optional[list[BikeResult]]`
- `find_bikes_by_brand(brand: str) → list[BikeResult]`
- `save_bike_details(company: str, model: str, data: BikeDetailsResponse, ttl: int) → None`
- `get_bike_details(company: str, model: str) → Optional[BikeDetailsResponse]`

## Benefits

✅ **Data Integrity** — Foreign keys, unique constraints, cascading deletes
✅ **Queryability** — Rich ORM queries instead of JSON parsing
✅ **Relationships** — One-to-many (Bike → BikeResults), One-to-one (Bike → BikeDetails)
✅ **Photo Management** — Proper ordering and sourcing
✅ **Indexed Lookups** — Brand, source, URL indices for fast queries
✅ **Future Extensions** — Easy to add new fields, relationships

## Example Queries

**Find all Trek bikes from cached searches:**
```python
from app.models import Bike, BikeResult, get_session

session = get_session()
trek_bikes = session.query(Bike).filter(Bike.brand.ilike("trek%")).all()
```

**Get all offers for a specific bike:**
```python
bike = session.query(Bike).filter_by(brand="Trek", model="Marlin 5").first()
offers = bike.offers  # Via relationship
```

**Find cheapest offer across all bikes:**
```python
from sqlalchemy import desc
cheapest = session.query(BikeOffer).order_by(BikeOffer.price).first()
```

## Rollback

To keep the old JSON-based system:
1. Don't call `init_db()`
2. Keep importing from `app.store` instead of `app.repository`
3. Remove `sqlalchemy` from `requirements.txt`
4. Delete `app/models.py` and `app/repository.py`

## Next Steps

1. Add new Offer endpoints to populate `bike_offers` table
2. Add Bike model to bike creation flow (currently implicit in search results)
3. Create analytics queries (e.g., most-searched brands, price trends)
4. Add data export/backup utilities
