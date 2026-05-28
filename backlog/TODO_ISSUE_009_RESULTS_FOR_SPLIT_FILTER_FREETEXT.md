# ISSUE-009 — "Results for" should be split into "Filter" and "Free text"

## Problem
The results header shows one run-on string that mixes structured filters and the free-text query:

> RESULTS FOR
> "Wheel size: 700c — Rower do jazdy po wrocławiu na 10km chce głownie na walach jezdzic"

The filter part (`Wheel size: 700c`) and the free text should be shown as two distinct, labelled sections — e.g. **Filter:** `Wheel size: 700c` and **Free text:** `Rower do jazdy…`.

## Root cause
The header renders `submittedQuery`, which is the backend's `enriched_query()` output — filters joined by `", "`, then `" — "`, then the free text (`app/schemas.py` `SearchRequest.enriched_query()`). `App.tsx` stores it as one string (`setSubmittedQuery(data.search)`, ~L126) and prints it verbatim in the "Results for" block (`src/App.tsx` ~L406-413).

## Proposed fix
Render the two parts separately. Cleanest option: don't rely on the round-tripped enriched string — `App.tsx` already holds the submitted `filters` and free-text `query` in state, so display:
- **Filter** — a readable summary of the active structured filters (reuse the same label formatting as `enriched_query`, or build a small client-side formatter).
- **Free text** — the raw `query` (omit this row when empty; omit the Filter row when no filters set).

Alternative (if state isn't convenient): split `submittedQuery` on the `" — "` delimiter — fragile, so prefer the state-based approach. If a backend change is acceptable, have `/v1/bike/search` return `filters_summary` and `search_text` separately instead of only the merged `search`.

## Acceptance criteria
- [ ] Filters and free text appear as two clearly labelled parts under "Results for".
- [ ] Filter-only search shows just the Filter part; free-text-only shows just the Free text part.
- [ ] No leftover `" — "` separator artifact in the UI.
