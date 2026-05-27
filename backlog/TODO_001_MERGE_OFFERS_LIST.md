# TODO-001 — Merge Ceneo and Allegro Offers Into One List

## Goal
Replace the two separate offer sections (Allegro + Ceneo) with a single unified "Offers" list on the bike details view.

## Behaviour
- Merge results from `POST /v1/bike/offer` (Allegro) and `POST /v1/bike/ceneo` (Ceneo) client-side.
- Sort the combined list by price ascending.
- Show a source badge on each card (e.g. "allegro.pl" / "ceneo.pl").
- Both API calls remain separate — merging is frontend-only.

## Scope
### Frontend
- `src/App.tsx` — combine `offerData` and `ceneoData` into one sorted array before passing to the view.
- `src/components/BikeDetailsView.tsx` — replace `OffersSection` × 2 with a single `OffersSection` fed the merged list; add source badge to each offer card.
- `src/types.ts` — `BikeOffer` already has `source: string`, no schema change needed.

### Backend
- No changes.

## Acceptance criteria
- [ ] Details view shows one "Offers" panel.
- [ ] Offers sorted cheapest first.
- [ ] Each offer card displays a source label.
- [ ] If one source returns no offers, the other still shows.
