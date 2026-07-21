# TODO-010 — Amazon Offer Integration

## Goal
Add a `POST /v1/bike/amazon` endpoint returning bike offers from Amazon.

## Prerequisites
- Amazon developer account + auth: https://developer.amazon.com/docs/app-submission-api/auth.html
- Likely **PA-API 5.0** (Product Advertising API) credentials + Associate tag, or **SP-API** with LWA OAuth. Confirm which API exposes a product/offer search usable here.

## Behaviour
- Auth (LWA token / PA-API signed request).
- Search products by "<brand> <model> bike"; map to `BikeOffer`: brand, model, price, is_new, url, photos, source = "amazon".
- Returns `BikeOfferResponse`. On error / no creds: `{ offers: [], info }` — never 502.

## Scope
### Backend
- `app/bike_offer_amazon_finder.py` — new finder (httpx + request signing / LWA).
- `.env.example` — Amazon creds (access key, secret, partner/associate tag, region/marketplace).
- `app/main.py` — route + generic cache.
- `backend/scripts/test_search.py` — smoke test.
- `backend/README.md` — Endpoints + Flow.

## Open questions / Notes
- Which API: PA-API 5.0 vs SP-API? PA-API requires an active Associate account with qualifying sales.
- Marketplace/region: amazon.de vs amazon.pl (limited catalog) vs amazon.com.

## Acceptance criteria
- [ ] Auth / request signing works.
- [ ] Endpoint returns 200 with mapped offers (or empty + info without creds).
- [ ] Smoke test passes; README updated.
