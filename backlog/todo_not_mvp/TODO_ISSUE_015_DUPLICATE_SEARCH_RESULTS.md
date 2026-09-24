# ISSUE-015 — Search returns duplicated bikes; results must be distinct by brand + model

**Type:** bug
**Area:** backend (`backend/app/bike_finder.py`, `backend/app/main.py`)
**Severity:** medium — the user gets fewer than 5 usable suggestions and the list looks broken

## Symptom

`POST /v1/bike/search` can return the same bike twice (or more) in the `bikes[]` array — the same
brand + model, usually with a different `match_score` and a different explanation, because each
copy came from a different category. Five slots, but only three distinct bikes.

Casing/whitespace differences make it worse: `Trek` / `trek`, `Marlin 5` / `Marlin  5` read as two
bikes to the frontend even though they are one.

## Steps to reproduce

1. Backend on :8000 with a cold `cache.db`
2. `POST /v1/bike/search` with `{"search": "trail bike for commuting"}`
3. The query scores high on both **Mountain (MTB)** and **Hybrid / Commuter**, so both categories
   run a bike-finding call → both propose e.g. `Trek Marlin 5`
4. The response contains `Trek Marlin 5` twice

## Root cause

`backend/app/bike_finder.py:103-109` — `find_all_bikes()` fans out one Claude call per qualifying
category via `asyncio.gather` and then flattens the results:

```python
results = await asyncio.gather(*tasks)
return [bike for category_bikes in results for bike in category_bikes]
```

Each category call is independent and has no idea what the others returned, so overlapping
categories (Mountain/Hybrid, Gravel/Cyclocross, Touring/Hybrid, any of them vs Electric) routinely
name the same popular model. Nothing between that flatten and the response in
`backend/app/main.py:156-166` removes the repeats — the list goes straight into
`BikeSearchResponse`, into `set_cached()`, and into `save_search()`, so the duplicate is persisted
as well as returned.

The DB-first branch is **not** affected: `store.py:_find_rated_bikes` already dedupes on
`(_norm(brand), _norm(model))` (`store.py:187-195`). This issue is about making the AI pipeline
behave the same way.

## Expected behaviour

`bikes[]` is distinct by **normalised brand + normalised model** (`strip().lower()`, matching
`models.norm()` / `store._norm()` — Python-side, never SQL `lower()`, so non-ASCII brands like
`RIESE & MÜLLER` collapse correctly).

- When two categories propose the same bike, keep **one** entry: the one with the higher
  `match_score`. On a tie, keep the first in the existing order so ranking stays stable.
- The kept entry keeps its own `explanation` and `accessories` — do not merge or concatenate.
- Ordering is otherwise unchanged: the surviving bikes stay in the score-weighted order the
  allocation produced, so `position` in `bike_results` still means what it meant.
- Deduplication happens **before** `set_cached()` and `save_search()`, so neither the generic cache
  nor `bike_results` ever stores a duplicate pair.
- Returning fewer than 5 bikes is acceptable — do **not** backfill with extra Claude calls.
- Log the collapse at INFO when anything was dropped, e.g.
  `dedup | requested=5 returned=4 dropped=1`.

## Implementation notes

- Do it in `find_all_bikes()` (`bike_finder.py:103`), right after the flatten — that keeps it in
  one place and covers every caller of the AI pipeline.
- Keep-highest-score means a single pass with a `dict[tuple[str, str], BikeResult]`, replacing the
  stored bike only when the new `match_score` is strictly greater, then returning `list(...values())`
  — insertion order preserves the original ranking for survivors.
- The generic-cache hit path (`main.py:81-87`) replays whatever was stored earlier, so rows written
  before this fix can still serve duplicates. That is acceptable — those entries age out; no
  migration is needed. Do not add a dedup pass on the hit path just for that.
- Frontend needs no change: `ResultCard` renders whatever the array holds.

## Acceptance criteria

- [ ] A search whose top categories overlap returns no two bikes with the same normalised
      brand + model
- [ ] The surviving copy of a duplicated bike is the one with the higher `match_score`
- [ ] `Trek` / `trek` and `Marlin 5` / `marlin 5 ` are treated as the same bike
- [ ] Remaining bikes keep their relative score-weighted order
- [ ] `bike_results` rows written by `save_search()` contain no duplicate brand+model for one search
- [ ] A search returning 4 distinct bikes instead of 5 is not padded out with extra AI calls
- [ ] Smoke test in `backend/scripts/test_search.py` asserts the returned `bikes[]` has no repeated
      `(brand.strip().lower(), model.strip().lower())` pair
