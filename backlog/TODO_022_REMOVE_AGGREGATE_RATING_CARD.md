# TODO-022 — Remove the "Aggregate rating" card from the review section

## Problem

The Expert Review section renders a separate sand-coloured card showing:

```
AGGREGATE RATING                    7.3 /10
Rating from 4 sources
```

It duplicates information the user already gets: the headline `score /10` sits in the
section header, and the per-source star rows below already convey how the sources rate
the bike. The card adds visual weight without adding information.

## Goal

Delete the aggregate-rating card. Everything else in the review section stays exactly as
it is — in particular the **Sources** table (stars | domain | "Read review →") is
untouched.

## Scope

**Frontend only.** No backend change.

`frontend/src/components/BikeDetailsShared.tsx` → `ReviewSection`:

1. Remove the `{hasRating && (...)}` block (currently lines ~167–187) that renders the
   `Aggregate rating` card.
2. Remove the now-unused `ratingPct` constant.
3. **Keep** `hasRating` and `starBasis` — the star count in each source row is still
   derived from the aggregate `rating` when present, falling back to `score` for
   equipment reviews (which have no `rating`). Do not change star behaviour.
4. Keep `rating` / `sources_used` on the `ReviewLike` interface and in `src/types.ts` —
   they are still consumed for the stars.

## Explicitly out of scope

- The backend `/v1/bike/review` response shape: `rating` and `sources_used` keep being
  computed and returned (`app/bike_review_finder.py`, weighting + disagreement logic
  from TODO-018 unchanged).
- The Sources table, `CitationChips`, the overview card, and the `EquipmentDetailsView`
  review rendering — all unchanged (they share `ReviewSection`, so the card disappears
  from equipment pages too, which is correct: equipment reviews never had one anyway
  since `hasRating` is false for them).

## Acceptance criteria

- The `AGGREGATE RATING` card no longer appears on a bike details page.
- The header still shows `Expert review` + `<score>/10`.
- The explanation paragraph and the full-width **Sources** table render as before, with
  the same star counts as today (stars still driven by `rating` when available).
- `cd frontend && npm run build` passes with no unused-variable errors.

## Verification

1. `cd frontend && npm run build`
2. Run backend + frontend, search a bike with several review sources (e.g. Trek Marlin 5),
   open its details page, and confirm the review section shows header → explanation →
   Sources table, with no aggregate card between explanation and header.

## Docs to update

- `CLAUDE.md` — the `BikeDetailsShared.tsx` row in the frontend table describes
  `ReviewSection` rendering the rating; adjust to say stars are derived from the
  aggregate `rating` but the rating itself is no longer displayed.
- `frontend/README.md` — same, if it mentions the aggregate rating card.

## Related

- `backlog/done/DONE_008_REMOVE_AGGREGATE_RATING_BAR.md` — removed the progress bar from
  the same card; this task removes what is left of it.
- `backlog/done/DONE_014_BIKE_RATING_FIELD.md` — introduced `rating` / `sources_used`.
- `backlog/done/DONE_004_REVIEW_TABLE_STARS_LINKS.md` — the Sources table that stays.
