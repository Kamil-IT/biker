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

## Category-Scoring Prompt Eval

`scripts/test_scoring.py` (pytest) evaluates the per-category scoring prompts in
`app/prompts/<category>.md`. It has two tiers:

```bash
cd backend

# 1) Deterministic tier — no model, no API key, runs on every commit.
#    Verifies the scorer's JSON parsing + graceful-degradation contract.
pytest scripts/test_scoring.py -m "not llm"

# 2) Live eval tier — full-dataset directional eval (run nightly/pre-release).
#    Scores 11 canonical queries against all 11 category prompts and asserts the
#    right category ranks highest. Add -s to print the top-1/top-2/MRR report.
pytest scripts/test_scoring.py -m llm -s
```

**The live tier needs no `ANTHROPIC_API_KEY`.** Instead of calling the API, it shells
out to the **`claude` CLI**, which authenticates via your subscription login. Each
(query, category) pair is scored with `claude -p "<query>" --system-prompt
"<app/prompts/category.md>" --tools "" --model claude-haiku-4-5-20251001
--output-format json` — i.e. the category prompt is the *sole* system prompt and the
prod model (Haiku 4.5) is forced, so it mirrors `anthropic_scorer.py`.

Prerequisites & notes for the live tier:
- `claude` CLI installed and logged in. If it is not on `PATH`, the live tests **skip**
  (they never hard-fail CI).
- A full run is **121 CLI calls** (11 queries × 11 categories) and takes several minutes;
  it draws on your Claude subscription usage. Run it nightly/pre-release, not per commit.
- The CLI is an agent harness, so replies may be prose rather than raw JSON; the eval
  extracts the numeric score (JSON → `score: N` → `N/10`). Strict JSON-format compliance
  is covered separately by the deterministic tier and the real-API prod path.

`pytest.ini` registers the `llm` marker and scopes default collection to
`scripts/test_scoring.py` so the standalone smoke scripts above are not auto-run.

### Evaluate any prompt (ad-hoc)

`scripts/eval_prompt.py` runs **any** prompt file (as the system prompt) against
arbitrary inputs via the same no-API-key `claude` CLI mechanism, printing each
reply and its extracted score (if any):

```bash
cd backend
.venv\Scripts\python.exe scripts/eval_prompt.py app/prompts/road.md "fast carbon road racer" "29er trail bike"
.venv\Scripts\python.exe scripts/eval_prompt.py app/prompts/gravel.md --dataset inputs.txt --model sonnet
```

The `/eval-prompt <prompt-file> "<input>" ...` slash command (`.claude/commands/`)
wraps this for quick reuse. Use it for ad-hoc prompt iteration; use the pytest
`-m llm` suite for the fixed directional category eval.

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
  "is_kids": false,
  "bike_type": "Gravel",
  "price_max": 6000,
  "frame_size": "M",
  "rider_height_cm": 178,
  "gender": "Universal",
  "frame_material": "Carbon",
  "brake_type": "Hydraulic Disc",
  "drivetrain": "2x",
  "belt_drive": false,
  "battery_capacity_wh": 500
}
```

All fields except `search` default to `null` (no constraint). The backend assembles an enriched query such as `"Brand: Trek, Type: Gravel, Frame size: M, Max price: 6000 PLN — comfortable bike…"` and passes it through the existing scoring and bike-finding pipeline. All fields participate in the SQLite cache key, so two searches that differ only in a filter return distinct results.

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 11 — score each bike category (parallel via `asyncio.gather`)
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

### `POST /v1/bike/used`

Return current used-bike listings from OLX.pl for a specific bike model.

```http
POST http://localhost:8000/v1/bike/used
Content-Type: application/json

{
  "company": "Trek",
  "model": "Marlin 5"
}
```

**Response:**
```json
{
  "offers": [
    {
      "brand": "Trek",
      "model": "Marlin 5 2022",
      "price": "2 500 zł",
      "is_new": false,
      "url": "https://www.olx.pl/d/oferta/...",
      "photos": ["https://ireland.apollo.olxcdn.com/...jpg"],
      "source": "olx.pl",
      "city": "Warsaw"
    }
  ],
  "info": "Exact match found on OLX.pl"
}
```

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches olx.pl with cascade fallback (exact → model-family → brand/category); returns up to 5 used listings with price, city, direct link
2. Playwright (headless=False) navigates each listing URL and extracts up to 4 `<img>` URLs matching the OLX CDN pattern (`*.apollo.olxcdn.com`)

---

### `POST /v1/bike/ceneo`

Return current buying offers from ceneo.pl for a specific bike model.

```http
POST http://localhost:8000/v1/bike/ceneo
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
      "is_new": true,
      "url": "https://www.ceneo.pl/rowery/canyon-grizl-cf-7",
      "photos": [],
      "source": "ceneo.pl"
    }
  ],
  "info": ""
}
```

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches ceneo.pl; returns 1 offer with price, condition, and direct link

---

### `POST /v1/bike/decathlon`

Return the current buying offer from decathlon.pl for a specific bike model.

```http
POST http://localhost:8000/v1/bike/decathlon
Content-Type: application/json

{
  "company": "Rockrider",
  "model": "ST 100"
}
```

**Response:**
```json
{
  "offers": [
    {
      "brand": "Rockrider",
      "model": "ST 100",
      "price": "1199 zł",
      "is_new": true,
      "url": "https://www.decathlon.pl/p/rockrider-st-100",
      "photos": [],
      "source": "decathlon.pl"
    }
  ],
  "info": ""
}
```

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches decathlon.pl; returns 1 new offer with price and direct link (no photos — pages require JS rendering)

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
