# ISSUE-001 — Rider height not extracted from free-text search

## Problem
Free-text search does not populate the **Rider height (cm)** filter.

**Repro:** search
> "Szukam roweru na pordóże po wrocławiu na wałach. Chce zeby rower nie był za drogi ale zeby sie na nim dobrze jedzilo. Mam **185cm** wzrostu i waze 100kg"

Expected: `rider_height_cm = 185` populated in the filters panel. Actual: rider height stays empty.

## Root cause
The free-text parser does not know about `rider_height_cm`:
- `app/prompts/bike_parse.md` — field not listed in the extractor instructions.
- `app/bike_parser.py` (`parse_free_text`) — does not read `rider_height_cm` from the model JSON.
- `app/schemas.py` `ParseResponse` — has no `rider_height_cm` field.
- `frontend/src/App.tsx` (`handleSearch` parse-merge block, ~L84-94) — does not map a parsed height into `filters`.

Note: `SearchRequest`, `SearchFilters`, `enriched_query()` and the UI input already support `rider_height_cm` — only the **parse** path is missing it.

## Proposed fix
- Add `"rider_height_cm": integer (cm)` to `bike_parse.md` with an example (e.g. "185 cm wzrostu" → `185`).
- Add `rider_height_cm: Optional[int]` to `ParseResponse`.
- Read `data.get("rider_height_cm")` in `parse_free_text`.
- Merge it into `filters` in `App.tsx` (`String(parsed.rider_height_cm)`), and include in the `anyExtracted` check.

## Acceptance criteria
- [ ] The repro prompt populates Rider height = 185.
- [ ] Parser works for Polish phrasing ("Mam 185 cm wzrostu", "185cm").
- [ ] No regression when height is absent (field omitted).
