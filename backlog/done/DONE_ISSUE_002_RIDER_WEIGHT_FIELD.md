# ISSUE-002 — Missing rider weight field

## Problem
There is no way to specify **rider weight**. It is relevant for frame/wheel/tyre recommendations and is commonly stated in queries.

**Repro:** the prompt "...Mam 185cm wzrostu i **waze 100kg**" — the 100 kg is ignored everywhere (no filter, no parse, not sent to the search pipeline).

## Root cause
`rider_weight_kg` does not exist anywhere — backend schema, enriched query, frontend filters, or parser.

## Proposed fix (end-to-end, mirror `rider_height_cm`)
### Backend
- `app/schemas.py` — add `rider_weight_kg: Optional[int]` to `SearchRequest` (+ `empty_int_to_none` validator + `at_least_one_field`), and to `ParseResponse`.
- `app/schemas.py` `enriched_query()` — append `Rider weight: {n} kg`.
- `app/main.py` — include `rider_weight_kg` in the SQLite cache key fields.
- `app/prompts/bike_parse.md` + `app/bike_parser.py` — extract weight ("waze 100kg" → `100`).
- `backend/README.md` — add field to `/v1/bike/search` request list.
### Frontend
- `src/types.ts` — add `rider_weight_kg` to `SearchFilters` (+ `EMPTY_FILTERS`) and `SearchPayload` and `ParseResponse`.
- `src/components/SearchInput.tsx` — add a "Rider weight (kg)" number input next to Rider height; include in `hasAny` + `buildPayload`.
- `src/App.tsx` — merge parsed weight into filters.

## Acceptance criteria
- [ ] "waze 100kg" populates Rider weight = 100.
- [ ] Weight participates in the enriched query and cache key.
- [ ] Smoke test in `backend/scripts/test_search.py` still passes.
