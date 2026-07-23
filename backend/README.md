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
#    Verifies the scorer's JSON parsing + graceful-degradation contract,
#    plus every pure unit test under tests/ (both collected by default).
pytest -m "not llm"

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
`scripts/test_scoring.py` **and `tests/`**, so a bare `pytest` run covers the prompt-eval
suite plus every pure unit test (currently `tests/test_price_parse.py`). The rest of
`scripts/` stays excluded — those are standalone smoke scripts that hit a live server at
import time and must not be auto-run.

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

## Follow-up cache tables

Two queryable SQLite tables (in the same `cache.db`, created on startup by `app/store.py`) sit **on top of** the generic response cache (`app/cache.py`). They let follow-up requests be served without any web/Claude call:

| Table | Key | Stores | TTL |
|-------|-----|--------|-----|
| `search_cache` | normalised enriched `query` | JSON list of `BikeResult` | 24 h |
| `bike_details_cache` | `(company, model)` | `description`, `components`, `photos` (JSON) | 30 days |

- Both are indexed on their key columns and upsert on conflict (a re-run refreshes the entry).
- Reads check the row's `time_stored + ttl`; a stale row is treated as a miss (never served).
- `search_cache` is also queryable **by attribute** — `find_bikes_by_brand(brand)` scans fresh cached searches and returns de-duplicated bikes of that brand, powering `GET /v1/bike/search-cache?brand=`.
- Writes are best-effort: a cache-table failure is logged but never breaks the underlying request.
- This layer is **additive** — the generic per-endpoint cache is unchanged.

