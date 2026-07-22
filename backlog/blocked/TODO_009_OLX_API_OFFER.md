# TODO-009 — OLX Official API Offer Integration

> ## 🟠 BLOCKED — no credentials, plus a known OAuth bug
>
> Implemented in **PR [#43](https://github.com/Kamil-IT/biker/pull/43)** (draft), but the happy path is **unverifiable here**: `backend/.env` holds only `ANTHROPIC_API_KEY`.
>
> **Unblock by:** OLX developer account approval (was pending), then setting `OLX_CLIENT_ID` / `OLX_CLIENT_SECRET`.
>
> **Fix on first real use — this one is the most likely to fail immediately:**
> - OAuth credentials are posted as a **JSON body**; most client-credentials servers expect `application/x-www-form-urlencoded` (which TODO-008 correctly does). The mock cannot catch this, because it accepts whatever is sent.
> - `OLX_ENV` is a **no-op** — `_HOSTS` maps both `production` and `sandbox` to the same `www.olx.pl`.
> - The mapper sets `brand`/`model` from the *request*, so every listing looks identical — worst here, since size/year/condition is exactly what distinguishes used listings.
>
> See `backlog/blocked/README.md`. Verified without credentials: graceful degradation (200 + empty + `info`), 422 validation, OAuth token reuse/refresh under mock, empty-result caching rule.

## Goal
Add live used-bike offers from the official OLX API, complementing the existing web-search + Playwright path (`/v1/bike/used`).

## Prerequisites
- OLX developer account approval (NEXT_STEPS: "waiting for account approval") + OAuth2 credentials.

## Behaviour
- OAuth2 to obtain a token (cache until expiry).
- Query OLX listings API by phrase "<brand> <model>" within the bikes category, location PL.
- Map to `BikeOffer`: brand, model, price, is_new (used), url, photos, source = "olx.pl", `city`.
- Returns a `UsedBikeResponse`-compatible shape. On error / no creds: `{ offers: [], info }` — never 502.

## Scope
### Backend
- `app/bike_used_api_finder.py` — new finder (httpx).
- `.env.example` — `OLX_CLIENT_ID`, `OLX_CLIENT_SECRET`.
- `app/main.py` — new route (e.g. `POST /v1/bike/used-api`) + generic cache.
- `backend/scripts/test_search.py` — smoke test.
- `backend/README.md` — Endpoints + Flow.

## Open questions / Notes
- Replace the Playwright `/v1/bike/used` scraper or run alongside? (default: alongside; prefer API when creds present)
- Confirm the OLX API returns photo URLs directly (avoids Playwright in `olx_image_fetcher.py`).

## Acceptance criteria
- [ ] OAuth2 token obtained + cached.
- [ ] Endpoint returns 200 with mapped used listings (or empty + info without approval).
- [ ] Smoke test passes; README updated.
