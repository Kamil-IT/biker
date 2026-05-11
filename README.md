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
| `cd backend && python scripts/test_search.py` | Smoke-test the backend API |
| `cd frontend && npm run build` | TypeScript check + production bundle → `dist/` |
| `cd frontend && npm run preview` | Serve the production bundle locally |
| http://localhost:8000/docs | Interactive OpenAPI UI for the backend |

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14, FastAPI, Uvicorn |
| AI | Anthropic Claude Haiku (`claude-haiku-4-5-20251001`) |
| Frontend | React 19, TypeScript, Vite, Tailwind CSS v4 |
| Fonts | Barlow Condensed · Lora · JetBrains Mono |

## Project structure

```
biker/
├── backend/
│   ├── app/
│   │   ├── main.py               # FastAPI app, POST /v1/bike/search
│   │   ├── schemas.py            # Pydantic models
│   │   ├── categories.py         # 11 bike category registry
│   │   ├── anthropic_scorer.py   # Claude Haiku category scoring
│   │   ├── bike_finder.py        # Filter, allocate, find real bikes
│   │   └── prompts/
│   │       ├── *.md              # Per-category scoring prompts
│   │       └── bike_search_*.md  # Per-category bike-finding prompts
│   └── scripts/test_search.py    # Integration smoke test
└── frontend/
    └── src/
        ├── App.tsx               # App shell, state machine, API call
        └── components/
            ├── SearchInput.tsx   # Search form
            ├── ResultCard.tsx    # Per-bike result card (brand, model, accessories, match score)
            └── LoadingCard.tsx   # Shimmer skeleton
```
