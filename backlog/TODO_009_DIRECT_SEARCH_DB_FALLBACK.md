# TODO_009: Direct Database Search with AI Fallback

**Status:** Design resolved in interview (2026-07-23), ready for implementation

**Goal:** When `brand` and `model` are provided to `POST /v1/bike/search`, serve the result from the local SQLite cache before calling AI. Join the offer cache to honour `price_max`. Fall back to the AI pipeline on a miss.

## Problem

`POST /v1/bike/search` always runs the full Claude scoring + web_search pipeline (11 scoring calls + N finder calls), even when the answer already sits in `cache.db`. For repeat brand+model searches this wastes API credits and adds tens of seconds of latency.

## Lookup cascade

1. **Generic cache** — exact normalised request match (`cache.py`). Existing, unchanged.
2. **NEW: brand+model DB lookup** — `search_cache` scan, gated by `price_max` via a join onto the offer cache.
3. **AI fallback** — Claude scoring + web_search. Existing, unchanged.

Reuse the existing SQLite layer in `store.py`. Do **not** wire the SQLAlchemy ORM (`models.py` / `repository.py`) — dead code, separate refactor.

## Decisions (resolved in interview — do not re-litigate)

| # | Question | Decision |
|---|---|---|
| 1 | Response shape on a DB hit | **Only matching bikes.** Return just the bikes whose brand+model match — may be 1 bike, not 5. Do not pad with siblings. |
| 2 | Extra filters (`price_max`, `year`, …) | **Use the DB and honour what we can.** Join the offer cache to gate `price_max`. Filters with no backing data are not gated (see Coverage). |
| 3 | Unknown price under `price_max` | **Lenient — keep it.** A bike with no parseable offer price passes the filter. Maximises hit rate; may return an unverified over-budget bike. |
| 4 | Which price gates `price_max` | **Cheapest across all sources.** `min()` of every parseable price from all 4 offer endpoints, new and used alike. |
| 5 | Generic-cache warming on a DB hit | **Do not warm.** Never call `set_cached` on the DB-hit path — the generic `cache` table has no TTL, so warming would pin a 24 h-TTL result permanently. |
| 6 | Hybrid DB+AI merge (old test #3) | **Dropped.** Pure cascade: a DB hit short-circuits, AI never runs. Replaced by a stale-row-falls-through test. |
| 7 | Scope | **Full scope, one PR.** |

## Ground truth from `cache.db` (measured 2026-07-23)

Verified against the live database — the implementation must match these realities, not assumptions.

**The join key already lines up.** Offer rows are keyed `{"company":"trek","model":"marlin 5"}` — lowercased and stripped by `cache.py:62` `_normalise()`, which matches `store.py:71` `_norm()`. No new normalisation needed.

**Coverage is thin.** Of 39 distinct bikes in `search_cache`, only **8 (21 %)** have a matching offer row:

```
HIT   trek/marlin 5 · trek/marlin 7 · trek/fx 3 · trek/fx 3 disc · trek/domane sl 5
      cannondale/topstone carbon 4 · specialized/allez sprint · riese & müller/nevo4 gt
MISS  canyon/neuron 6 · giant/talon 3 · cube/aim 27.5 · kona/kona rove st … (31 more)
```

This is *why* decision 3 is lenient — strict filtering would kill ~79 % of hits.

**Only `price_max` is backed by data.** `BikeResult` (`schemas.py:178`) carries only `brand, model, accessories, match_score, explanation`. `BikeOffer` (`schemas.py:238`) adds `price, is_new, url, photos, source, city`. Nothing anywhere stores `year`, `frame_size`, `wheel_size`, `frame_material`, `brake_type`, `drivetrain`, `gender`, `rider_height_cm`, `rider_weight_kg`, `battery_capacity_wh`. Those filters are therefore **not** gated on the DB path — document this, do not fake it.

**`price` is a string, not a number** (`schemas.py:241`). Real observed values:

```
'2799 zł'  '1199.99 zł'  '1407,12 zł'  '17 386,85 zł'  '11 000 zł'  '939,99 zł'
'Price on request'  'Not listed'  'Not specified'
```

Comma *and* dot decimals; space thousands separators; three non-numeric sentinels.

**Known data-quality landmines** (flag, do not fix here):
- The offer cache has **no TTL** — `cache.py:31` has `time_stored` but no `ttl` column and `get_cached` never checks age. Joined prices never expire.
- Brand/model split disagrees across pipelines: `search_cache` holds `('decathlon','rockrider st 100')` while the offer row is `('rockrider','st 100')`. These will not join. Acceptable for now.
- Bad scrape in live data: `/v1/bike/offer` has `rockrider/st 100` at `'279 zł'` — an accessory, not the bike. Lenient filtering limits the blast radius.

## Changes required

### 1. NEW `backend/app/price_parse.py`

```python
def parse_price(raw: str) -> float | None
```

- Strip currency tokens (`zł`, `PLN`, `zl`) case-insensitively.
- Strip regular spaces, NBSP (` `) and narrow NBSP (` `) used as thousands separators.
- Both `,` and `.` present → the **last** separator is the decimal point.
- Only `,` present → decimal iff exactly 2 digits follow, else thousands separator.
- Only `.` present → same rule.
- Return `None` for anything with no digits (`'Price on request'`, `'Not listed'`, `'Not specified'`, `''`).
- Never raise. `None` means "unknown", which under decision 3 means "keep".

Unit-test every literal in the Ground-truth block above.

### 2. `backend/app/store.py` — two helpers

```python
def find_bike_by_brand_model(brand: str, model: str) -> list[BikeResult]
```
Mirror `find_bikes_by_brand()` (`store.py:119`): scan `search_cache`, skip rows failing `_is_fresh()`, match `_norm(brand)` **and** `_norm(model)`, dedup on `(brand, model)`. Return `[]` on miss/stale.

```python
def find_offer_prices(brand: str, model: str) -> list[float]
```
Scan the generic `cache` table for `endpoint IN ('/v1/bike/offer','/v1/bike/ceneo','/v1/bike/decathlon','/v1/bike/used')` where the `request` column equals `_normalise({"company": brand, "model": model})`. Parse every offer's `price` via `parse_price`, drop `None`s, return the list. Must never raise — cache reads are best-effort; log and return `[]` on any failure.

### 3. `backend/app/main.py` — DB-first branch in `bike_search()`

Insert after the `get_cached` miss (`main.py:84`), before `enriched = req.enriched_query()`:

```python
if req.brand and req.model:
    db_bikes = find_bike_by_brand_model(req.brand, req.model)
    if db_bikes and req.price_max is not None:
        kept = []
        for b in db_bikes:
            prices = find_offer_prices(b.brand, b.model)
            # Decision 3: unknown price passes.
            if not prices or min(prices) <= req.price_max:
                kept.append(b)
        db_bikes = kept
    if db_bikes:
        enriched = req.enriched_query()
        logger.info("search served from DB | brand=%r model=%r bikes=%d",
                    req.brand, req.model, len(db_bikes))
        # Decision 5: deliberately no set_cached here.
        return BikeSearchResponse(search=enriched, bikes=db_bikes)
    # fall through to the AI pipeline
```

Add `find_bike_by_brand_model, find_offer_prices` to the `.store` import at `main.py:38`.

No schema changes. No API contract changes. `BikeSearchResponse` shape is identical — only `len(bikes)` may differ from 5.

## Testing

Unit tests for `parse_price` (no server needed) plus smoke tests appended to `backend/scripts/test_search.py`, run against a live local backend:

1. **DB hit** — search a brand+model known to be in `search_cache` → 200, bikes non-empty, every result matches the requested brand+model, response fast (no AI latency).
2. **AI fallback** — unknown brand+model → 200, falls through to the AI pipeline, still returns bikes.
3. **Stale row falls through** — a `search_cache` row older than 24 h is not served; request hits AI instead. (Replaces the dropped hybrid-merge test.)
4. **price_max gates a DB hit** — `trek/marlin 5` (cheapest joined offer 1000 zł) with `price_max=2000` → kept; with `price_max=500` → filtered out, falls through to AI.
5. **Unknown price is lenient** — a brand+model with no offer rows plus `price_max` → still returned.
6. **No regression** — existing smoke tests still pass; generic cache path unchanged.

## Documentation updates

- **`backend/README.md`** — new `## Search Cache` section documenting the three-step cascade, the offer join, and explicitly which filters are and are not honoured on the DB path.
- **`CLAUDE.md`** — update the `POST /v1/bike/search` description with the DB-first behaviour and the `store.py` row to mention both new helpers; add `app/price_parse.py` to the backend layer table.

## Files changed

| File | Change |
|---|---|
| `backend/app/price_parse.py` | NEW — price string parser |
| `backend/app/store.py` | +2 helpers |
| `backend/app/main.py` | +~15 lines in `bike_search()`, +1 import |
| `backend/scripts/test_search.py` | +6 tests |
| `backend/README.md` | new Search Cache section |
| `CLAUDE.md` | endpoint + layer table updates |

## Success criteria

- Brand+model provided → DB checked before any AI call
- DB hit → returns only the matching bikes, no AI call, no `set_cached`
- `price_max` honoured via the offer join, cheapest-across-sources, lenient on unknown
- DB miss / all-filtered / stale → falls back to the AI pipeline unchanged
- Filters with no backing data are documented as not gated, not silently ignored
- All smoke tests pass; no regression in the generic cache path
- Response format identical (`BikeSearchResponse`)

## Rollback

Delete the branch in `bike_search()`, the two helpers in `store.py`, and `price_parse.py`. The endpoint reverts to the AI-only pipeline.

---

**Created:** 2026-07-22
**Design resolved:** 2026-07-23 (interview — see Decisions table)
**Assigned to:** coder (implement), tester (verify), reviewer (approve)
