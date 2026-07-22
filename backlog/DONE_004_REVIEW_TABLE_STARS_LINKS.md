# TODO-004 — Review Section: Star Rating + Source Table

## Goal
Adjust the review section layout so the existing text (score explanation) stays on the left, and a table of individual source reviews (with star rating and clickable link) appears on the right.

## Behaviour
- Left column: current score + explanation text (unchanged).
- Right column: table with one row per source URL from `ref[]`.
  - Columns: star icon(s) | source domain (e.g. "bikemagazine.com") | "Read review →" link.
  - Stars are decorative / inferred from the aggregate score — show the same integer score as filled stars (out of 5, mapped from 0–10).
- Layout: the table sits full-width **below** the explanation text at every width.
  (Revised from the original two-column plan — `ReviewSection` gained an aggregate
  rating bar and a `CitationChips` sources row in the meantime, and a right-hand
  column no longer fits alongside them.)

## Scope
### Frontend
- `src/components/BikeDetailsShared.tsx` — `ReviewSection` renders the source table
  in place of the `CitationChips` row it previously used.
- No API or type changes needed (`BikeReviewResponse` already has `score`, `explanation`, `ref: string[]`).

## Acceptance criteria
- [x] Explanation text visible above the table.
- [x] Table lists one row per `ref` URL.
- [x] Each row has stars and a working external link.
- [x] Responsive: readable at 390 px without horizontal overflow.
- [x] Degrades cleanly for equipment reviews, which carry no `rating` /
      `sources_used` — stars fall back to the headline score.
