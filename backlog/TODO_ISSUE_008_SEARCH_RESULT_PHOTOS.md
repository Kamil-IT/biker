# ISSUE-008 — Missing photos on the main results page after search

## Problem
The search results list shows no bike images — each `ResultCard` is text-only (score, brand, model, accessories, explanation). Photos only appear later on the details page.

## Root cause
- Backend `BikeResult` (`app/schemas.py`) has no `photos`/`image` field, and `/v1/bike/search` (`app/bike_finder.py`) never fetches images.
- Frontend `ResultCard` (`frontend/src/components/ResultCard.tsx`) renders no image element; `Bike` type has no photo field.

A photo finder already exists for the details flow: `app/bike_photos_finder.py` (Claude web_search → Playwright scrape).

## Proposed fix (confirm cost/latency trade-off first)
- Add an optional `photo`/`photos` field to `BikeResult` and the `Bike` type.
- Populate a single thumbnail per result. Options:
  - reuse/lighten `bike_photos_finder.py` (likely too slow for 5 results inline — see ISSUE-004); or
  - lazy-load the thumbnail per card after results render (separate request), so the list shows immediately.
- Render the thumbnail in `ResultCard` (with graceful fallback when absent — keep current layout).
- Update `backend/README.md` + `frontend` docs and the search smoke test.

## Acceptance criteria
- [ ] Result cards show a bike thumbnail when available.
- [ ] Missing photo degrades gracefully (no broken image, layout intact).
- [ ] Search perceived latency not made worse (lazy-load or cache photos).
