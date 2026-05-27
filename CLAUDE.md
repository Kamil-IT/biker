# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agent Policy

**Before implementing any multi-step task**, always call `mcp__ruflo__hooks_pre-task` with the task ID and description. It returns agent role suggestions — spawn those agents via `mcp__ruflo__agent_spawn` before writing code. Example flow:

1. `mcp__ruflo__hooks_pre-task` — get agent suggestions for this task
2. `mcp__ruflo__agent_spawn` — spawn one agent per suggested role (e.g. `backend-impl`, `tester`)
3. `mcp__ruflo__task_create` — register the task
4. Implement, then `mcp__ruflo__task_complete` when done

## Backlog

Tasks are tracked in `/backlog/`. Naming convention:

- `TODO_<ID>_<TASK_NAME>.md` — task not yet started
- `DONE_<ID>_<TASK_NAME>.md` — completed task (rename the file, don't delete it)

When picking up a task: read its file, implement, then rename `TODO_` → `DONE_`.
When creating a new task: ask clarifying questions first, then write the file.

## Development Rules

**New backend endpoint** → add a smoke test for it in `backend/scripts/test_search.py`. This is the single file for all smoke tests. Each test must call the endpoint against a running local server and assert HTTP 200.

**New backend endpoint using the Anthropic API** → must use the SQLite cache in `app/cache.py`. Pattern:
```python
_fields = {"key_field": req.key_field}  # only fields that uniquely identify the response
cached = get_cached("/v1/your/route", _fields, YourResponseModel)
if cached is not None:
    return cached
# ... existing logic ...
set_cached("/v1/your/route", _fields, result)
return result
```
Only call `set_cached` on the happy path — never cache error/fallback responses.

## Documentation Update Policy

After **every code change**, review and update the relevant documentation before considering the task done:

| What changed | Files to review & update |
|---|---|
| Any change | `CLAUDE.md` · `README.md` |
| Backend (`/backend/**`) | `backend/README.md` · `README.md` · `CLAUDE.md` |
| Frontend (`/frontend/**`) | `frontend/README.md` · `README.md` · `CLAUDE.md` |

Update only the sections that are actually affected — do not rewrite docs that remain accurate.

**`backend/README.md` must always contain an `## Endpoints` section** with every endpoint listed, including:
- A raw HTTP request example (`POST http://localhost:8000/...` with `Content-Type` and JSON body)
- A **Flow** list of every outbound HTTP call made (exact URL, service name, and how many times / in what order)

## Project Overview

Monorepo with separate backend and frontend applications:
- `/backend` — Python REST API (FastAPI)
- `/frontend` — React + TypeScript + Tailwind v4 SPA (Vite)

## Backend Setup

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then edit .env with your real ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8000
```

```bash
# In a second terminal — smoke test the endpoint:
python scripts/test_search.py
```

- **API docs**: http://localhost:8000/docs (auto-generated OpenAPI UI)
- **Python version**: 3.14

## Frontend Setup

```bash
cd frontend
npm install
npm run dev       # dev server on http://localhost:5173
```

```bash
npm run build     # production build → dist/
npm run preview   # serve production build locally
```

- **Dev server**: http://localhost:5173 — requires the backend to be running on port 8000 (Vite proxies `/v1/*` → `http://localhost:8000`)
- **Node version**: v24 / npm 11

## Parallel Development (Worktrees)

Work on multiple features simultaneously — each in its own directory, its own branch, without stashing.

```
C:\Users\kamil_wolny\Projects\
├── biker\             ← main branch (always here)
└── biker-wt\
    ├── feature-xyz\   ← feature/xyz branch
    └── fix-abc\       ← fix/abc branch
```

**Create a new worktree:** `/new-worktree feature/my-feature`
**Check what's running:** `/worktree-status`
**Remove when done:** `git worktree remove C:\Users\kamil_wolny\Projects\biker-wt\feature-my-feature`

Each worktree shares `node_modules` and `.venv` via Junction symlinks (created automatically by `/new-worktree`). If your branch adds new packages, break the junction and run install fresh — the command output explains how.

**Port convention** (for running two worktrees simultaneously):

| Worktree | Backend | Frontend |
|----------|---------|----------|
| `biker\` (main) | 8000 | 5173 |
| first worktree | 8001 | 5174 |
| second worktree | 8002 | 5175 |

## Architecture

### Backend (`/backend`)

| Layer | File | Responsibility |
|-------|------|----------------|
| Entry point | `app/main.py` | FastAPI app, routes, request logging |
| Schemas | `app/schemas.py` | Pydantic models: `SearchRequest`, `CategoryResult`, `SearchResponse`, `BikeResult`, `BikeSearchResponse`, `BikeDetailsRequest`, `BikeDetailsResponse`, `BikeCategory`, `BikeSubcategory`, `ComponentElement`, `SpecItem`, `BikeReviewRequest`, `BikeReviewResponse`, `BikeOffer`, `BikeOfferRequest`, `BikeOfferResponse`, `UsedBikeRequest`, `UsedBikeResponse` |
| Categories | `app/categories.py` | 11 bike category registry; loads prompt files at startup |
| Prompts | `app/prompts/*.md` | Per-category scoring prompts + `bike_search_{slug}.md` per-category bike-finding prompts + `bike_details_{slug}.md` per-category component search prompts (8 categories) + `bike_details.md` JSON format reference |
| Scorer | `app/anthropic_scorer.py` | Calls Claude Haiku per category, strips code fences, parses JSON |
| Bike finder | `app/bike_finder.py` | Filters top categories, allocates 5 bikes by score weight, finds real bikes via Claude in parallel |
| Details finder | `app/bike_details_finder.py` | Loops through 8 component categories (Frame → Accessories), runs one focused `web_search` call per category, aggregates results; logs per-iteration and total token usage |
| Description finder | `app/bike_description_finder.py` | Single `web_search` call with prompt caching to generate a 4–5 sentence plain-text bike overview; runs in parallel with details finder |
| Review finder | `app/bike_review_finder.py` | Single `web_search` call to find 3–5 reviews, synthesises score 0–10, explanation, and source URLs |
| Offer finder | `app/bike_offer_finder.py` | Single `web_search` call to find 1 current offer on allegro.pl |
| Used bikes finder | `app/bike_used_finder.py` | Single `web_search` call to find up to 5 used listings on olx.pl with cascade fallback; then Playwright scrapes photos via `olx_image_fetcher.py` |
| OLX image fetcher | `app/olx_image_fetcher.py` | Playwright (headless=False) scrapes up to 4 `<img>` URLs from each OLX listing URL using `*.apollo.olxcdn.com` regex |
| Ceneo finder | `app/bike_offer_ceneo_finder.py` | Single `web_search` call to find 1 current offer on ceneo.pl |
| Photos finder | `app/bike_photos_finder.py` | Two-step: (1) Claude `web_search` to find manufacturer product page URL, (2) Playwright (`headless=False`) scrapes up to 8 product `<img>` URLs from rendered page; runs in parallel with details and description finders |
| Test scripts | `scripts/test_search.py` · `scripts/test_details.py` · `scripts/test_review.py` · `scripts/test_offer.py` | Smoke tests for each endpoint |

**Endpoint** `POST /v1/bike/search`
- Request: all fields optional, at least one required — `search` (free text), `brand`, `model`, `year` (int), `wheel_size` (string), `is_electric` (bool), `has_suspension` (bool), `is_kids` (bool)
- Structured fields are assembled into an enriched query string via `SearchRequest.enriched_query()` (e.g. `"Brand: Trek, Year: 2023 — trail riding"`), then passed through the existing pipeline
- Phase 1: Calls `claude-haiku-4-5-20251001` once per category (11 sequential calls) to score relevance against the enriched query
- Phase 2: Filters to categories with score ≥ 5 (minimum 2); allocates exactly 5 bikes weighted by score
- Phase 3: Calls Claude in parallel (one call per qualifying category) to find real bikes
- Returns 5 bike results with brand, model, accessories, match score, and explanation; `search` field in response contains the enriched query
- On parse error: returns empty list for that category — never returns 502 for bad JSON

**Endpoint** `POST /v1/bike/details`
- Request: `{"company": "Canyon", "model": "Grizl CF 7 ESC"}`
- Runs three calls in parallel via `asyncio.gather`:
  1. `claude-haiku-4-5-20251001` with `web_search_20250305` **8 times** sequentially — one focused search per component category (Frame, Drivetrain, Brakes, Wheels, Cockpit, Saddle & Seatpost, Lighting, Accessories), each using a dedicated `app/prompts/bike_details_{slug}.md` system prompt
  2. `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — generates a 4–5 sentence plain-text overview using `app/prompts/bike_description.md` with prompt caching on the system prompt
  3. `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — finds the official manufacturer product page URL, then Playwright (`headless=False`) scrapes up to 8 product `<img>` URLs from the rendered page; uses `app/prompts/bike_photos.md`
- Returns: `{ company, model, description: str, components: [...], photos: [url, ...] }`
- On JSON parse error for a category: logs the error and skips that category — never returns 502

**Endpoint** `POST /v1/bike/review`
- Request: `{"company": "Canyon", "model": "Grizl CF 7 ESC"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches for 3–5 professional and user reviews, using `app/prompts/bike_review.md` as the system prompt
- Returns `{ score: int (0–10), explanation: str (5–10 sentences), ref: [url, ...] }`
- On JSON parse error: returns `{ score: 0, explanation: "Review unavailable.", ref: [] }` — never returns 502

**Endpoint** `POST /v1/bike/offer`
- Request: `{"company": "Canyon", "model": "Grizl CF 7 ESC"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches allegro.pl using `app/prompts/bike_offer_allegro.md` as the system prompt
- Returns `{ offers: [{ brand, model, price, is_new, url, photos, source }], info: str }` (1 offer)
- On JSON parse error: returns `{ offers: [], info: raw_text }` — never returns 502

**Endpoint** `POST /v1/bike/used`
- Request: `{"company": "Trek", "model": "Marlin 5"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches olx.pl using `app/prompts/bike_offer_olx.md` as the system prompt; cascade fallback (exact → model-family → brand/category)
- Then Playwright (headless=False) fetches up to 4 photo URLs per listing from OLX CDN
- Returns `{ offers: [{ brand, model, price, is_new, url, photos, source, city }], info: str }` (up to 5 listings, always used)
- On JSON parse error: returns `{ offers: [], info: raw_text }` — never returns 502

**Endpoint** `POST /v1/bike/ceneo`
- Request: `{"company": "Canyon", "model": "Grizl CF 7 ESC"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches ceneo.pl using `app/prompts/bike_offer_ceneo.md` as the system prompt
- Returns `{ offers: [{ brand, model, price, is_new, url, photos: [], source: "ceneo.pl" }], info: str }` (1 offer, no photos)
- On JSON parse error: returns `{ offers: [], info: raw_text }` — never returns 502

**Bike categories** (defined in `app/categories.py`):
Road, Mountain (MTB), Gravel, Hybrid / Commuter, Electric (e-bike), BMX, Cruiser, Touring, Folding, Cyclocross, Kids

**To add a category**: add an entry to `BIKE_CATEGORIES` in `app/categories.py` and create the matching `app/prompts/<slug>.md`.

### Frontend (`/frontend`)

| Layer | File | Responsibility |
|-------|------|----------------|
| Entry point | `src/main.tsx` | React root, mounts `<App>` |
| App shell | `src/App.tsx` | View router (`search` / `details`), search, details, review, allegro offer, ceneo offer & used-bike state, all six API calls |
| Search form | `src/components/SearchInput.tsx` | Controlled input + submit button, loading state |
| Result card | `src/components/ResultCard.tsx` | Clickable per-bike card: match score, brand + model, accessories chips, explanation, score bar |
| Loading card | `src/components/LoadingCard.tsx` | Shimmer skeleton matching result card dimensions |
| Details view | `src/components/BikeDetailsView.tsx` | Full spec sheet: back nav, bike header, Overview (DescriptionCard), Allegro Offers (OffersSection), Ceneo Offers (OffersSection), Used Bikes OLX (UsedBikesSection), Expert Review (ReviewSection), category/subcategory/element/spec tree, shimmer skeleton, error + retry |
| Shared types | `src/types.ts` | `Bike`, `BikeCategory`, `BikeSubcategory`, `ComponentElement`, `SpecItem`, `BikeDetailsResponse`, `BikeDescription`, `TextSegment`, `DescriptionCitation`, `BikeReviewResponse`, `BikeOffer`, `BikeOfferResponse`, `UsedBikeResponse` |
| Styles | `src/index.css` | Tailwind v4 `@theme` tokens, Google Fonts import, keyframe animations |
| Vite config | `vite.config.ts` | Tailwind v4 plugin, `/v1` proxy to backend |

**Design system — Direction 5 "Café Rider":**
- Background `#EDE7DC` · Cards `#F5F1EA` · Accent `#C45C38` (terracotta)
- Display font: Barlow Condensed Bold · Body: Lora · Data labels: JetBrains Mono
- All theme tokens live in `src/index.css` under `@theme { --color-*, --font-* }`

**API integration:**
- `POST /v1/bike/search` `{ "search": "..." }` → `{ search, bikes: [{ brand, model, accessories, match_score, explanation }] }` (5 bikes)
- `POST /v1/bike/details` `{ "company": "...", "model": "..." }` → `{ company, model, description: BikeDescription, components: BikeCategory[] }`
- `POST /v1/bike/review` `{ "company": "...", "model": "..." }` → `{ score, explanation, ref: string[] }`
- `POST /v1/bike/offer` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (allegro.pl)
- `POST /v1/bike/ceneo` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (ceneo.pl)
- `POST /v1/bike/used` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (used bikes from OLX, each with optional `city`)
- All endpoints proxied to backend via Vite — no CORS config needed in development
