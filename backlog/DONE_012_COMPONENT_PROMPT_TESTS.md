# TODO-012 — Component-Search Prompt Tests

## Goal
Add tests that validate the quality/shape of the component-search prompts (`app/prompts/bike_details_*.md`) driven by `bike_details_finder.py`, beyond the existing HTTP-200 smoke test.

## Behaviour
- For a small set of known bikes (e.g. Canyon Grizl CF 7, Trek Marlin 5), assert the `/v1/bike/details` response:
  - returns the expected 8 component categories (Frame → Accessories) when data exists,
  - each category has well-formed elements/specs (non-empty names; no leaked code fences / raw JSON wrappers),
  - graceful skip (not 502) when a category's output is unparseable.
- Prompt-level (optional): assert prompts request the agreed JSON schema (per `app/prompts/bike_details.md`).

## Scope
- `backend/scripts/test_details.py` — extend with the assertions above (per-endpoint script; the aggregate smoke run stays in `test_search.py`).
- No app code change unless a prompt bug is found.

## Open questions / Notes
- Is an occasionally-empty category acceptable (real web-data gaps)? i.e. test resilience/shape, not exact content. (default: yes — assert shape, not exact specs)
- Which fixed reference bikes to standardise on?

## Acceptance criteria
- [ ] Test runs against a live server and asserts component shape for ≥2 reference bikes.
- [ ] Asserts no raw JSON / code-fence leakage in fields.
- [ ] Asserts graceful handling of a category with no data.
