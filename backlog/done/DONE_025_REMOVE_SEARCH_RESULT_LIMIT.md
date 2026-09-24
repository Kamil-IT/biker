# TODO-025 — Remove the 5-bike limit from search

## Goal
`POST /v1/bike/search` must not work with a fixed number of bikes anywhere. It returns **as many bikes as it finds**:
every DB match, or every AI match. The only rule is **at least 1 result**. Builds on TODO-024 (DB first, one AI call).

## Decisions (agreed 2026-09-23)
1. **No upper limit anywhere.** Remove it from the backend (`TOTAL_BIKES`, `bikes[:TOTAL_BIKES]`, "Find up to N" in the
   user message, "normally 5" in the prompt) and from the frontend (5 loading skeletons).
2. **Minimum 1.** When nothing meets every filter, the AI returns the **closest** bike instead of an empty array. That bike
   gets a low `match_score`, and its `explanation` names which filter it misses (e.g. "Trek does not offer this e-bike with rim brakes").
3. **Still one AI call.** No second call with relaxed filters.
4. **Empty list only on failure.** `bikes: []` is returned only on a parse error or when the JSON is unusable. The frontend
   then shows a "Not found" message instead of an empty result list.

## Behaviour
```
POST /v1/bike/search
  1. generic cache (get_cached)          → hit: return (unchanged)
  2. DB details search                   → ≥1 bike: return ALL matches (no cap)
  3. ONE Claude call                     → ALL matching bikes, min 1 (closest match if none fit)
     → set_cached + save_search only when bikes is non-empty
```

## Scope
**Backend**
- `backend/app/bike_finder.py`: remove `TOTAL_BIKES` and the `[:TOTAL_BIKES]` slice. The user message becomes just
  `User search: …`. Raise `max_tokens` (currently 2000) so a longer list does not cut the JSON off mid-array. Log a
  warning when `stop_reason == "max_tokens"`.
- `backend/app/prompts/bike_search.md`: replace "up to the number of bikes requested (normally 5)" with "every real
  bike that matches". Replace "return fewer bikes or an empty array" with "return at least one bike: the closest match,
  with a low `match_score` and an explanation of which filter it misses". Keep "never invent models".
- `backend/app/repository.py` `find_bikes_by_details`: check there is no cap and that all matches are returned.
- `backend/app/main.py`: do not cache an empty AI result (`if bikes: set_cached(...)`), so a parse failure is not pinned.

**Frontend**
- `frontend/src/App.tsx:539`: loading skeletons no longer read as "5 results". Use a neutral fixed count (e.g. 3).
- `App.tsx`: when the search returns `bikes: []`, show a "Not found" message in the results section. Reuse the existing
  "Not found" warning style (`App.tsx:455`).
- `ResultCard` / `BikeSearchResponse`: no change.

**Docs**: `CLAUDE.md` ("Returns 5 bike results", "exactly 5 bikes"), `README.md`, `backend/README.md` (search endpoint +
Flow), `frontend/README.md`: replace "5 bikes" with "all found, min 1".

## Out of scope
- Second AI call / relaxed-filter retry
- Pagination or a `limit` request field
- `BikeSearchResponse` / `ResultCard` shape changes
- The 5-listing cap in `bike_used_finder.py` (OLX used offers is a different feature)

## Acceptance criteria
- [ ] No constant, slice or prompt text limits the search result count (`grep -rn "TOTAL_BIKES\|normally 5"` is empty).
- [ ] A DB query matching more than 5 bikes returns all of them.
- [ ] A broad AI query (e.g. `bike_type: Gravel`) can return more than 5 bikes, with valid JSON that is not truncated.
- [ ] An impossible filter combination (e.g. `Brand: Trek, Electric: yes, Brakes: rim`) returns ≥1 closest bike with
      a low `match_score` and an explanation naming the unmet filter.
- [ ] A forced parse error returns `bikes: []` (not a 502). It is not cached, and the frontend shows "Not found".
- [ ] The frontend renders 1, 5 and 10+ results correctly. Skeletons are not tied to 5.
- [ ] Smoke test in `backend/scripts/test_search.py` asserts `len(bikes) >= 1` instead of `== 5`.
- [ ] Docs updated (see Scope).
