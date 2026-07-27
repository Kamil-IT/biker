# Database Models Summary

## What Was Created

Three new files implement a complete relational database layer for bike data:

### 1. `app/models.py` — SQLAlchemy ORM Models
Defines 8 tables with relationships and constraints:

#### Entity Relationship Diagram
```
┌─────────────────────────────────────────────────────────┐
│                      BIKE (core)                        │
│  id | brand | model | created_at | updated_at          │
│  UNIQUE(brand, model)                                   │
└──────────────────┬──────────────────────────────────────┘
                   │
        ┌──────────┼──────────────────┐
        │          │                  │
        ↓          ↓                  ↓
┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐
│ BikeDetails  │ │ BikeOffer    │ │ SearchBikeRating         │
│ (specs) 1:1  │ │ (listings)   │ │ (per-search rated bike)  │
│              │ │ 1:N          │ │ FK bike + FK search_cache│
└──┬───────────┘ └──┬───────────┘ └──────────┬───────────────┘
   │                │                          │
   ↓                ↓                          ↑ N:1
┌──────────────────┐ ┌──────────────┐   ┌──────────────┐
│ BikeDetailPhotos │ │ BikeOffer    │   │ SearchCache  │
│ (URLs + order)   │ │ Photos       │   │ (query)      │
└──────────────────┘ └──────────────┘   └──────────────┘
```

#### Table Details

**`Bike`** — Master bike record
- Primary identity by (brand, model)
- Shared across search ratings, details, and offers
- Timestamp tracking (created_at, updated_at)
- One-to-many: bike_offer, search_bike_rating_cache
- One-to-one: bike_detail

**`SearchCache`** / **`SearchBikeRating`** — the search cache
- `search_cache`: one row per query (`query`, `time_stored`)
- `search_bike_rating_cache`: one row per bike a search returned — FK to
  `search_cache` + `bike`, plus `rating`, `explanation`, `accessories` (inline
  JSON), `display_order`
- TTL: 24 h from `store.SEARCH_TTL_SECONDS` vs `time_stored`
- (Replaced the earlier `bike_results` + `accessories` tables, now removed)

**`BikeDetails`** — Full specifications for one bike
- Unique per Bike (one-to-one)
- Stores description as JSON (BikeDescription model)
- Components are normalised into `bike_details_component` →
  `bike_details_component_element` → `bike_details_component_spec`, not a JSON blob
- One-to-many: photos (ordered)
- TTL: 30 days (module constant `repository.TTL_DETAILS`, not stored per record)
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
# Details operations (the only functions this module still owns)
save_bike_details(company: str, model: str, data: BikeDetailsResponse, ttl: int) → None
get_bike_details(company: str, model: str) → Optional[BikeDetailsResponse]
rebuild_components(rows) → list[BikeCategory]
```

The search helpers (`save_search` / `get_search_by_query` / `find_bikes_by_brand`)
that once lived here were removed with the `bike_results` + `accessories` tables;
the live search cache is `search_cache` + `search_bike_rating_cache` in
`app/store.py`.

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

### 5. **TTL as Module Constant**
- `repository.TTL_DETAILS` applies uniformly to every bike_details row
- Compared against `updated_at` at query time (not automatic cleanup)
- Reason: Lazy deletion avoids frequent DB maintenance; no caller ever varied
  the TTL per record, so storing it per row only risked stale rows outliving a
  changed constant

### 6. **Foreign Key Cascades**
- Delete a Bike → auto-deletes its results, details, offers
- Delete a SearchCache → auto-deletes its search_bike_rating_cache rows
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
