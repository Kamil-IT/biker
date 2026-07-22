# TODO_009: Direct Database Search with AI Fallback

**Status:** Planning complete, ready for implementation

**Goal:** When `brand` and `model` are provided in `/v1/bike/search`, check the database first before calling AI. Return cached result on hit; fall back to AI pipeline on miss.

## Problem

Currently `POST /v1/bike/search` always runs the full Claude scoring + AI pipeline, even when the result may already exist in the database. For repeat searches (same brand+model), this wastes API credits and latency.

## Solution (Approved)

**Lookup cascade:**
1. Generic cache (exact query match) — existing
2. **NEW:** Direct brand+model lookup in `search_cache` table
3. AI fallback (Claude scoring + web_search) — existing

**Implementation approach:** Reuse existing SQLite layer in `store.py`. Do NOT wire the broken SQLAlchemy ORM (models.py/repository.py) — that's a future refactor.

## Changes Required

### 1. `backend/app/store.py` — Add lookup helper

Add new function `find_bike_by_brand_model(brand: str, model: str) -> List[BikeResult] | None`:
- Scans `search_cache` rows
- Filters by exact normalized brand+model (case-insensitive, whitespace-normalized)
- Checks TTL (24h)
- Deduplicates results
- Returns `None` on miss or expired

Mirror the pattern of existing `find_bikes_by_brand()`.

### 2. `backend/app/main.py` — Add DB-first branch in `bike_search()`

In the `bike_search()` route handler (line ~64-139), after the generic `get_cached()` miss:

```python
# After: cached = get_cached("/v1/bike/search", _fields, ...)
# Add:
if req.brand and req.model:
    db_result = find_bike_by_brand_model(req.brand, req.model)
    if db_result:
        # Warm the generic cache for next request
        set_cached("/v1/bike/search", _fields, response)
        return response
    # else: fall through to AI pipeline
```

No schema changes. No API contract changes. Response format stays identical.

## Testing

Add smoke tests to `backend/scripts/test_search.py`:

1. **DB hit:** Search with known brand+model (from prior search_cache) → assert 200, result from DB, no web calls
2. **AI fallback:** Search with unknown brand+model → assert 200, AI result, web calls made
3. **Mixed:** One bike from DB, one from AI in the same response → assert dedup + merge

Run against live local backend (`uvicorn app.main:app --reload`).

## Documentation Updates

- **`backend/README.md`:** Add "## Search Cache" section documenting the lookup cascade
- **`CLAUDE.md`:** Update `POST /v1/bike/search` endpoint description with the new DB-first behavior

## Files Changed

- `backend/app/store.py` — +1 function (~20 lines)
- `backend/app/main.py` — +5 lines in `bike_search()`
- `backend/scripts/test_search.py` — +3 smoke tests (~30 lines)
- `backend/README.md` — document the lookup cascade
- `CLAUDE.md` — update endpoint description

**Total scope:** ~80 lines of code, fully reversible

## Success Criteria

- ✅ Brand+model provided → checks DB first
- ✅ DB hit → returns cached result (no AI call)
- ✅ DB miss → falls back to AI pipeline (existing behavior)
- ✅ Smoke tests pass (DB hit, AI fallback, mixed)
- ✅ Existing tests still pass (no regression)
- ✅ Generic cache still works (no behavioral change)
- ✅ No API contract change (response format identical)

## Known Issues / Decisions

- **ORM layer (models.py/repository.py):** Left as-is (dead code). Fix in future refactor task.
- **TTL strategy:** Reuse 24h TTL from `search_cache` (existing). No new configuration.
- **Dedup strategy:** Exact brand+model match (case-insensitive). Same as existing `find_bikes_by_brand()`.

## Rollback

Remove the 5-line branch in `main.py` bike_search() and the helper in `store.py`. Endpoints revert to AI-only pipeline (existing behavior).

---

**Created:** 2026-07-22  
**Assigned to:** architect (design ✅), coder (implement), tester (verify), reviewer (approve)  
**Ready for:** Implementation  
