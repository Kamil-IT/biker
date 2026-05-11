# Biker — AI Bike Finder

AI-powered bike finder. Describe what you're looking for in plain English and get matched to real bike models instantly.

## How it works

1. You enter a free-text description (e.g. *"comfortable bike for daily 10 km city commute"*)
2. The backend calls Claude Haiku once per category (11 total) to score relevance
3. Top-scoring categories (score ≥ 5, minimum 2) are selected; 5 bikes are allocated proportionally by score
4. Claude finds real bikes for each qualifying category in parallel
5. Results (brand, model, accessories, match score, explanation) are returned

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
| `cd frontend && npm run build` | TypeScript check + production bundle → `dist/` |
| `cd frontend && npm run preview` | Serve the production bundle locally |
| http://localhost:8000/docs | Interactive OpenAPI UI for the backend |

## Marketplace integrations

| Marketplace | Status | Notes |
|---|---|---|
| Allegro | **Blocked** | Offer listing requires a verified app — not implementing for now. Dev portal: https://apps.developer.allegro.pl/ · [Restriction details](https://developer.allegro.pl/news/get-offers-listing-tylko-dla-zweryfikowanych-aplikacji-GRax4oVgrs1) |
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
│   │   ├── main.py               # FastAPI app, routes
│   │   ├── schemas.py            # Pydantic models
│   │   ├── categories.py         # 11 bike category registry
│   │   ├── anthropic_scorer.py   # Claude Haiku category scoring
│   │   ├── bike_finder.py        # Filter, allocate, find real bikes
│   │   ├── bike_details_finder.py# Fetch full component specs via web search
│   │   └── prompts/
│   │       ├── *.md              # Per-category scoring prompts
│   │       ├── bike_search_*.md  # Per-category bike-finding prompts
│   │       └── bike_details.md   # Component extraction prompt
│   └── scripts/
│       ├── test_search.py        # Smoke test for /v1/bike/search
│       └── test_details.py       # Smoke test for /v1/bike/details
└── frontend/
    └── src/
        ├── App.tsx               # App shell, state machine, API call
        └── components/
            ├── SearchInput.tsx   # Search form
            ├── ResultCard.tsx    # Per-bike result card (brand, model, accessories, match score)
            └── LoadingCard.tsx   # Shimmer skeleton
```
