# ISSUE-005 — Non-bike results are not excluded (e.g. "Tesla Model S Plaid")

## Problem
Search returns results that are not bicycles. A "Tesla Model S Plaid" card appears with score **0 / 10**, "No match", and explanation "Tesla manufactures electric vehicles, not bicycles…". A 0-score non-bike should never be shown.

This happens when the user constrains by a non-bike brand (see ISSUE-003: "Firma tylko tesla").

## Root cause
`app/bike_finder.py` `find_bikes_for_category` trusts whatever the model returns and builds a `BikeResult` for every item, including ones the model itself flags as non-bikes / `match_score == 0`. There is no post-filter, and `find_all_bikes` returns them as-is.

## Proposed fix
- In `find_all_bikes` (or `find_bikes_for_category`), drop results with `match_score == 0` (and/or that the model marks as not-a-bicycle).
- When a constraining brand yields no real bikes, return an empty list with a clear `info`/empty-state rather than a placeholder non-bike — the frontend should show a "no matching bikes for brand X" empty state.
- Optionally reinforce in `bike_search_{slug}.md` prompts: "Only return actual bicycles; if the brand does not make bicycles, return an empty array."

## Acceptance criteria
- [ ] "Firma tylko tesla" no longer shows a Tesla car card.
- [ ] Zero-score / non-bicycle entries are filtered out before reaching the UI.
- [ ] Empty result set renders a friendly empty state, not a 502.
