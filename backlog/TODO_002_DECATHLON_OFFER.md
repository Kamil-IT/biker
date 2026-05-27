# TODO-002 — Add Decathlon Live Offer

## Goal
Add a new `POST /v1/bike/decathlon` endpoint that searches decathlon.pl for a matching bike offer, following the same pattern as the existing Ceneo endpoint.

## Behaviour
- Searches decathlon.pl for the best matching new bike offer.
- Returns 1 offer (or 0 if not found): brand, model, price, url, source = "decathlon.pl".
- No photos (decathlon.pl pages require JS rendering — skip for now).
- On parse error: returns `{ offers: [], info: raw_text }`.

## Scope
### Backend
- `app/bike_offer_decathlon_finder.py` — new finder, same structure as `bike_offer_ceneo_finder.py`.
- `app/prompts/bike_offer_decathlon.md` — system prompt targeting decathlon.pl search.
- `app/schemas.py` — reuse `BikeOfferRequest` / `BikeOfferResponse` (no new models needed).
- `app/main.py` — register `POST /v1/bike/decathlon` route.
- `backend/scripts/test_search.py` — add smoke test for the new endpoint.
- `backend/README.md` — add endpoint entry with HTTP example and Flow.

### Frontend
- `src/App.tsx` — add `decathlonData` state; call `/v1/bike/decathlon` alongside existing offer calls.
- `src/components/BikeDetailsView.tsx` — include Decathlon offers in the merged list (TODO-001 should land first, or merge all three here).
- `src/types.ts` — no change needed.

## Acceptance criteria
- [ ] `POST /v1/bike/decathlon` returns HTTP 200 with valid JSON.
- [ ] Smoke test passes.
- [ ] Offer appears in the merged offers list on the details view.
- [ ] Source badge shows "decathlon.pl".
