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
│ BikeDetailCo.│ │ BikeOffer    │ │ SearchBikeRating         │
│ (specs) 1:N  │ │ (listings)   │ │ (per-search rated bike)  │
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
- One-to-one: bike_review; one-to-many: bike_detail_component (details themselves are `bike.description` / `bike.short_description`)

**`SearchCache`** / **`SearchBikeRating`** — the search cache
- `search_cache`: one row per query (`query`, `time_stored`)
- `search_bike_rating_cache`: one row per bike a search returned — FK to
  `search_cache` + `bike`, plus `rating`, `explanation`, `accessories` (inline
  JSON), `display_order`
- TTL: 24 h from `store.SEARCH_TTL_SECONDS` vs `time_stored`
- (Replaced the earlier `bike_results` + `accessories` tables, now removed)

**Bike details** — the `bike.description` / `bike.short_description` columns (table `bike_detail` was dropped by `scripts/migrate_drop_bike_detail.py`; NULL description = no details) and `BikeDetailComponent` rows keyed on `bike_id`
- Stores description as JSON (BikeDescription model)
- Components are normalised into `bike_details_component` →
  `bike_details_component_element` → `bike_details_component_spec`, not a JSON blob
- No TTL: stored details are returned whatever their age (`repository.TTL_DETAILS` was removed in TODO-035)
- Photos are no longer under details — see `BikeDetailPhoto` (keyed on `bike_id`)
- Timestamps: the bike's `updated_at` only

**`BikeDetailPhoto`** — Photo URL of a bike (table `bike_detail_photos`)
- Belongs to Bike (`bike_id`, `ON DELETE CASCADE`), not to BikeDetails (TODO-035; migration `scripts/migrate_photos_bike_id.py`)
- Ordered by display_order field; written only by the searcher's photo search, never replaced

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

**`BikeReview`** / **`BikeReviewSource`** — stored expert review (tables `bike_review` / `bike_review_source`, TODO-037)
- `bike_review`: one row per bike (`bike_id` UNIQUE, `ON DELETE CASCADE`) — `score`, `explanation`, `rating`,
  `sources_used`, `created_at`, `updated_at`
- `bike_review_source`: the review's `ref` URLs, FK `review_id` (`ON DELETE CASCADE`), ordered by `display_order, id`
- Written only by the searcher (`POST /v1/search/review`); read by `app/reviews_repository.py` `get_review`; no TTL
- Existing generic-cache reviews are copied in once by `scripts/copy_review_cache_to_table.py`

### 2. `app/repository.py` — Data Access Layer

Provides the same interface as the old `app/store.py` but using ORM:

```python
# Details operations (the only functions this module still owns)
save_bike_details(company: str, model: str, data: BikeDetailsResponse, ttl: int) → None
get_bike_details(company: str, model: str) → Optional[BikeDetailsResponse]
rebuild_components(rows) → list[BikeCategory]
```

The search helpers that once lived here were removed with the `bike_results` + `accessories` tables;
`app/store.py` now only has `save_search` (write-only: AI-found bikes into `bike` + `search_cache` +
`search_bike_rating_cache`; nothing reads those two tables any more).

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

### 5. **No TTL for details (TODO-035)**
- The former module constant `repository.TTL_DETAILS` (30 days) was removed: stored details are returned whatever their age
- Search results still expire after 24 h (`store.SEARCH_TTL_SECONDS`)

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
