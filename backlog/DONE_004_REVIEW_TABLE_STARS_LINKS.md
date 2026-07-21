# TODO-004 — Review Section: Star Rating + Source Table

## Goal
Adjust the review section layout so the existing text (score explanation) stays on the left, and a table of individual source reviews (with star rating and clickable link) appears on the right.

## Behaviour
- Left column: current score + explanation text (unchanged).
- Right column: table with one row per source URL from `ref[]`.
  - Columns: star icon(s) | source domain (e.g. "bikemagazine.com") | "Read review →" link.
  - Stars are decorative / inferred from the aggregate score — show the same integer score as filled stars (out of 5, mapped from 0–10).
- Layout: side-by-side on md+ screens; stacked on mobile (text above, table below).

## Scope
### Frontend
- `src/components/BikeDetailsView.tsx` — refactor `ReviewSection` into a two-column layout.
- No API or type changes needed (`BikeReviewResponse` already has `score`, `explanation`, `ref: string[]`).

## Acceptance criteria
- [ ] Explanation text visible on left.
- [ ] Table on right lists one row per `ref` URL.
- [ ] Each row has stars and a working external link.
- [ ] Responsive: stacks vertically on mobile.