The follow-up read endpoints are [`GET /v1/bike/search-cache`](#get-v1bikesearch-cache) and [`GET /v1/bike/details-cache`](#get-v1bikedetails-cache).

## Search Cache

`POST /v1/bike/search` resolves through a **three-step cascade**, stopping at the first step that produces bikes:

| # | Step | Cost | Condition |
|---|------|------|-----------|
| 1 | Generic response cache (`app/cache.py`) | 0 outbound calls | Exact normalised match on the full request (every filter field) |
| 2 | **Brand+model DB lookup** (`app/store.py`) | 0 outbound calls | `brand` **and** `model` both provided, and a fresh `search_cache` row holds that bike |
| 3 | AI pipeline | 11 + N calls | Everything else — a miss at 1 and 2 |

Step 2 is the addition. `find_bike_by_brand_model(brand, model)` scans `search_cache`, skips rows past their 24 h TTL, and returns every de-duplicated bike whose normalised brand **and** model match. A hit **short-circuits** — the AI pipeline never runs. The response shape is identical (`BikeSearchResponse`); only `len(bikes)` differs, since it returns just the bikes that actually match rather than padding to 5. A miss, a stale row, or an all-filtered-out result falls through to step 3 unchanged.

### Which filters are honoured on the DB path

**Only `price_max`.** It is gated by joining the generic cache's offer rows:

- `find_offer_prices(brand, model)` reads every cached response from `/v1/bike/offer`, `/v1/bike/ceneo`, `/v1/bike/decathlon` and `/v1/bike/used` for that bike, and parses each offer's `price` string via `app/price_parse.py`.
- The join key is `_normalise({"company": brand, "model": model})` — imported from `cache.py` so the lookup key is byte-identical to how offer rows were written. `store.py`'s own `_norm()` (strip + lowercase) produces the same normalisation, so no extra mapping is needed.
- **Cheapest across all sources** gates the filter: `min()` of every parseable price from all four endpoints, new and used alike.
- **Lenient when no price is parseable.** A bike with no offer rows — or whose prices are all sentinels like `'Price on request'` — passes the filter. Only ~21 % of cached bikes have a matching offer row, so strict filtering would discard the great majority of hits. The tradeoff: an over-budget bike may be returned unverified.

**Not honoured on the DB path:** `year`, `frame_size`, `wheel_size`, `frame_material`, `brake_type`, `drivetrain`, `gender`, `rider_height_cm`, `rider_weight_kg`, `battery_capacity_wh`.

This is a deliberate, documented limitation, not an oversight. `BikeResult` stores only `brand`, `model`, `accessories`, `match_score`, `explanation`; `BikeOffer` adds only `price`, `is_new`, `url`, `photos`, `source`, `city`. **No stored model carries any of those fields**, so there is nothing to filter against. Rather than silently dropping the constraints or faking a match, the DB path ignores them — a request combining `brand` + `model` with, say, `frame_size: "M"` may be served from the DB with that size unverified. Callers that need those constraints enforced should omit `brand` or `model` so the request routes to the AI pipeline.

### A DB hit deliberately does not warm the generic cache

`set_cached` is never called on the step-2 path. The generic `cache` table has **no `ttl` column** and `get_cached` never checks age — writing a DB-sourced result there would pin a 24 h-TTL `search_cache` answer permanently, outliving the very TTL that makes it safe to serve. The same no-TTL property is why the joined offer prices never expire either: a stale scraped price can gate `price_max` indefinitely.

Note the offer cache's brand/model split does not always agree with `search_cache`'s — e.g. `('decathlon', 'rockrider st 100')` vs the offer row's `('rockrider', 'st 100')`. Those simply fail to join, and the lenient rule keeps the bike.

`parse_price()` handles the real formats found in the cache: `zł` / `PLN` / `zl` currency tokens, regular/NBSP/narrow-NBSP thousands separators, and both `,` and `.` decimals (with both present the **last** separator is the decimal point; a lone separator is decimal only when exactly 2 digits follow). It returns `None` — never raises — for anything with no digits.

**Tests:** `tests/test_price_parse.py` covers the parser (collected by a bare `pytest` run — see [Category-Scoring Prompt Eval](#category-scoring-prompt-eval)). The cascade itself is covered by `scripts/test_search.py` TC-20 – TC-25 against a live server: DB hit, AI fallback, stale-row fall-through, `price_max` gating both ways, lenient unknown price, and no regression on the generic-cache path.

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
  "rider_weight_kg": 75,
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
0. SQLite reads only — generic cache, then (when `brand` **and** `model` are both given) the `search_cache` brand+model lookup with its `price_max` offer join. **A hit at either step returns immediately, making zero outbound HTTP calls.** Steps 1–2 run only on a miss. See [Search Cache](#search-cache)
1. `POST https://api.anthropic.com/v1/messages` × 11 — score each bike category (parallel via `asyncio.gather`)
2. `POST https://api.anthropic.com/v1/messages` × N — find real bikes per top category (parallel)

On the happy path the result is also written to the queryable `search_cache` table (see [Follow-up cache tables](#follow-up-cache-tables)). A DB-served result is **not** written back to the generic cache — see [Search Cache](#search-cache) for why.

---

### `GET /v1/bike/search-cache`

Follow-up read served **purely from the `search_cache` table** — makes **no** web/Claude call. Two modes:

- `?query=<enriched query>` — exact (case-insensitive, trimmed) repeat of a prior search. Returns 404 if not cached or the entry is older than its 24 h TTL.
- `?brand=<brand>` — lookup-by-attribute: every cached bike of that brand across all fresh cached searches (de-duplicated by brand+model).

```http
GET http://localhost:8000/v1/bike/search-cache?query=Brand:%20Trek%20%E2%80%94%20trail%20riding
GET http://localhost:8000/v1/bike/search-cache?brand=Trek
```

**Response:**
```json
{
  "query": "Brand: Trek — trail riding",
  "cached": true,
  "bikes": [ { "brand": "Trek", "model": "Marlin 5", "accessories": [], "match_score": 8.0, "explanation": "…" } ]
}
```

Returns 422 if neither `query` nor `brand` is provided.

**Flow:** none — SQLite read only.

---

### `GET /v1/bike/details-cache`

Follow-up details lookup served **purely from the `bike_details_cache` table** — makes **no** web/Claude call. Returns 404 if the `(company, model)` pair is not cached or the entry is older than its 30-day TTL.

```http
GET http://localhost:8000/v1/bike/details-cache?company=Canyon&model=Grizl%20CF%207%20ESC
```

**Response:** identical shape to `POST /v1/bike/details` (`company`, `model`, `description`, `components`, `photos`).

**Flow:** none — SQLite read only.

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

On the happy path the result is also written to the queryable `bike_details_cache` table (see [Follow-up cache tables](#follow-up-cache-tables)).

**Flow (all three run in parallel via `asyncio.gather`):**
1. `POST https://api.anthropic.com/v1/messages` × 8 — Claude Haiku with `web_search_20250305` tool, one focused search per component category (sequential): Frame, Drivetrain, Brakes, Wheels, Cockpit, Saddle & Seatpost, Lighting, Accessories
2. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool + prompt caching, generates a 4–5 sentence bike overview
3. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool finds the official manufacturer product page URL, then Playwright (headless=False) scrapes up to 8 product `<img>` URLs from the rendered page

**Parsing:** each category response goes through the shared `app/json_extract.py` `extract_json()`, which pulls the first parseable fenced block or balanced `{...}` / `[...]` out of surrounding prose. The model routinely narrates ("I'll search for the Brakes specifications...") before emitting the JSON, so a parser that assumed the whole response was JSON silently dropped whole categories. A category with genuinely no JSON in its response is logged and skipped — never a 502.

---

### `POST /v1/bike/review`

Return an aggregated review score, explanation, source links, and an aggregate rating derived from multiple curated review sources for a specific bike model.

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
  "ref": ["https://...", "https://..."],
  "rating": 7.7,
  "sources_used": 3
}
```

- `score` — a single synthesised editorial verdict (integer 0–10), as before.
- `rating` — the **aggregate** rating (float 0–10) computed from per-source scores across the curated sources.
- `sources_used` — count of curated sources that contributed a score to the aggregate.

**Aggregation methodology** (curated source list and tier weights in [`backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md`](../backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md)):
Claude searches the curated sources and returns a per-source score for each source it found a review on, tagged with a `type`. The backend computes a weighted mean and normalises to 0–10:

| Source type | Examples | Weight |
|---|---|---|
| `pro_numeric` | bikeradar.com, cyclingweekly.com, bikeperfect.com | 3× |
| `pro_qualitative` | pinkbike.com, bikemag.com, gcn.com | 2× |
| `community` | mtbr.com, reddit.com, forumrowerowe.org / bikestats.pl | 1× |

`rating = Σ(score × weight) / Σ(weight)`, rounded to 1 decimal. A non-zero rating **requires at least one professional (`pro_numeric` or `pro_qualitative`) source**; if only community sources are found, `rating` is `0.0` and `sources_used` is `0`.

The curated list is a starting point, not a whitelist: if no curated source covers the model, Claude may use any other credible review site or owner forum, tagged with the closest matching `type`. This prevents a bike with real but non-curated coverage from returning nothing.

**Cache:** keyed on `{company, model}`; stored on the happy path only when `ref` is non-empty **and** `sources_used >= 1`. The extra `sources_used` condition stops a degenerate `rating: 0.0` response from being pinned in the cache for that bike forever. The full extended response — including `rating` and `sources_used` — is cached, so a repeat call returns the same rating.

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches the curated sources, returns a per-source score array plus a synthesised overall score, 5–10 sentence explanation, and source URLs; the backend then computes the weighted aggregate rating
2. `POST https://api.anthropic.com/v1/messages` × 0–1 — **repair pass, only if step 1 ended in prose instead of the JSON object.** Re-sends step 1's text findings with no tools and an assistant prefill of `{`, so the model can only emit the object. Avoids discarding an already-paid-for web search

The response parser scans **every** text block for the first balanced `{...}` rather than assuming the last block is pure JSON, and strips any `<cite>` markup `web_search` injects into the explanation.

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

### `POST /v1/equipment/details`

Return an overview, component-tree spec sheet, and photos for a piece of cycling equipment (helmet, light/electronics, lock/security, or apparel/bags/accessories). The gear counterpart to `/v1/bike/details`. **No shopping/offer links** are ever included.

```http
POST http://localhost:8000/v1/equipment/details
Content-Type: application/json

{
  "company": "POC",
  "model": "Octal MIPS",
  "category": "helmets"
}
```

- `company` is optional (defaults to `""`), `model` is required, `category` is optional — one of `helmets`, `lights`, `locks`, `apparel`. If `category` is omitted it is **inferred** from the item name (keyword match; falls back to `apparel`).

**Response includes:** `category` (resolved slug), `description` (4–5 sentence cited overview), `components` (same category → subcategory → element → spec tree as bikes), `photos` (up to 8 manufacturer product image URLs). No offer/buy links.

**Flow (all three run in parallel via `asyncio.gather`):**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku, one focused search using the resolved category's `equipment_details_{slug}.md` prompt, returns the component tree (web_search currently disabled behind a `TODO` flag, mirroring `/v1/bike/details`)
2. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool + prompt caching, generates a 4–5 sentence equipment overview
3. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool finds the official manufacturer product page URL, then Playwright (headless=False) scrapes up to 8 product `<img>` URLs from the rendered page

**Parsing:** same shared `extract_json()` as `/v1/bike/details` — see that endpoint's Parsing note.

**Cache:** keyed on `{company, model, category}`; always cached (empty is a valid result).

---

### `POST /v1/equipment/review`

Return an aggregated review score, explanation, and source links for a piece of cycling equipment. Review/forum **source** links are allowed; offer/buy links are never included.

```http
POST http://localhost:8000/v1/equipment/review
Content-Type: application/json

{
  "company": "POC",
  "model": "Octal MIPS"
}
```

**Response:**
```json
{
  "score": 8,
  "explanation": "The POC Octal MIPS is widely praised as one of the most protective...",
  "ref": ["https://..."]
}
```

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku with `web_search_20250305` tool searches for 3–5 reviews, then synthesises a score 0–10, a 5–10 sentence explanation, and one source URL

**Cache:** keyed on `{company, model}`; cached **only when `ref` is non-empty** (fallbacks are never cached).

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
  "is_kids": null,
  "rider_height_cm": null,
  "rider_weight_kg": null
}
```

Fields not found in the text are returned as `null`. All fields are optional in the response.

`brand` is also extracted from Polish and English brand-constraint phrasing — "Firma tylko Tesla", "marka Trek", "tylko Specialized", "brand only Canyon" — copying the name verbatim (casing preserved). The name after such a keyword is extracted even when it is not a known bicycle maker. Place names following a preposition ("po Wrocławiu", "w Krakowie") are treated as locations, never as a brand.

**Flow:**
1. `POST https://api.anthropic.com/v1/messages` × 1 — Claude Haiku (no web search, pure text extraction) with `app/prompts/bike_parse.md` system prompt; returns a JSON object with only the confident field extractions
