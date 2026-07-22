# TODO-008 — Allegro API Offer Integration

> ## 🟠 BLOCKED — no credentials
>
> Implemented in **PR [#42](https://github.com/Kamil-IT/biker/pull/42)** (draft), but the happy path is **unverifiable here**: `backend/.env` holds only `ANTHROPIC_API_KEY`.
>
> **Unblock by:** creating an Allegro developer app **and getting the application verified** — `GET /offers/listing` is restricted to verified applications — then setting `ALLEGRO_CLIENT_ID` / `ALLEGRO_CLIENT_SECRET`.
>
> **Fix on first real use:** the mapper sets `brand`/`model` from the *request*, so every offer comes back identical regardless of what was actually listed. `info` also conflates "credentials missing" with "token request failed". See `backlog/blocked/README.md`.
>
> Verified without credentials: graceful degradation (200 + empty + `info`), 422 validation, OAuth token reuse/refresh under mock, empty-result caching rule.

## Goal
Add a `POST /v1/bike/allegro` endpoint that fetches live bike offers from the official Allegro REST API (`api.allegro.pl`), in addition to the existing web-search Allegro path (`/v1/bike/offer`).

## Prerequisites
- Allegro developer app + OAuth2 credentials.
- ⚠️ The offer-listing endpoint (`GET /offers/listing`) requires a **verified** Allegro application — see https://developer.allegro.pl/news/get-offers-listing-tylko-dla-zweryfikowanych-aplikacji-GRax4oVgrs1 . Verification must clear before this works in production. Use the sandbox (`api.allegro.pl.allegrosandbox.pl`) for development.

## Behaviour
- OAuth2 client-credentials flow to obtain a token; cache the token until expiry.
- Query `GET /offers/listing?phrase="<brand> <model>"&category.id=<bikes>` (confirm the rowery category id).
- Map results to `BikeOffer`: brand, model, price, is_new (new/used), url, photos, source = "allegro.pl".
- Returns `BikeOfferResponse`. On error / missing creds: `{ offers: [], info }` — never 502.

## Scope
### Backend
- `app/bike_offer_allegro_api_finder.py` — new finder (httpx; **not** Anthropic API).
- `.env.example` — `ALLEGRO_CLIENT_ID`, `ALLEGRO_CLIENT_SECRET`.
- `app/main.py` — register route + generic cache (cache the mapped response).
- `backend/scripts/test_search.py` — smoke test.
- `backend/README.md` — Endpoints + Flow (note the OAuth token call + the listing call).

## Open questions / Notes
- Replace the web-search Allegro (`/v1/bike/offer`) or run alongside? (default: new route alongside)
- Confirm the bikes/rowery category id on Allegro.

## Acceptance criteria
- [ ] OAuth2 token obtained + cached until expiry.
- [ ] Endpoint returns 200 with mapped offers (or empty + info when unverified / no creds).
- [ ] Smoke test passes; README updated.
