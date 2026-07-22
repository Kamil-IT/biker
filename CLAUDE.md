# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Agent Policy

**Before implementing any multi-step task**, always call `mcp__ruflo__hooks_pre-task` with the task ID and description. It returns agent role suggestions — spawn those agents via `mcp__ruflo__agent_spawn` before writing code. Example flow:

1. `mcp__ruflo__hooks_pre-task` — get agent suggestions for this task
2. `mcp__ruflo__agent_spawn` — spawn one agent per suggested role (e.g. `backend-impl`, `tester`)
3. `mcp__ruflo__task_create` — register the task
4. Implement, then `mcp__ruflo__task_complete` when done

## ECC Skill Routing

Structured workflows for common task types. Reference these skills in `/\.claude/skills/` when starting code changes.

| Task | Skill | Use When |
|------|-------|----------|
| **Implement new endpoint** | `sparc-code` | Adding POST /v1/bike/* or /v1/equipment/* endpoint |
| **Add tests** | `sparc-tester` | After implementation, before PR; writes smoke tests in backend/scripts/test_search.py |
| **Security audit** | `sparc-security-review` | New endpoint, new finder module, or API integration (validates input, prevents prompt injection, checks error handling) |
| **Capture pattern** | `memory-persist` | After successful feature completion; saves reusable pattern to Obsidian vault for future tasks |

**Example workflow:**
```
User: "Add Decathlon offer endpoint"

1. Invoke `/sparc:code` to design the endpoint + finder
   → creates app/bike_offer_decathlon_finder.py + POST /v1/bike/decathlon route
2. Invoke `/sparc:tester` to add smoke tests
   → adds test to backend/scripts/test_search.py
3. Invoke `/sparc:security-review` to audit API calls + input validation
   → checks for prompt injection, API key leaks, error handling
4. Invoke `/memory:persist` to capture pattern
   → saves "Offer finder pattern: single web_search + cache + fallback" to Obsidian
5. Create PR for review
```

**Skills directory:** `.claude/skills/` in this repo contains:
- `sparc-code.md` — structured implementation with phases (Specification → Pseudocode → Implementation → Testing)
- `sparc-tester.md` — TDD workflow + smoke test templates for backend/frontend
- `sparc-security-review.md` — security checklist + audit templates + pen-test examples
- `memory-persist.md` — capture patterns to Obsidian vault; search for similar past solutions before coding

## Memory & Persistence

Durable, cross-session memory for this project lives in a single human-readable Obsidian vault — **not** ruflo's `memory_*` / AgentDB stores. The vault is at `obsidian/bike-memory/` (gitignored, including its bearer token) with notes under a `memory/` folder. It is served by the `obsidian` MCP server (the "MCP Connector" plugin, `http://127.0.0.1:27200/mcp`) using local Transformers.js embeddings (`Xenova/all-MiniLM-L6-v2`, no API key).

**To recall:** `mcp__obsidian__search_vault_smart` (semantic) or `search_vault_simple` (keyword).
**To store:** `mcp__obsidian__create_vault_file` (path like `memory/<topic>.md`, with YAML frontmatter + tags).
**To read/update:** `get_vault_file`, `append_to_vault_file`, `patch_vault_file`, `list_vault_files`.

Prefer these over `mcp__ruflo__memory_store` / `memory_search` — the vault is the source of truth so everything stays in one syncable, greppable, Obsidian-browsable store. **Requires the Obsidian app running** with the MCP Connector plugin enabled; if the `obsidian` server is unavailable, say so rather than silently falling back to the ruflo DB.

## Backlog

Tasks are tracked in `/backlog/`. Naming convention:

- `TODO_<ID>_<TASK_NAME>.md` — task not yet started
- `DONE_<ID>_<TASK_NAME>.md` — completed task (rename the file, don't delete it)
- `TODO_ISSUE_<ID>_<NAME>.md` — reported bug/issue, not yet fixed
- `DONE_ISSUE_<ID>_<NAME>.md` — fixed issue (rename the file, don't delete it)

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
For endpoints returning offers or reviews, only cache when the result is non-empty:
- Offers: `if result.offers: set_cached(...)`
- Reviews: `if result.ref: set_cached(...)`
- Search/details: always cache (empty is a valid result)
This mirrors the pattern used by `/v1/bike/used`.

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
| Schemas | `app/schemas.py` | Pydantic models: `SearchRequest`, `CategoryResult`, `SearchResponse`, `BikeResult`, `BikeSearchResponse`, `BikeDetailsRequest`, `BikeDetailsResponse`, `BikeCategory`, `BikeSubcategory`, `ComponentElement`, `SpecItem`, `BikeReviewRequest`, `BikeReviewResponse`, `BikeOffer`, `BikeOfferRequest`, `BikeOfferResponse`, `UsedBikeRequest`, `UsedBikeResponse`, `EquipmentDetailsRequest`, `EquipmentDetailsResponse`, `EquipmentReviewRequest`, `EquipmentReviewResponse` |
| Categories | `app/categories.py` | 11 bike category registry; loads prompt files at startup |
| Equipment categories | `app/equipment_categories.py` | 4 equipment category registry (helmets, lights, locks, apparel); loads prompt files at startup; keyword-based `resolve_category()` inference |
| Prompts | `app/prompts/*.md` | Per-category scoring prompts + `bike_search_{slug}.md` per-category bike-finding prompts + `bike_details_{slug}.md` per-category component search prompts (8 categories) + `bike_details.md` JSON format reference + `equipment_details_{slug}.md` (4) + `equipment_description.md` / `equipment_photos.md` / `equipment_review.md` |
| Scorer | `app/anthropic_scorer.py` | Calls Claude Haiku per category, strips code fences, parses JSON |
| Bike finder | `app/bike_finder.py` | Filters top categories, allocates 5 bikes by score weight, finds real bikes via Claude in parallel |
| Details finder | `app/bike_details_finder.py` | Loops through 8 component categories (Frame → Accessories), runs one focused `web_search` call per category, aggregates results via the shared `extract_json()`; logs per-iteration and total token usage |
| JSON extraction | `app/json_extract.py` | Shared `extract_json()` — lifts the first parseable fenced block or balanced `{...}`/`[...]` out of prose. Used by every finder whose prompt demands raw JSON; the model narrates before the object often enough that a strict parser silently loses whole categories/offers |
| Description finder | `app/bike_description_finder.py` | Single `web_search` call with prompt caching to generate a 4–5 sentence plain-text bike overview; runs in parallel with details finder |
| Review finder | `app/bike_review_finder.py` | Single `web_search` call across curated sources (tier list and weights in `backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md`); synthesises score 0–10, explanation, source URLs, plus a per-source score array from which it computes a weighted aggregate `rating` (0–10) and `sources_used` count (pro/numeric 3×, pro/qualitative 2×, community 1×; non-zero rating requires ≥1 pro source). Tolerates the model narrating before the JSON via a balanced-brace scan over all text blocks, with a no-tool prefilled repair call as a last resort |
| Offer finder | `app/bike_offer_finder.py` | Single `web_search` call to find 1 current offer on allegro.pl |
| Used bikes finder | `app/bike_used_finder.py` | Single `web_search` call to find up to 5 used listings on olx.pl with cascade fallback; then Playwright scrapes photos via `olx_image_fetcher.py` |
| OLX image fetcher | `app/olx_image_fetcher.py` | Playwright (headless=False) scrapes up to 4 `<img>` URLs from each OLX listing URL using `*.apollo.olxcdn.com` regex |
| Ceneo finder | `app/bike_offer_ceneo_finder.py` | Single `web_search` call to find 1 current offer on ceneo.pl |
| Decathlon finder | `app/bike_offer_decathlon_finder.py` | Single `web_search` call to find 1 current offer on decathlon.pl |
| Photos finder | `app/bike_photos_finder.py` | Two-step: (1) Claude `web_search` to find manufacturer product page URL, (2) Playwright (`headless=False`) scrapes up to 8 product `<img>` URLs from rendered page; runs in parallel with details and description finders |
| Equipment details finder | `app/equipment_details_finder.py` | Resolves the equipment category (given or inferred), runs one focused component-search call with that category's `equipment_details_{slug}.md` prompt, returns the bike-style component tree (web_search behind a `TODO` flag, mirroring the bike details finder) |
| Equipment description finder | `app/equipment_description_finder.py` | Single `web_search` call with prompt caching for a 4–5 sentence equipment overview |
| Equipment photos finder | `app/equipment_photos_finder.py` | Two-step manufacturer-page → Playwright scrape (mirrors `bike_photos_finder.py`) |
| Equipment review finder | `app/equipment_review_finder.py` | Single `web_search` call → score 0–10, explanation, one source URL (review/forum only, never offers) |
| Test scripts | `scripts/test_search.py` · `scripts/test_details.py` · `scripts/test_review.py` · `scripts/test_offer.py` · `scripts/test_equipment.py` · `scripts/test_equipment_review.py` | Smoke tests for each endpoint (the last is a focused regression for the equipment-review JSON extraction) |
| Prompt eval | `scripts/test_scoring.py` | Pytest eval of category-scoring prompts: deterministic parse tests (`-m "not llm"`) + live directional eval via the `claude` CLI, no API key (`-m llm`). See `backend/README.md`. |

**Endpoint** `POST /v1/bike/search`
- Request: all fields optional, at least one required — `search` (free text), `brand`, `model`, `year` (int), `wheel_size` (string), `is_electric` (bool), `has_suspension` (bool), `is_kids` (bool), `bike_type` (string), `price_max` (int), `frame_size` (string), `rider_height_cm` (int), `rider_weight_kg` (int), `gender` (string), `frame_material` (string), `brake_type` (string), `drivetrain` (string), `belt_drive` (bool), `battery_capacity_wh` (int)
- Structured fields are assembled into an enriched query string via `SearchRequest.enriched_query()` (e.g. `"Brand: Trek, Type: Gravel, Year: 2023 — trail riding"`), then passed through the existing pipeline; all fields participate in the SQLite cache key in `main.py`
- Phase 1: Calls `claude-haiku-4-5-20251001` once per category (11 parallel calls via `asyncio.gather`) to score relevance against the enriched query
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
- Each category response is parsed with the shared `app/json_extract.py` `extract_json()`, which lifts the JSON out of any surrounding narration/code fence — the model routinely prefaces the object with prose
- If a response genuinely contains no JSON: logs the error and skips that category — never returns 502

**Endpoint** `POST /v1/bike/review`
- Request: `{"company": "Canyon", "model": "Grizl CF 7 ESC"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches the curated review sources (tier list and weights in `backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md`), using `app/prompts/bike_review.md` as the system prompt; returns per-source scores tagged by type
- Backend computes a weighted aggregate `rating` (0–10) from the per-source scores: pro/numeric 3×, pro/qualitative 2×, community 1×, normalised; a non-zero rating requires ≥1 professional source
- Returns `{ score: int (0–10), explanation: str (5–10 sentences), ref: [url, ...], rating: float (0–10), sources_used: int }`
- The parser scans **every** text block for the first balanced `{...}` (the model often narrates before emitting the JSON, sometimes inside a ```json fence) and strips `<cite>` markup from the explanation
- If no JSON object is found at all, a **repair pass** re-sends the gathered findings with no tools and an assistant prefill of `{`, forcing a JSON-only reply rather than wasting the completed web search
- Cache: keyed on `{company, model}`; stored only when `ref` is non-empty **and** `sources_used >= 1`, so a degenerate `rating: 0.0` row cannot be pinned for that bike
- On JSON parse error: returns `{ score: 0, explanation: "Review unavailable.", ref: [], rating: 0.0, sources_used: 0 }` — never returns 502

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

**Endpoint** `POST /v1/bike/decathlon`
- Request: `{"company": "Rockrider", "model": "ST 100"}`
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches decathlon.pl using `app/prompts/bike_offer_decathlon.md` as the system prompt
- Returns `{ offers: [{ brand, model, price, is_new, url, photos: [], source: "decathlon.pl" }], info: str }` (1 offer, no photos)
- On JSON parse error: returns `{ offers: [], info: raw_text }` — never returns 502

**Endpoint** `POST /v1/equipment/details`
- Request: `{"company": "POC", "model": "Octal MIPS", "category": "helmets"}` — `company` optional (default `""`), `model` required, `category` optional (`helmets` / `lights` / `locks` / `apparel`; inferred from the item name when omitted, defaulting to `apparel`)
- Runs three calls in parallel via `asyncio.gather` (mirrors `/v1/bike/details`):
  1. `claude-haiku-4-5-20251001` **once** — one focused component search using the resolved category's `app/prompts/equipment_details_{slug}.md` prompt (web_search behind a `TODO` flag, like the bike details finder)
  2. `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — 4–5 sentence overview using `app/prompts/equipment_description.md` with prompt caching
  3. `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — finds the manufacturer product page URL, then Playwright (`headless=False`) scrapes up to 8 product `<img>` URLs; uses `app/prompts/equipment_photos.md`
- Returns `{ company, model, category, description, components: [...], photos: [...] }` — **never** any offer/buy links
- Cache: keyed on `{company, model, category}`; always cached (empty is valid)
- On JSON parse error for the category: logs and skips — never returns 502

**Endpoint** `POST /v1/equipment/review`
- Request: `{"company": "POC", "model": "Octal MIPS"}` — `company` optional, `model` required
- Calls `claude-haiku-4-5-20251001` with `web_search_20250305` **once** — searches 3–5 reviews using `app/prompts/equipment_review.md`; review/forum source links only, never offer links
- Returns `{ score: int (0–10), explanation: str, ref: [url, ...] }`
- Cache: keyed on `{company, model}`; cached only when `ref` is non-empty
- On JSON parse error: returns `{ score: 0, explanation: "Review unavailable.", ref: [] }` — never returns 502

**Bike categories** (defined in `app/categories.py`):
Road, Mountain (MTB), Gravel, Hybrid / Commuter, Electric (e-bike), BMX, Cruiser, Touring, Folding, Cyclocross, Kids

**Equipment categories** (defined in `app/equipment_categories.py`):
Helmets, Lights & electronics, Locks & security, Apparel/bags & accessories. **No** equipment offer endpoints exist — equipment has details + review only, never buy/offer links.

**To add a category**: add an entry to `BIKE_CATEGORIES` in `app/categories.py` and create the matching `app/prompts/<slug>.md`.

### Frontend (`/frontend`)

| Layer | File | Responsibility |
|-------|------|----------------|
| Entry point | `src/main.tsx` | React root, mounts `<App>` |
| App shell | `src/App.tsx` | View router (`search` / `details` / `equipment`), search, details, review, allegro offer, ceneo offer, decathlon offer & used-bike state, plus equipment details/review state; all API calls. Clicking a component element name in a bike's spec tree opens the equipment view for that item |
| Search form | `src/components/SearchInput.tsx` | Controlled input + submit button + collapsible Filters panel (Basic group: brand, model, bike type, year, wheel size, frame size, rider height, max price + electric/suspension/kids toggles; Advanced group: gender, frame material, brake type, drivetrain, belt drive + battery capacity shown only when electric); loading state |
| Result card | `src/components/ResultCard.tsx` | Clickable per-bike card: match score, brand + model, accessories chips, explanation, score bar |
| Loading card | `src/components/LoadingCard.tsx` | Shimmer skeleton matching result card dimensions |
| Details view | `src/components/BikeDetailsView.tsx` | Full spec sheet: back nav, bike header, Overview, unified Offers (MergedOffersSection — pools all four sources Allegro/Ceneo/Decathlon/OLX and splits by each offer's `is_new` flag into two stacked cards: Used on top, New below, each sorted cheapest-first via `OfferCategoryCard`/`OfferRow`), Expert Review, component tree whose element names are clickable → equipment view. Reuses shared building blocks from `BikeDetailsShared.tsx` (component-element links are enabled by passing `onElementSelect`) |
| Equipment details view | `src/components/EquipmentDetailsView.tsx` | Equipment spec page: back nav, category eyebrow + item header, Overview, Expert Review, component tree, shimmer skeleton, error + retry, graceful empty state. **No** offers/used sections. Reuses `BikeDetailsShared.tsx` |
| Shared details building blocks | `src/components/BikeDetailsShared.tsx` | `PhotoGallery`, `DescriptionCard`, `ReviewSection`, `LoadingSkeleton`, `CategorySection` — shared by both the bike and equipment detail views. `DescriptionCard` renders its sources via `CitationChips`; `ReviewSection` renders its `ref[]` as a full-width source table below the explanation — one row per source, `stars | domain | "Read review →"`, stars mapped 0–10 → 1–5 from the aggregate `rating` (falling back to `score` for equipment reviews, which have none) |
| Citation chips | `src/components/CitationChips.tsx` | Google-AI-Overview-style "Sources" row: terracotta pill links showing each source's domain (`target="_blank"`, full URL as hover tooltip). Accepts structured `citations: DescriptionCitation[]` (overview) or a bare `urls: string[]` (review `ref[]`) |
| Shared types | `src/types.ts` | `Bike`, `BikeCategory`, `BikeSubcategory`, `ComponentElement`, `SpecItem`, `BikeDetailsResponse`, `BikeDescription`, `TextSegment`, `DescriptionCitation`, `BikeReviewResponse`, `BikeOffer`, `BikeOfferResponse`, `UsedBikeResponse`, `EquipmentDetailsResponse`, `EquipmentReviewResponse`, `EquipmentDetailsPayload`, `EquipmentReviewPayload`, `SearchPayload`, `SearchFilters` (+ `EMPTY_FILTERS`), `ParseResponse` |
| Styles | `src/index.css` | Tailwind v4 `@theme` tokens, Google Fonts import, keyframe animations |
| Vite config | `vite.config.ts` | Tailwind v4 plugin, `/v1` proxy to backend |

**Design system — Direction 5 "Café Rider":**
- Background `#EDE7DC` · Cards `#F5F1EA` · Accent `#C45C38` (terracotta)
- Display font: Barlow Condensed Bold · Body: Lora · Data labels: JetBrains Mono
- All theme tokens live in `src/index.css` under `@theme { --color-*, --font-* }`

**API integration:**
- `POST /v1/bike/search` `SearchPayload` (free text `search` plus any structured filters — see backend endpoint) → `{ search, bikes: [{ brand, model, accessories, match_score, explanation }] }` (5 bikes)
- `POST /v1/bike/details` `{ "company": "...", "model": "..." }` → `{ company, model, description: BikeDescription, components: BikeCategory[] }`
- `POST /v1/bike/review` `{ "company": "...", "model": "..." }` → `{ score, explanation, ref: string[], rating: number (0–10 aggregate), sources_used: number }`
- `POST /v1/bike/offer` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (allegro.pl)
- `POST /v1/bike/ceneo` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (ceneo.pl)
- `POST /v1/bike/decathlon` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (decathlon.pl)
- `POST /v1/bike/used` `{ "company": "...", "model": "..." }` → `{ offers: BikeOffer[], info: string }` (used bikes from OLX, each with optional `city`)
- `POST /v1/equipment/details` `{ "company"?, "model", "category"? }` → `{ company, model, category, description: BikeDescription, components: BikeCategory[], photos: string[] }` (no offer links)
- `POST /v1/equipment/review` `{ "company"?, "model" }` → `{ score, explanation, ref: string[] }` (review/forum links only)
- All endpoints proxied to backend via Vite — no CORS config needed in development
