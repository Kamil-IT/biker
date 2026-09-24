# TODO-027 — Frontend: "Request data" button in bike details sections

## Goal
In the bike details view, every section whose data is slow or missing shows a button that lets the user ask for that
data. The click calls `POST /v1/bike/missing` (TODO-026, which must be done first). Long term, most bikes (about p90)
should already be in the cache, so the button will mostly show up for bikes we really lack data for.

## Decisions (agreed 2026-09-24)
1. **Sections and `missing_type`**: a string enum constant in `frontend/src/types.ts`:
   `photos`, `description`, `components`, `review`, `offers_new`, `offers_used`. Each section works on its own.
2. **Flow per section**:
   - 0–5 s: spinner / current loading state.
   - After 5 s, if there is still no data: the spinner goes away and the button takes its place. The request keeps
     running in the background.
   - Data arrives (at any time): it replaces the button, even one that was already clicked.
   - Response is empty or an error: the button stays.
   - Data arrives within 5 s: the button never shows.
   It is expected that the button shows for almost every bike that is not cached yet (`/v1/bike/details` takes tens of seconds).
3. **Look**: not an illustration or graphic, just a well-styled button with a short line of text, matching the Café
   Rider design (`src/index.css` `@theme` tokens). Use a frontend design skill (e.g. `frontend-design`) for the styling.
   One shared component (e.g. `RequestDataButton`) that each section renders with its own `missing_type`.
4. **Copy (EN, like the rest of the UI)**: "We don't have this data yet" / "Request data" / "Requested ✓".
5. **Click**: `POST /v1/bike/missing` `{company, model, missing_type}` → button becomes "Requested ✓" and is disabled.
   This is plain component state, **no** `localStorage`, so after a page refresh the user can request again. If the POST
   fails, the button goes back to clickable.

## Scope
**Frontend**
- `src/types.ts`: `MissingType` enum/const + request/response types (`MissingDataRequest`, `MissingDataResponse`).
- New component `src/components/RequestDataButton.tsx`.
- `src/components/BikeDetailsView.tsx`: add the 5 s timer + button to `PhotoGallery`, `DescriptionCard`, the component
  tree, `ReviewSection`, and the Used / New cards in `MergedOffersSection`. Note: `MergedOffersSection` currently returns
  `null` when both lists are empty, so it must show the button instead. Shared pieces sit in `BikeDetailsShared.tsx`.
  Keep `EquipmentDetailsView` unchanged.
- `src/App.tsx` (or the component): the `POST /v1/bike/missing` call.

**Docs**: `frontend/README.md`, `README.md`, `CLAUDE.md` (frontend table + API integration list).

## Out of scope
- Equipment details view and the search screen
- Illustrations / SVG graphics
- Remembering requests after a refresh (`localStorage`)
- Changing loading times or caching
- Showing the request counter anywhere in the UI

## Acceptance criteria
- [ ] Uncached bike: each section shows a spinner for 5 s, then the button, while its request is still running.
- [ ] When a section's data arrives after the button appeared, the data replaces the button.
- [ ] Cached bike (data in < 5 s): no button appears.
- [ ] Empty or error response for a section: the button stays.
- [ ] Click → one `POST /v1/bike/missing` with the correct `missing_type` → "Requested ✓" and disabled.
- [ ] POST failure → button is clickable again.
- [ ] Used and New offer cards each have their own button (`offers_used` / `offers_new`).
- [ ] Button styling matches Café Rider. `npm run build` passes.
- [ ] Manual QA (`manual-tester`) in the browser.
- [ ] Docs updated (see Scope).
