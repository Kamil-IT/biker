# ISSUE-010 — Decathlon offers always empty for non-Decathlon brands

## Problem
`POST /v1/bike/decathlon` returns no offers whenever the requested bike is not a Decathlon house brand. Decathlon only sells its own brands (Rockrider, B'Twin, Triban, Van Rysel, Elops), so any third-party brand (Trek, Canyon, Giant, Specialized, …) can never have a match.

Example — input `{ "company": "Trek", "model": "FX 3 Disc" }` returns:
```json
{
    "offers": [],
    "info": "Trek FX 3 Disc is not available on Decathlon.pl. Decathlon specializes in their own bike brands (Rockrider, Btwin) rather than Trek bicycles."
}
```

Because most bikes searched in the app are third-party brands, the Decathlon section is empty almost every time — it spends a Claude `web_search` call and renders an empty/unhelpful section.

## Root cause
- `app/bike_offer_decathlon_finder.py` always runs the full `web_search` call regardless of brand.
- `app/prompts/bike_offer_decathlon.md` correctly returns `{"info": "<reason>", "offers": []}` when nothing matches — the logic is working, but the call is wasted for brands Decathlon doesn't carry.
- Frontend `BikeDetailsView` always renders a Decathlon `OffersSection`, so users see an empty block + the `info` reason for most bikes.

## Proposed fix (confirm preferred approach first)
Pick one:
- **Skip the call for non-Decathlon brands** — short-circuit in `find_decathlon_offers` (and/or the endpoint) when `company` is not in the Decathlon house-brand allowlist (`rockrider`, `b'twin` / `btwin` / `b-twin`, `triban`, `van rysel`, `elops`, `decathlon`). Return `{"offers": [], "info": "<brand> is not sold by Decathlon"}` without calling Claude — saves latency and tokens.
- **Hide the section in the UI** — when `offers` is empty, don't render the Decathlon `OffersSection` (apply consistently with Allegro/Ceneo empty states).
- Or both: skip the backend call AND hide the empty section.

## Acceptance criteria
- [ ] Searching a non-Decathlon brand no longer wastes a `web_search` call (if skip approach chosen).
- [ ] The UI does not show an empty/confusing Decathlon block for unsupported brands.
- [ ] Decathlon house brands (e.g. Rockrider ST 100) still return offers as before.
- [ ] Smoke test in `backend/scripts/test_offer.py` (or equivalent) covers both a house brand and a non-Decathlon brand.
