# TODO-007 — Generic Offer Endpoint with Curated Site Allowlist

## Goal
Add a `POST /v1/bike/offers` endpoint that runs a single web search constrained to the curated allowlist from TODO-006 and returns a live list of offers for a bike model across multiple retailers/classifieds.

**Depends on:** TODO-006 (allowlist doc).

## Behaviour
- Input: `{ "company": "...", "model": "..." }` (reuse `BikeOfferRequest`).
- One `web_search_20250305` call (`claude-haiku-4-5-20251001`) with a system prompt that restricts results to the curated allowlist domains.
- Returns `BikeOfferResponse`: `{ offers: [{ brand, model, price, is_new, url, photos, source }], info }` — multiple offers; `source` = originating domain.
- Anthropic-API endpoint → **must use the SQLite cache** (`app/cache.py`) on the happy path only.
- On parse error: `{ offers: [], info: raw_text }` — never 502.

## Scope
### Backend
- `app/bike_offers_finder.py` — new finder (pattern: `bike_offer_ceneo_finder.py`).
- `app/prompts/bike_offers_generic.md` — system prompt embedding the allowlist domains.
- `app/main.py` — register `POST /v1/bike/offers` + cache wrapper.
- `backend/scripts/test_search.py` — smoke test (assert 200 + schema).
- `backend/README.md` — Endpoints section: HTTP example + Flow.
### Frontend (optional follow-up)
- `src/App.tsx` + `src/components/BikeDetailsView.tsx` — surface multi-source offers (or merge into the existing offers list per TODO-001).

## Acceptance criteria
- [ ] `POST /v1/bike/offers` → 200 with valid JSON.
- [ ] Results limited to allowlist domains.
- [ ] Cache hit on 2nd identical call (fast, identical JSON).
- [ ] Smoke test passes; README updated.
