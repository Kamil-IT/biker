# Biker — AI Bike Finder

AI-powered bike finder. Describe what you're looking for in plain English and get matched to real bike models instantly.

## How it works

1. You enter a free-text description (e.g. *"comfortable bike for daily 10 km city commute"*)
2. The backend calls Claude Haiku once per category (11 total) to score relevance
3. Top-scoring categories (score ≥ 5, minimum 2) are selected; 5 bikes are allocated proportionally by score
4. Claude finds real bikes for each qualifying category in parallel
5. Click a result to open the details page — the backend fetches specs, description, manufacturer photos, review score, and current Allegro offers in parallel via Claude web search + Playwright
6. Click any component name in a bike's spec sheet (e.g. a derailleur, fork, or saddle) to open the **equipment** page for that item — an overview, component-tree spec sheet, photos, and an expert review for gear (helmets, lights, locks, apparel). Equipment is informational only — no shopping/offer links

## Running the project

You need **two terminals** — backend and frontend run separately.

### Terminal 1 — Backend

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env          # edit .env and set your ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8000
```

### Terminal 2 — Frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** in your browser.

> The frontend proxies `/v1/*` to the backend automatically — no CORS config needed.

## Other useful commands

| Command | What it does |
|---|---|
| `cd backend && python scripts/test_search.py` | Smoke-test `POST /v1/bike/search` |
| `cd backend && python scripts/test_details.py` | Smoke-test `POST /v1/bike/details` |
| `cd backend && python scripts/test_review.py` | Smoke-test `POST /v1/bike/review` |
| `cd backend && python scripts/test_offer.py` | Smoke-test `POST /v1/bike/offer` |
| `cd backend && python scripts/test_equipment.py` | Smoke-test `POST /v1/equipment/details` + `/v1/equipment/review` |
| `cd backend && pytest scripts/test_scoring.py -m "not llm"` | Deterministic category-scoring prompt tests (no API key) |
| `cd backend && pytest scripts/test_scoring.py -m llm -s` | Live category-scoring eval via the `claude` CLI (no API key; nightly) |
| `cd frontend && npm run build` | TypeScript check + production bundle → `dist/` |
| `cd frontend && npm run preview` | Serve the production bundle locally |
| http://localhost:8000/docs | Interactive OpenAPI UI for the backend |

## Marketplace integrations

| Marketplace | Status | Notes |
|---|---|---|
| Allegro | **Working** | Offers fetched via Claude web search (`bike_offer_allegro.md`). Official API requires a verified app — dev portal: https://apps.developer.allegro.pl/ |
| OLX | Waiting | Pending account approval |
| Amazon | Todo | — |

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14, FastAPI, Uvicorn |
| AI | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) — used for all API calls |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4 |
| Fonts | Barlow Condensed · Lora · JetBrains Mono |

## Project structure

```
biker/
├── backend/
│   ├── app/
│   │   ├── main.py                    # FastAPI app, routes
│   │   ├── schemas.py                 # Pydantic models
│   │   ├── categories.py              # 11 bike category registry
│   │   ├── anthropic_scorer.py        # Claude Haiku category scoring
│   │   ├── bike_finder.py             # Filter, allocate, find real bikes
│   │   ├── bike_details_finder.py     # Fetch full component specs via web search
│   │   ├── bike_description_finder.py # Generate plain-text overview via web search
│   │   ├── bike_review_finder.py      # Aggregate web reviews into score + explanation
│   │   ├── bike_offer_finder.py       # Find current Allegro offers via web search
│   │   ├── bike_photos_finder.py      # Find manufacturer product photos: Claude URL search + Playwright scrape
│   │   ├── equipment_categories.py    # 4 equipment category registry + inference
│   │   ├── equipment_details_finder.py    # Equipment component specs (per-category prompt)
│   │   ├── equipment_description_finder.py # Equipment overview via web search
│   │   ├── equipment_photos_finder.py      # Equipment manufacturer photos
│   │   ├── equipment_review_finder.py      # Equipment review (review/forum links only)
│   │   └── prompts/
│   │       ├── *.md                   # Per-category scoring prompts
│   │       ├── bike_search_*.md       # Per-category bike-finding prompts
│   │       ├── bike_details.md        # Component extraction prompt
│   │       ├── bike_review.md         # Review aggregation prompt
│   │       ├── bike_offer.md          # Multi-marketplace offer prompt (unused)
│   │       ├── bike_offer_allegro.md  # Allegro offer search prompt
│   │       ├── bike_photos.md         # Manufacturer product page URL search prompt
│   │       ├── equipment_details_*.md # Per-category equipment spec prompts (helmets/lights/locks/apparel)
│   │       ├── equipment_description.md   # Equipment overview prompt
│   │       ├── equipment_photos.md        # Equipment manufacturer page URL prompt
│   │       └── equipment_review.md        # Equipment review prompt (no offer links)
│   └── scripts/
│       ├── test_search.py             # Smoke test for /v1/bike/search
│       ├── test_details.py            # Smoke test for /v1/bike/details
│       ├── test_review.py             # Smoke test for /v1/bike/review
│       ├── test_offer.py              # Smoke test for /v1/bike/offer
│       ├── test_equipment.py          # Smoke test for /v1/equipment/details + /review
│       ├── test_equipment_review.py   # Focused regression for equipment-review JSON extraction
│       └── test_scoring.py            # Pytest eval of category-scoring prompts (deterministic + live CLI)
└── frontend/
    └── src/
        ├── App.tsx                    # App shell, state machine, all API calls
        ├── types.ts                   # Shared TypeScript interfaces
        └── components/
            ├── SearchInput.tsx        # Search form
            ├── ResultCard.tsx         # Per-bike result card
            ├── LoadingCard.tsx        # Shimmer skeleton for search results
            ├── BikeDetailsView.tsx    # Bike details page: Overview, Offers, Review, Specs
            ├── EquipmentDetailsView.tsx   # Equipment details page: Overview, Review, Specs (no offers)
            └── BikeDetailsShared.tsx  # Shared building blocks for both detail views
```
