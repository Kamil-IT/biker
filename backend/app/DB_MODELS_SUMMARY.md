# Database Models Summary

## What Was Created

Three new files implement a complete relational database layer for bike data:

### 1. `app/models.py` — SQLAlchemy ORM Models
Defines 7 tables with relationships and constraints:

#### Entity Relationship Diagram
```
┌─────────────────────────────────────────────────────────┐
│                      BIKES (core)                       │
│  id | brand | model | created_at | updated_at          │
│  UNIQUE(brand, model)                                   │
└──────────────────┬──────────────────────────────────────┘
                   │
        ┌──────────┼──────────┐
        │          │          │
        ↓          ↓          ↓
┌──────────────┐ ┌──────────────────┐ ┌──────────────┐
│ BikeResults  │ │ BikeDetails      │ │ BikeOffers   │
│ (search)     │ │ (specs)          │ │ (listings)   │
│ 1:N          │ │ 1:1              │ │ 1:N          │
└──┬───────────┘ └──┬───────────────┘ └──┬───────────┘
   │                │                     │
   ↓                ↓                     ↓
┌──────────────┐ ┌──────────────────┐ ┌──────────────┐
│ Accessories  │ │ BikeDetailPhotos │ │ BikeOffer    │
│ (strings)    │ │ (URLs + order)   │ │ Photos       │
└──────────────┘ └──────────────────┘ └──────────────┘
```

#### Table Details

**`Bike`** — Master bike record
- Primary identity by (brand, model)
- Shared across search results, details, and offers
- Timestamp tracking (created_at, updated_at)
- One-to-many: bike_results, bike_offers
- One-to-one: bike_details

**`BikeResult`** — One search result
- Belongs to one Bike
- Stores: match_score, explanation
- One-to-many: accessories
- TTL: 24 hours (inferred from created_at)

**`Accessory`** — An item in a bike result
- Belongs to BikeResult
- Single field: name (string)

**`BikeDetails`** — Full specifications for one bike
- Unique per Bike (one-to-one)
- Stores description as JSON (BikeDescription model)
- Stores components as JSON (list[BikeCategory])
- One-to-many: photos (ordered)
- TTL: 30 days (configurable via ttl_seconds field)
- Timestamps: created_at, updated_at

**`BikeDetailPhoto`** — Photo URL for bike specs
- Belongs to BikeDetails
- Ordered by display_order field

**`BikeOffer`** — Marketplace listing (new/used)
- Belongs to Bike
- Stores: price, is_new, url, source, city
- source values: "allegro.pl", "olx.pl", "ceneo.pl", "decathlon.pl"
- Unique URL per bike (prevents duplicate listings)
- Optional city (for used listings)
- One-to-many: photos

**`BikeOfferPhoto`** — Photo URL for offers
- Belongs to BikeOffer
- Ordered by display_order field

### 2. `app/repository.py` — Data Access Layer

Provides the same interface as the old `app/store.py` but using ORM:

```python
# Search operations
save_search(query: str, bikes: list[BikeResult], ttl: int) → None
get_search_by_query(query: str) → Optional[list[BikeResult]]
find_bikes_by_brand(brand: str) → list[BikeResult]

# Details operations
save_bike_details(company: str, model: str, data: BikeDetailsResponse, ttl: int) → None
get_bike_details(company: str, model: str) → Optional[BikeDetailsResponse]
```

Each function:
- Uses `get_session()` to get a SQLAlchemy Session
- Handles transactions (commit/rollback)
- Logs operations (hit/miss/store)
- Catches exceptions silently (like the old JSON store)
- Auto-closes sessions

### 3. `DB_MIGRATION.md` — Migration Guide

Complete guide covering:
- Schema comparison (old vs new)
- All 7 tables with structure
- Migration steps
- API compatibility (drop-in replacement)
- Example queries
- Rollback procedure

## Key Design Decisions

### 1. **JSON Storage for Complex Types**
- `BikeDescription` and `BikeCategory` remain as JSON strings
- Reason: These are domain models, not query targets; JSON keeps them flexible
- Deserialization happens in `repository` layer

### 2. **No Separate "BikeModel" Table**
- Bike identity is (brand, model) pair
- No surrogate "model_id" needed
- UNIQUE constraint enforces single record per bike

### 3. **Photos as Separate Tables**
- BikeDetailPhoto and BikeOfferPhoto are ordered lists
- Easier to paginate, fetch, update independently
- display_order field preserves original sequence

### 4. **City for Used Bikes Only**
- Nullable `city` field in BikeOffer
- Used listings from OLX include city; new from Allegro don't

### 5. **TTL as Stored Field**
- `bike_details.ttl_seconds` allows per-record expiry
- Checked at query time (not automatic cleanup)
- Reason: Lazy deletion avoids frequent DB maintenance

### 6. **Foreign Key Cascades**
- Delete a Bike → auto-deletes its results, details, offers
- Delete a BikeResult → auto-deletes its accessories
- Maintains referential integrity

## Migration Path

### Option A: Gradual (Recommended)
1. Add models.py and repository.py (already done)
2. Keep old store.py unchanged
3. Import from repository for new code
4. Old endpoints stay on store; new endpoints on repository
5. Once all code migrated, remove old store.py

### Option B: Big Bang
1. Call `init_db()` in FastAPI startup
2. Update all imports from `store` → `repository`
3. Backup cache.db if it has data
4. Let SQLite handle schema creation

### Option C: No Migration (Keep JSON)
1. Don't use these new files
2. Continue with store.py
3. Delete models.py, repository.py, DB_MIGRATION.md

## File Locations

```
backend/
  requirements.txt (✎ added sqlalchemy)
  app/
    models.py (✨ NEW — ORM definitions)
    repository.py (✨ NEW — data access layer)
    DB_MIGRATION.md (✨ NEW — migration guide)
    DB_MODELS_SUMMARY.md (this file)
    store.py (⚠ old, still works)
    cache.py (⚠ old, used by store.py)
    schemas.py (unchanged)
  cache.db (auto-created by init_db())
```

## Next Steps

1. **Test it locally:**
   ```bash
   pip install -r requirements.txt
   python -c "from app.models import init_db; init_db()"
   # Tables created in cache.db
   ```

2. **Update main.py** to initialize:
   ```python
   from app.models import init_db
   @app.on_event("startup")
   async def startup():
       init_db()
   ```

3. **Switch endpoints** (gradual):
   ```python
   # Old: from app.store import save_search
   # New:
   from app.repository import save_search
   ```

4. **Add Bike management endpoint** (future):
   - New `/v1/bike` CRUD operations
   - Create, read, update bike records
   - Links to offers, details, reviews

5. **Analytics** (future):
   - Most searched brands
   - Trending bikes
   - Price history per bike
   - Source comparison (same bike on multiple marketplaces)

## Backward Compatibility

✅ Both `store` and `repository` provide identical function signatures
✅ Pydantic schemas unchanged (`BikeResult`, `BikeDetailsResponse`, etc.)
✅ Can run both simultaneously (different backend stores)
✅ Easy to swap: one line import change per module
