# Biker Backend

## Setup & Run

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # then edit .env with your real ANTHROPIC_API_KEY
uvicorn app.main:app --reload --port 8000
```

```bash
# In a second terminal:
python scripts/test_search.py   # smoke-test POST /v1/bike/search
python scripts/test_details.py  # smoke-test POST /v1/bike/details
python scripts/test_review.py   # smoke-test POST /v1/bike/review
python scripts/test_offer.py    # smoke-test POST /v1/bike/offer
```

## Endpoints

### `POST /v1/bike/search`

Find 5 matching bikes. All fields are optional but at least one must be provided. The structured fields are combined into an enriched query string and fed to Claude alongside the free-text description.

```http
POST http://localhost:8000/v1/bike/search
Content-Type: application/json

{
  "search": "comfortable bike for daily 10 km city commute, mostly paved roads",
  "brand": "Trek",
  "model": "FX 3",
  "year": 2023,
  "wheel_size": "29\"",
  "is_electric": false,
  "has_suspension": false,
  "is_kids": false
}
```

All fields except `search` default to `null` (no constraint). The backend assembles an enriched query such as `"Brand: Trek, Model: FX 3, Year: 2023 — comfortable bike…"` and passes it through the existing scoring and bike-finding pipeline.

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 11 — score each bike category (sequential)
2. `POST https://api.anthropic.com/v1/messages` × N — find real bikes per top category (parallel)

---

### `POST /v1/bike/details`

Return the full component list for a specific bike model.

```http
POST http://localhost:8000/v1/bike/details
Content-Type: application/json

{
  "company": "Canyon",
  "model": "Grizl CF 7 ESC"
}
```

**Response includes:** `description` (4–5 sentence plain-text overview), `components` (category tree), `photos` (up to 8 manufacturer product image URLs).

**Flow (all three run in parallel via `asyncio.gather`):**
1. `POST https://api.anthropic.com/v1/messages` × 8 — Claude Haiku with `web_search_20250305` tool, one focused search per component category (sequential): Frame, Drivetrain, Brakes, Wheels, Cockpit, Saddle & Seatpost, Lighting, Accessories
2. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool + prompt caching, generates a 4–5 sentence bike overview
3. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool finds the official manufacturer product page URL, then Playwright (headless=False) scrapes up to 8 product `<img>` URLs from the rendered page

---

### `POST /v1/bike/review`

Return an aggregated review score, explanation, and source links for a specific bike model.

```http
POST http://localhost:8000/v1/bike/review
Content-Type: application/json

{
  "company": "Canyon",
  "model": "Grizl CF 7 ESC"
}
```

**Response:**
```json
{
  "score": 8,
  "explanation": "The Canyon Grizl CF 7 ESC is widely praised for its...",
  "ref": ["https://...", "https://..."]
}
```

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches for 3–5 reviews, then synthesises a score 0–10, a 5–10 sentence explanation, and a list of source URLs

---

### `POST /v1/bike/offer`

Return current buying offers from Polish cycling marketplaces for a specific bike model.

```http
POST http://localhost:8000/v1/bike/offer
Content-Type: application/json

{
  "company": "Canyon",
  "model": "Grizl CF 7 ESC"
}
```

**Response:**
```json
{
  "offers": [
    {
      "brand": "Canyon",
      "model": "Grizl CF 7",
      "price": "8 999 zł",
      "is_new": false,
      "url": "https://www.olx.pl/oferta/...",
      "photos": ["https://img.olx.pl/...jpg"],
      "source": "allegro.pl"
    }
  ]
}
```

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches allegro.pl; returns 1 offer with price, condition, direct link, and photo URLs

---

### `POST /v1/bike/parse`

Extract structured bike attributes (brand, model, year, wheel size, flags) from a free-text query. Used by the frontend to auto-populate the structured search fields before the user submits their search.

```http
POST http://localhost:8000/v1/bike/parse
Content-Type: application/json

{
  "text": "Looking for Trek Marlin 7 2023, 29 inch wheels, with suspension"
}
```

**Response:**
```json
{
  "brand": "Trek",
  "model": "Marlin 7",
  "year": 2023,
  "wheel_size": "29\"",
  "has_suspension": true,
  "is_electric": null,
  "is_kids": null
}
```

Fields not found in the text are returned as `null`. All fields are optional in the response.

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku (no web search, pure text extraction) with `app/prompts/bike_parse.md` system prompt; returns a JSON object with only the confident field extractions
