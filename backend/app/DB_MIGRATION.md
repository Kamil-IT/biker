# Database Migration: JSON Cache → SQLAlchemy ORM

## Overview

This migration moves from JSON serialization in SQLite to a proper relational database schema using SQLAlchemy ORM.

### Old Approach
- Generic `endpoint_req_to_body_cache` table with `(endpoint, request, response_json)`
- Searchable `search_cache` and the retired `bike_details_cache` with JSON blobs
- No relationships or foreign keys
- TTL managed in application code

### New Approach
- Normalized `bike` table — single source of truth for bike identity
- Related tables: `bike_detail`, `bike_offer`, `photos`, and the search cache
  (`search_cache` + `search_bike_rating_cache`)
- Foreign key constraints (enforced — `app/cache.py` sets `PRAGMA foreign_keys=ON`)
- TTL via module constants compared against `time_stored` / `updated_at`
- Proper relationships via SQLAlchemy ORM

## Database Schema

### Core Tables

**`bike`**
```
id (PK)
brand: str
model: str
created_at: datetime
updated_at: datetime
UNIQUE(brand, model)
```

**`search_cache`** — one cached search query
```
id (PK)
query: text (UNIQUE)
time_stored: str (ISO-8601)
```

**`search_bike_rating_cache`** — one bike a search returned (replaces the old
`bike_results` + `accessories` tables)
```
id (PK)
search_cache_id (FK → search_cache.id, CASCADE)
bike_id (FK → bike.id, CASCADE)
rating: float
explanation: text
accessories: text (JSON array of strings)
display_order: int
```

**`bike_details`** — Full specifications
```
id (PK)
bike_id (FK → bike.id, UNIQUE)
description: text (JSON serialized BikeDescription)
created_at: datetime
updated_at: datetime
```

**`bike_detail_photos`** — Photos for bike details
```
id (PK)
bike_details_id (FK → bike_details.id)
url: str
display_order: int
```

**`bike_details_component`** — One (category, subcategory) pair
```
id (PK)
bike_details_id (FK → bike_details.id)
category: str        e.g. "Frame"    — repeats across the rows sharing it
subcategory: str     e.g. "Fork"
display_order: int   running counter across the whole tree
```

**`bike_details_component_element`** — A named part
```
id (PK)
component_id (FK → bike_details_component.id)
name: str            e.g. "Shimano GRX RD-RX822 12s"
description: text    often "" — never NULL
display_order: int
```

**`bike_details_component_spec`** — One key/value spec row
```
id (PK)
element_id (FK → bike_details_component_element.id)
key: str             e.g. "Weight"
value: str           e.g. "580 g"
display_order: int
```
NOT unique on (element_id, key) — the source data repeats keys within an
element, and many elements carry no specs at all.

**`bike_offer`** — Marketplace listings
```
id (PK)
bike_id (FK → bike.id)
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
bike_offer_id (FK → bike_offer.id)
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

## API surface (current)

- Search cache — `app.store`: `save_search`, `get_search_by_query`,
  `find_bikes_by_brand`, `find_bike_by_brand_model` (backed by `search_cache` +
  `search_bike_rating_cache`).
- Details cache — `app.repository`: `save_bike_details`, `get_bike_details`
  (backed by `bike_detail` + `bike_detail_component` + `bike_detail_photos`).

(The `bike_results` + `accessories` tables and `repository`'s own copies of the
search helpers were removed once the store versions became authoritative.)

## Benefits

✅ **Data Integrity** — Foreign keys, unique constraints, cascading deletes
✅ **Queryability** — Rich ORM queries instead of JSON parsing
✅ **Relationships** — One-to-many (Bike → BikeOffer, SearchCache → ratings), One-to-one (Bike → BikeDetails)
✅ **Photo Management** — Proper ordering and sourcing
✅ **Indexed Lookups** — Brand, source, URL indices for fast queries
✅ **Future Extensions** — Easy to add new fields, relationships

## Example Queries

**Find all Trek bikes from cached searches:**
```python
from app.models import Bike, get_session

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

1. Add new Offer endpoints to populate `bike_offer` table
2. Add Bike model to bike creation flow (currently implicit in search results)
3. Create analytics queries (e.g., most-searched brands, price trends)
4. Add data export/backup utilities
