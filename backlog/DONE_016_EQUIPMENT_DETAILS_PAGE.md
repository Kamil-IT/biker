# TODO-016 — Bike Equipment Details Page

## Goal
Add a new **equipment** details page — the gear counterpart to the existing bike details
feature — covering helmets, lights & electronics, locks & security, and apparel / bags /
accessories. For a given equipment item the page shows: a plain-text **overview**, a
**spec sheet** (reusing the bike component tree), **photos**, and an **expert review**.

**Hard constraint:** NO links to shopping offers anywhere. There are deliberately **no**
equipment equivalents of `/v1/bike/offer`, `/v1/bike/used`, or `/v1/bike/ceneo`. Review
**source** links (forums / review sites) are allowed — only buy/offer links are forbidden.

Mirrors the existing pipeline; builds on `/v1/bike/details` + `/v1/bike/review`.

## Entry point
Brand + product name lookup, exactly like bike details:
```
POST /v1/equipment/details   { "company": "POC", "model": "Octal MIPS", "category": "helmets" }
POST /v1/equipment/review    { "company": "POC", "model": "Octal MIPS" }
```
No relevance-scoring / search phase — the item is identified directly by company + model.
`category` is optional; if omitted the details finder infers it.

## Equipment categories
All four, each with its own component-search prompt (like `bike_details_{slug}.md`):
- **Helmets** — fit system, MIPS, weight, certification, ventilation
- **Lights & electronics** — lumens, battery/run time, mount, bike computers
- **Locks & security** — lock type, security rating, weight, dimensions
- **Apparel, bags & accessories** — jerseys, gloves, shoes, panniers, racks, pumps, tools, bottle cages

Register these in a new `app/equipment_categories.py` (mirrors `app/categories.py`).

## Behaviour
- `POST /v1/equipment/details` runs in parallel via `asyncio.gather` (mirrors bike details):
  1. **Spec finder** — `claude-haiku-4-5-20251001` + `web_search_20250305`, one focused
     search per relevant equipment component group, using per-category prompts. Returns the
     **same component tree** as bikes (category → subcategory → element → spec /
     `BikeCategory` → `BikeSubcategory` → `ComponentElement` → `SpecItem`).
  2. **Overview finder** — single `web_search` call, 4–5 sentence plain-text overview
     (mirror `bike_description_finder.py` + prompt caching).
  3. **Photos finder** — find manufacturer product page URL, then Playwright (`headless=False`)
     scrapes up to 8 product `<img>` URLs (mirror `bike_photos_finder.py`).
  - Returns `{ company, model, category, description, components: [...], photos: [url, ...] }`.
  - On per-category JSON parse error: log + skip that category — never 502.
- `POST /v1/equipment/review` — single `web_search` call, 3–5 reviews synthesised into
  `{ score: int 0–10, explanation: str, ref: [url, ...] }` (mirror `bike_review_finder.py`).
  Source links allowed (review/forum), no offer links. On parse error: `{ score: 0,
  explanation: "Review unavailable.", ref: [] }` — never 502.

## SQLite cache (required — see CLAUDE.md)
Both endpoints must use `app/cache.py` on the happy path:
- `/v1/equipment/details`: key on `{company, model, category}`; **always** cache (empty valid).
- `/v1/equipment/review`: key on `{company, model}`; cache **only if `result.ref`** is non-empty.
Never cache error/fallback responses.

## Scope
### Backend
- `app/schemas.py` — `EquipmentDetailsRequest`, `EquipmentDetailsResponse`,
  `EquipmentReviewRequest`, `EquipmentReviewResponse` (reuse `BikeCategory` /
  `ComponentElement` / `SpecItem` for the tree).
- `app/equipment_categories.py` — 4-category registry, loads prompt files at startup.
- `app/equipment_details_finder.py` — per-category web_search loop + aggregation + token logging.
- `app/equipment_description_finder.py` — single web_search overview.
- `app/equipment_photos_finder.py` — manufacturer page → Playwright photo scrape.
- `app/equipment_review_finder.py` — single web_search review synthesis.
- `app/prompts/` — `equipment_details_{slug}.md` (×4), `equipment_description.md`,
  `equipment_photos.md`, `equipment_review.md`.
- `app/main.py` — wire `POST /v1/equipment/details` + `POST /v1/equipment/review` with cache.
- `backend/scripts/test_equipment.py` — smoke tests asserting HTTP 200 for both endpoints;
  also add an assertion in `scripts/test_search.py` per the "single smoke-test file" rule.
- `backend/README.md` — add both endpoints to `## Endpoints` with raw HTTP example + **Flow** list.

### Frontend
- `src/types.ts` — `EquipmentDetailsResponse`, `EquipmentReviewResponse`, request payloads.
- `src/components/EquipmentDetailsView.tsx` — full spec page reusing `BikeDetailsView`
  building blocks (DescriptionCard, ReviewSection, component tree, photo gallery, shimmer
  skeleton, error + retry). **No** OffersSection / UsedBikesSection.
- An entry point into the page (e.g. an "Equipment" tab / lookup form in `src/App.tsx`),
  matching the Café Rider design system.
- `frontend/README.md` — document the new view + API integration.

## Documentation
Per CLAUDE.md update policy: `CLAUDE.md`, `README.md`, `backend/README.md`,
`frontend/README.md` after implementation.

## Open questions / Notes
- Combined vs split: this task splits details and review into two endpoints to mirror bikes
  exactly. Could collapse review into the details response later if the extra round-trip hurts.
- Frontend entry UX (tab vs separate route vs link from a bike's accessories) is left to the
  designer — propose before building.

## Acceptance criteria
- [ ] `POST /v1/equipment/details` returns overview + component-tree specs + photos for all 4 categories.
- [ ] `POST /v1/equipment/review` returns score (0–10) + explanation + source refs.
- [ ] No offer/buy links anywhere in either response or the UI.
- [ ] Cache hit on repeat calls (details always; review only when non-empty).
- [ ] Smoke tests pass (HTTP 200); README + frontend + CLAUDE.md updated.
