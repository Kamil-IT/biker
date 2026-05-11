# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Monorepo with separate backend and frontend applications:
- `/backend` — Python REST API (FastAPI)
- `/frontend` — Frontend application (TBD)

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

- **Install dependencies**: `cd frontend && npm install`
- **Run development server**: `cd frontend && npm run dev`
- **Run tests**: `cd frontend && npm test`
- **Node version**: v24 / npm 11

## Architecture

### Backend (`/backend`)

| Layer | File | Responsibility |
|-------|------|----------------|
| Entry point | `app/main.py` | FastAPI app, `POST /v1/bike/search` route, request logging |
| Schemas | `app/schemas.py` | Pydantic models: `SearchRequest`, `CategoryResult`, `SearchResponse` |
| Categories | `app/categories.py` | 11 bike category registry; loads prompt files at startup |
| Prompts | `app/prompts/*.md` | Per-category system prompts (one `.md` file per category) |
| Scorer | `app/anthropic_scorer.py` | Calls Claude Haiku per category, strips code fences, parses JSON |
| Test script | `scripts/test_search.py` | POSTs a sample search, prints response, asserts HTTP 200 |

**Endpoint** `POST /v1/bike/search`
- Request: `{"search": "free text description"}`
- Calls `claude-haiku-4-5-20251001` once per category (11 sequential calls)
- Returns all categories ranked by score (highest first)
- On parse error: `score=0`, raw response in `explanation` — never returns 502 for bad JSON

**Bike categories** (defined in `app/categories.py`):
Road, Mountain (MTB), Gravel, Hybrid / Commuter, Electric (e-bike), BMX, Cruiser, Touring, Folding, Cyclocross, Kids

**To add a category**: add an entry to `BIKE_CATEGORIES` in `app/categories.py` and create the matching `app/prompts/<slug>.md`.

### Frontend

TBD
