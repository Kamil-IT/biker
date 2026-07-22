# TODO-014 — Bike Rank / Rating Field from Aggregated Reviews

## Goal
Add a bike rank/rating derived from aggregated forum/review data, surfaced in the review response and the UI.

**Depends on:** TODO-013 (curated sources). Builds on the existing `/v1/bike/review`.

## Behaviour
- Aggregate review signals from the curated sources (TODO-013) into a normalised rating (e.g. 0–10) plus a count of sources used.
- Extend `/v1/bike/review` with: `rating` (number), `sources_used` / `rating_count`; keep existing `score`, `explanation`, `ref`.
- Anthropic API + web_search → **must use the SQLite cache** on the happy path.

## Scope
### Backend
- `app/bike_review_finder.py` — extend to compute/return the aggregate rating.
- `app/prompts/bike_review.md` — incorporate the curated sources + ask for per-source scores.
- `app/schemas.py` — add fields to `BikeReviewResponse`.
- `backend/scripts/test_review.py` + `test_search.py` — assert the new field is present + in 0–10 range.
- `backend/README.md` — update the review endpoint schema.
### Frontend
- `src/types.ts` — extend `BikeReviewResponse`.
- `src/components/BikeDetailsView.tsx` — show the rating (stars / number) in `ReviewSection`.

## Open questions / Notes
- Relationship to the existing `score`? Proposal: `score` = synthesised single score; `rating` = aggregate across sources — or merge into one. Confirm before implementing.

## Acceptance criteria
- [ ] Review response includes an aggregate rating + source count.
- [ ] Rating in 0–10, derived from ≥3 sources when available.
- [ ] Cache hit on repeat call; tests + README + frontend updated.
