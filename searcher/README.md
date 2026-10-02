# Biker Searcher

The on-demand marketplace, photo and review search (TODO-031 OLX, TODO-032 Decathlon, TODO-033 Allegro, bike photos, TODO-037 expert reviews, TODO-041 bike details, TODO-042 equipment). A small FastAPI service that
runs **only when asked**: `POST /v1/search/olx` searches olx.pl for a bike, scrapes each listing's photos with Playwright
and writes the result into the shared bike database (`bike_offer` + `bike_offer_photos`, `source = 'olx.pl'`);
`POST /v1/search/decathlon` searches decathlon.pl the same way (one CLI run, no Playwright) and writes `bike_offer` rows
with `source = 'decathlon.pl'`; `POST /v1/search/allegro` searches allegro.pl (one CLI run, no Playwright — Allegro offers
are stored without photos by design, see "Why the Claude Code CLI") and writes rows with `source = 'allegro.pl'`. The
backend never searches any of the three shops itself —
`POST /v1/bike/used/olx`, `POST /v1/bike/decathlon` and `POST /v1/bike/allegro` are pure DB reads, and
`POST /v1/bike/used/search` / `POST /v1/bike/decathlon/search` / `POST /v1/bike/allegro/search` proxy here when the user
clicks **Poproś o dane** in the "Używane" (OLX) / "Nowe" (Decathlon **and** Allegro at once) card.
`POST /v1/search/photos` finds the bike's manufacturer product page (one CLI run) and scrapes up to 8 photos with
Playwright into `bike_detail_photos` — only for a bike that has no photos yet (the search always runs — no searcher route
reads the DB before searching; stored photos are never replaced); the backend's `POST /v1/bike/photos` is the DB read and `POST /v1/bike/photos/search`
proxies here from the photo gallery's **Poproś o dane** button. `POST /v1/search/review` (TODO-037) searches expert
reviews of the bike (one CLI run, no Playwright) and stores a usable one in `bike_review` + `bike_review_source`; the
backend's `POST /v1/bike/review` is the DB read and `POST /v1/bike/review/search` proxies here from the "Recenzja
eksperta" section's **Poproś o dane** button. `POST /v1/search/details` (TODO-041) collects the bike's Polish description,
a 2-sentence Polish `short_description` and the 8-category component tree (one CLI run, `WebSearch` + `WebFetch`, no
Playwright) with structured output (`found` boolean: `false` when the model could not identify the bike, then nothing is
stored and empty details are returned). Stores a usable result in the bike row's `description` / `short_description` + `bike_component` (updated in place, photos untouched); the
backend's `POST /v1/bike/details` is the DB read and `POST /v1/bike/details/search` proxies here from the Opis / Komponenty
sections' **Poproś o dane** button. `POST /v1/search/equipment/details` and `POST /v1/search/equipment/photos` (TODO-042)
do the same for an equipment item (bike part, helmet, light, lock, apparel/bag/accessory) opened from a bike's spec tree: one CLI run
for the Polish description + `short_description` + spec tree into `equipment` / `equipment_detail` /
`equipment_detail_component`, or the photo search (same hardened scrape) into `equipment_detail_photos`; a successful save
links the element on that bike (`bike_component.equipment_id`). The eight searches share `SEARCHER_MAX_CONCURRENT` busy
slots (default **10**); one more concurrent search is refused with 503, never queued.

## Why the Claude Code CLI

The search is the most token-hungry call in the project (web search + fetch per bike), so it is billed to the Claude
**subscription** instead of the API key: every model call goes through `claude -p` — the Claude Code CLI — with
`ANTHROPIC_API_KEY` stripped from the child environment. Locally that is your logged-in `claude`; on a server it is
`CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`. `--output-format json --json-schema` makes the CLI return an
already-validated `structured_output`, so there is no prose parsing.

```
claude -p "Find current used bike offers on OLX for: Trek Marlin 5" \
  --system-prompt "<app/prompts/bike_offer_olx.md>" --output-format json --json-schema '<schema>' \
  --tools WebSearch,WebFetch --allowedTools WebSearch,WebFetch --permission-prompts none \
  --strict-mcp-config --setting-sources "" --no-session-persistence \
  --exclude-dynamic-system-prompt-sections --model claude-haiku-4-5-20251001
```

Probe on 2026-09-25: Trek Marlin 5 → 5 real OLX listings in 34 s.

Allegro is different (probes 2026-09-26): **allegro.pl answers HTTP 403 (DataDome captcha) to every automated request** —
to the CLI's `WebFetch` and to patchright Chromium alike, headless or headed, already on the homepage. The backend's
SDK-era prompt ("open the listing, open the offer page") therefore did not survive the move: Trek Marlin 5 needed
**286 s** of the 300 s `SEARCHER_CLI_TIMEOUT` to fall back to search results (1 offer), Kross Level 3.0 gave up after
49 s with `offers: []` ("Allegro.pl blocks automated page fetching"). `app/prompts/bike_offer_allegro.md` is therefore a
**CLI-tuned rewrite** (same role, rules and output; WebSearch results only, never `WebFetch` on allegro.pl; price and
condition from the result title/snippet): Kross Level 3.0 → 3 real offers in **67 s** (8 turns), Trek Marlin 4 → 3 real
offers in **75 s** (11 turns, no price visible in the snippets → `"price": ""`). The Playwright photo scrape that shipped
with the move got the same 403 on every offer page — 0 photos in every probe, for ~10 s and a browser launch per run —
so it was **dropped** (decision of 2026-09-26): Allegro offers are stored with `photos: []` by design and the route
launches no browser.

## Layout

| File | Responsibility |
|------|----------------|
| `app/main.py` | FastAPI app: `GET /health` (open) · `POST /v1/search/olx` · `POST /v1/search/decathlon` · `POST /v1/search/allegro` · `POST /v1/search/photos` · `POST /v1/search/review` · `POST /v1/search/details` · `POST /v1/search/equipment/details` · `POST /v1/search/equipment/photos` (all eight `X-Searcher-Key`); one `asyncio.Semaphore(SEARCHER_MAX_CONCURRENT)` (default 10) shared by the eight routes around the whole search (`_run_search` is the offers' common body; `locked()` is true only when every slot is taken, so the busy check holds for any slot count); no route reads the DB before its search (neither does the backend's search proxy: the caller decides whether a paid run is needed); the photo route single-flights identical searches (`_photo_searches`); the default thread pool is sized `SEARCHER_MAX_CONCURRENT + 8` so every slot gets a worker thread |
| `app/photos_finder.py` | The moved `find_bike_photos` (the backend's former `bike_photos_finder`): CLI (`WebSearch` only) → `{url}` of the official manufacturer product page → URL validated (http/https, public addresses only) → patchright opens it once (`domcontentloaded`, 60 s, + 4 s) with every browser request passing a route guard (`_RouteGuard`: http/https to public hosts only) → ≤ 8 `<img src/data-src>` URLs (`_IMG_SRC` / `_SKIP` regexes unchanged; local / non-global-IP image hosts dropped) |
| `app/review_finder.py` | The moved `find_bike_review` (TODO-037, the backend's former `bike_review_finder`): prompt → CLI (`WebSearch,WebFetch`, JSON schema `{score, explanation, per_source[], ref[]}`) → `build_review()`: URLs failing `is_safe_review_url()` (http/https + host, ≤ 2048 chars, not on `BANNED_REVIEW_DOMAINS`) dropped before aggregation, `explanation` capped at 4000 chars, then the old post-processing unchanged: weights `pro_numeric` 3 / `pro_qualitative` 2 / `community` 1, non-zero `rating` only with ≥ 1 pro source, `DISAGREEMENT_THRESHOLD` 3.0 anchoring to the pro/numeric (else pro/qualitative) mean + the Polish disagreement sentence, `ref` sorted Tier 1 → 2 → 3, `<cite>` stripped, score clamped 0–10. The SDK finder's balanced-brace scan and no-tool repair pass are gone — `--json-schema` returns a validated object or the run fails (502). No Playwright |
| `app/details_finder.py` | TODO-041 `find_bike_details`: prompt `bike_details.md` → CLI (`WebSearch,WebFetch`, `DETAILS_SCHEMA` = `description`, `short_description`, `sources[{url,title}]`, `components[8 categories → subcategories → elements → specs]`, all required) → pure `build_details()` (`BikeDescription` built from `sources`, the 8 category shells kept, strings capped to the column widths, `MAX_SOURCES` 8); `is_usable_details` / `has_components` / `empty_details`; `ClaudeCliError` → `SearcherError` (a limit error keeps the 400 path). No Playwright |
| `app/equipment_details_finder.py` · `app/equipment_categories.py` | TODO-042 `find_equipment_details(bike_company, bike_model, element_name, category)`: category = the given slug/name or inferred from the element name (`resolve_category`; the backend's registry `helmets` / `lights` / `locks` / `apparel` plus `parts` = "Bike parts & components" — derailleurs, brakes, wheels, tyres, cockpit, saddle, pedals, suspension — which is the default when no keyword matches; keywords match at a word start and, when several match, the latest one in the name — the head noun — wins, e.g. "Abus T82 Battery Lock" → `locks`; a bare "battery" is a part; `apparel` only on a keyword hit); system prompt = `prompts/equipment_details.md` (Polish description rules, `found`, no shop sources) + `prompts/equipment_details_{slug}.md`; CLI (`WebSearch,WebFetch`, the bike `DETAILS_SCHEMA`) → pure `build_equipment_details()`: company `""`, model = element name, every subcategory under ONE category named after the slug's display name (`[]` when empty), shop / marketplace sources dropped, the bike helpers for description and caps. No Playwright |
| `app/shop_filter.py` | TODO-042 `is_shop_source(url, item_name)`: the code-side shop / marketplace filter for equipment sources (marketplace labels, `SHOP_HOST_TOKENS`, shop-listing paths skipped on the brand's own host). Not applied to bike details, whose prompt uses shop spec pages on purpose |
| `app/equipment_photos_finder.py` | TODO-042 `find_equipment_photos`: `photos_finder.find_product_photos` (the bike photo search's CLI step + guarded scrape, unchanged) with `prompts/equipment_photos.md` |
| `app/equipment_repository.py` | TODO-042 `save_equipment_details` (usable result only: equipment row created if missing, `equipment_detail` updated in place, components replaced for the half produced, one transaction), `save_equipment_photos` (insert-only under `SELECT … FOR UPDATE` on the equipment row), `get_equipment_details` / `get_equipment_photos`, `link_bike_components` (sets `equipment_id` on THIS bike's `bike_component` rows with that element name, Python-normalised; never global; bike missing → stored, not linked, WARNING) |
| `app/config.py` | Env vars (see below), loads `searcher/.env`; `DATABASE_URL` is required — no SQLite fallback |
| `app/claude_cli.py` | `run_structured(system_prompt, user_message, schema, tools=TOOLS)` — the `claude -p` subprocess wrapper (argv list, `stdin=DEVNULL`, timeout, sanitised errors — `ClaudeCliLimitError` when the subscription limit is used up (TODO-038, `limit_message`); `tools` defaults to `WebSearch,WebFetch` for the offer routes, the photo search passes `WebSearch`); `cli_version()` |
| `app/olx_finder.py` | The moved `find_used_bikes`: prompt → CLI → ≤ 5 offers (`is_new=false`, `source=olx.pl`) → photo scrape. Also home of `SearcherError`, the `{info, offers[]}` CLI schema and the `bike_offer` column widths the Decathlon and Allegro finders reuse |
| `app/decathlon_finder.py` | The moved `find_decathlon_offers` (TODO-032): prompt → CLI → ≤ 3 offers (`url` on `https://www.decathlon.pl/`, `is_new` from the page — default true, `source=decathlon.pl`, `photos=[]`, `city=null`). No Playwright |
| `app/allegro_finder.py` | The moved `find_allegro_offers` (TODO-033, the backend's former `bike_offer_finder`): prompt → CLI → ≤ 3 offers (`url` must be an `allegro.pl/oferta/…` or `allegro.pl/produkt/…` page — a search/category page is dropped, `is_new` from the result title/snippet, `price` may be `""` when no snippet showed one, `source=allegro.pl`, `photos=[]`, `city=null`). No Playwright — the photo scrape was dropped because allegro.pl answers 403 to Chromium too |
| `app/olx_image_fetcher.py` · `app/browser_config.py` | Playwright scrape of ≤ 4 `apollo.olxcdn.com` images per listing (copied from the backend); `BROWSER_SLOTS` caps browser launches per process (`BROWSER_MAX_CONCURRENCY`, default 2) for the OLX and photo scrapes alike |
| `app/models.py` · `app/repository.py` | SQLAlchemy over `bike` / `bike_offer` / `bike_offer_photos` / `bike_detail_photos` / `bike_review` / `bike_review_source` / `bike_component` + (TODO-042) `equipment` / `equipment_detail` / `equipment_detail_component` / `equipment_detail_photos` (DDL identical to `backend/app/models.py`; `init_db()` only checks they exist, that `bike_detail_photos` has `bike_id` and that the `bike_detail` table is gone with `bike.description` / `bike.short_description` and `bike_component.bike_id` in place, that `bike_component` has `equipment_id` (TODO-042) and that the table is no longer called `bike_detail_component`, else it **refuses to start** naming `backend/scripts/migrate_photos_bike_id.py` / `backend/scripts/migrate_drop_bike_detail.py` / `backend/scripts/migrate_equipment_tables.py` / `backend/scripts/migrate_rename_bike_component.py` / `backend/scripts/migrate_component_linkable.py` (ISSUE-016, `bike_component.is_linkable`) — run in that order); `save_details(company, model, details)` (only a usable result: bike row created if missing, its details columns updated in place, components replaced — each element keeps its `equipment_id` link — one transaction) and `get_stored_details` read and write the bike's details; `save_offers(company, model, offers, source)` upserts on `url` within this bike **and** source, takes `is_new` from each offer, never re-parents a listing, deletes the bike's stale rows of that source only when something new was stored; `save_photos` writes the bike's photos — insert-only, only when it has none, under a `SELECT … FOR UPDATE` on the bike row; `save_review` upserts the bike's review — written only when `ref` is non-empty and `sources_used >= 1`, replacing the previous review and its sources (`created_at` kept) |
| `app/prompts/bike_offer_olx.md` · `app/prompts/bike_offer_decathlon.md` · `app/prompts/bike_offer_allegro.md` · `app/prompts/bike_photos.md` · `app/prompts/bike_review.md` · `app/prompts/bike_details.md` | The system prompts — OLX and Decathlon byte-for-byte the backend's former prompts; the Allegro one is a CLI-tuned rewrite (WebSearch only, allegro.pl answers 403 to every fetch — see "Why the Claude Code CLI"); the photos one is the backend's with two CLI edits (`WebSearch` for `web_search` — the only tool it gets — and a `{"url": …}` JSON object for the bare URL line); the review one is the backend's former `bike_review.md`; TODO-042 `equipment_details.md` (the shared frame: role, budget, `found`, the backend's `equipment_description.md` rules turned Polish, no shop sources) + `equipment_details_{helmets,lights,locks,apparel}.md` (the backend's category prompts, component lists intact, JSON-only output section replaced by a schema-shaped example) and `equipment_photos.md` (the backend's with the photos prompt's two CLI edits) |
| `scripts/test_equipment_searcher.py` · `scripts/test_equipment_frame.py` · `scripts/test_cli_limit.py` | pytest, no CLI / network, throwaway SQLite (`python -m pytest scripts -q --ignore=scripts/test_searcher.py`): `test_equipment_frame.py` = the 2026-10-02 frame fix (user message builder, `element_type` 422 / forwarding, frame keywords); the equipment builder, saves, links (only this bike, kept across a bike details re-save), insert-only photos, the `equipment_id` start-up check, both routes with stubbed finders (401 / 422 / 503); the limit 400 / 502 mapping on all eight routes |
| `scripts/test_searcher.py` | Smoke test, free: health, 401 ×2 + 422 on `/v1/search/olx` (TC-1–4), 401 + 422 on `/v1/search/decathlon` (TC-5–6), 401 + 422 on `/v1/search/allegro` (TC-7–8), 401 + 422 on `/v1/search/photos` (TC-9–10), 401 + 422 on `/v1/search/review` (TC-12–13), 401 + 422 on `/v1/search/details` (TC-14–15), 401 + 422 on `/v1/search/equipment/details` and `/v1/search/equipment/photos` (TC-16–19) (TC-11 — stored photos answered from the DB — was removed: the searcher no longer reads the DB before a search, so it would start a paid run). No `claude -p` run — the one paid live search of the test set is `backend/scripts/test_search.py` `case_decathlon_search` |

## Run locally

Prerequisites: the `claude` CLI installed and logged in (`claude --version` works), the local PostgreSQL
(`docker start biker-pg`), and Chromium for patchright (`patchright install chromium` — the backend venv already has it).

```bash
cd searcher
copy .env.example .env      # SEARCHER_API_KEY + DATABASE_URL are already filled in for local use

# either reuse the backend venv (it has every dependency) …
..\backend\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8100
# … or make its own
python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt && patchright install chromium
uvicorn app.main:app --port 8100
```

Startup logs the database URL (password hidden) and the CLI version; a missing `DATABASE_URL` aborts startup with a
`RuntimeError`. Then, in a second terminal:

```bash
..\backend\.venv\Scripts\python.exe scripts/test_searcher.py
```

The backend picks it up through `SEARCHER_URL=http://localhost:8100` + `SEARCHER_API_KEY` in `backend/.env`.
Health check: `curl http://127.0.0.1:8100/health` → `{"status":"ok",...}`. The `app-runner` agent (`.claude/agents/app-runner.md`) starts the searcher together with the database, backend and frontend. In a git worktree use the worktree's own port (8101, 8102, …) and set it in that worktree's `backend/.env` `SEARCHER_URL`.

## Environment variables

| Variable | Required | Meaning |
|----------|----------|---------|
| `SEARCHER_API_KEY` | yes | Shared secret; every `POST /v1/search/*` must send it as `X-Searcher-Key`. Unset = 401 for everyone (fail closed) |
| `DATABASE_URL` | yes | SQLAlchemy URL of the bike DB, e.g. `postgresql+psycopg://biker:biker@localhost:5432/biker`. SQLite URLs work too (tests), but there is no default |
| `CLAUDE_CODE_OAUTH_TOKEN` | server | Subscription token for the CLI (`claude setup-token`). Locally the CLI login is used instead |
| `CLAUDE_BIN` | no | Path to the CLI when it is not on `PATH` |
| `SEARCHER_CLAUDE_MODEL` | no | Default `claude-haiku-4-5-20251001` |
| `SEARCHER_CLI_TIMEOUT` | no | Seconds before a CLI run is killed (default 300) |
| `SEARCHER_MAX_CONCURRENT` | no | Searches (CLI runs; the OLX and photo ones also open a browser) allowed at once, counted across **all six** search routes; further requests get 503 "searcher busy" (default **10**; locally that is up to ten CLI runs in one process, on Cloud Run each instance still serves one request and every further search gets its own instance). |
| `BROWSER_MAX_CONCURRENCY` | no | Chromium launches allowed at once in this process (default **2**; each costs 0.5–0.9 GiB). With more search slots than browsers, an OLX or photo search that reaches its scrape waits for a free browser — it is not refused |
| `SEARCHER_CREATE_TABLES` | no | `true` = `create_all()` on startup for a database the backend never touches (scratch tests). Default: refuse to start until `bike` / `bike_offer` / `bike_offer_photos` / `bike_detail_photos` exist — the backend creates them, and two `create_all()`s on one fresh database race. A `bike_detail_photos` without `bike_id` (a database not yet migrated by `backend/scripts/migrate_photos_bike_id.py`) also aborts startup |
| `PLAYWRIGHT_HEADLESS` | no | `true` on servers / in Docker; unset = visible browser for debugging |

Neither the API key, the OAuth token nor the DB password is ever logged.

## Endpoints

### `POST /v1/search/olx`

```http
POST http://localhost:8100/v1/search/olx
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"company": "Trek", "model": "Marlin 5"}
```

```bash
curl -s -X POST http://localhost:8100/v1/search/olx \
  -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key" \
  -d '{"company":"Trek","model":"Marlin 5"}'
```

- `200` → `{"offers": [BikeOffer…], "info": str, "bike_id": int | null, "saved": int}` — `BikeOffer =
  {brand, model, price, is_new: false, url, photos: [str], source: "olx.pl", city: str | null}`. `offers` are exactly
  the rows now stored under this bike (`saved == len(offers)`). A search that finds nothing is a 200 with
  `offers: []` — and the bike's previously stored rows are **kept** (an OLX hiccup must not wipe paid-for data)
- `401` missing/wrong `X-Searcher-Key` (also when `SEARCHER_API_KEY` is unset)
- `422` empty `company`/`model` (after strip) or longer than 255 characters
- `400` `{"detail": "<the CLI's notice>"}` when the `claude -p` run was refused because the **Claude subscription limit
  is used up** (TODO-038) — e.g. `"You've hit your session limit · resets 1am (Europe/Warsaw)"`. Rule
  (`claude_cli.limit_message`): the CLI's JSON result has `is_error: true` **and** either its `result` text carries the
  CLI's limit wording (`You've hit/reached your … limit`, `usage/session/weekly/daily/5-hour/opus/sonnet limit reached`)
  — relayed whitespace-collapsed, `sk-ant-…` redacted, ≤ 300 chars — or `api_error_status` is `429` (then the fixed
  `"Claude subscription usage limit reached"`). `run_structured` raises `ClaudeCliLimitError`, the finder
  `SearcherLimitError`, and `main._search_failed` maps it to 400 on **every** CLI-backed route. Validation errors are
  422, so a searcher 400 means only this; the backend relays it as its own 400 (same shape as its Anthropic
  credit-balance 400)
- `502` `{"detail": "claude CLI failed: exit 1" | "claude CLI timed out after 300 s" | "claude CLI returned no
  structured output" | …}` — a short summary; the CLI's stderr tail is only in the server log
- `503` `{"detail": "searcher busy"}` straight away when `SEARCHER_MAX_CONCURRENT` searches are already running —
  nothing queues, because a queued search would outlive the backend's timeout and end in a second paid run
- `500` `{"detail": "database write failed"}`

**Flow**: (1) `claude -p` once (`--tools WebSearch,WebFetch`, the CLI does the olx.pl searches/fetches) →
(2) Playwright opens each listing URL once (≤ 5, 20 s each; a non-200 page — OLX answers 503 when it rate-limits an
IP — is logged and skipped) and takes ≤ 4 `apollo.olxcdn.com` image URLs →
(3) one DB transaction: bike looked up by normalised brand/model (created with the caller's casing if missing),
`INSERT … ON CONFLICT (url) DO UPDATE` per offer **limited to this bike's rows** (`url` is globally unique and the
prompt's cascade returns model-family listings, so a URL already stored under another bike stays there and is not
reported as saved), its photos rewritten in `display_order`, then — only when at least one offer was stored — every
`olx.pl` row of that bike not in the new set deleted.

### `POST /v1/search/decathlon`

```http
POST http://localhost:8100/v1/search/decathlon
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"company": "Rockrider", "model": "ST 100"}
```

```bash
curl -s -X POST http://localhost:8100/v1/search/decathlon \
  -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key" \
  -d '{"company":"Rockrider","model":"ST 100"}'
```

```json
{
  "offers": [
    {"brand": "Rockrider", "model": "ST 100", "price": "1249 zł", "is_new": true,
     "url": "https://www.decathlon.pl/p/rower-gorski-mtb-27-5-cala-rockrider-st-100/_/R-p-192872",
     "photos": [], "source": "decathlon.pl", "city": null}
  ],
  "info": "",
  "bike_id": 42,
  "saved": 1
}
```

- `200` → the same `{offers, info, bike_id, saved}` shape as `/v1/search/olx`; each `BikeOffer` has `url` on
  `https://www.decathlon.pl/`, `source: "decathlon.pl"`, `is_new` as the shop page says (true unless it is an outlet /
  refurbished item), `photos: []` and `city: null`. At most 3 offers. `offers` are exactly the rows now stored under
  this bike for `source = 'decathlon.pl'` (`saved == len(offers)`); nothing found is a 200 with `offers: []` and the
  bike's previously stored Decathlon rows are **kept**
- `400` / `401` / `422` / `502` / `500` exactly as for `/v1/search/olx`
- `503` `{"detail": "searcher busy"}` — the `SEARCHER_MAX_CONCURRENT` slots (default 10) are **shared** with
  `/v1/search/olx`, `/v1/search/allegro` and `/v1/search/photos` whatever the source, so a Decathlon search is refused
  while every slot is taken (nothing queues)

The backend only calls this for Decathlon house brands (Rockrider, Btwin, Triban, Van Rysel, Elops, Riverside, Stilus,
Tilt, Decathlon) — for any other brand it answers its own `/v1/bike/decathlon/search` without a searcher run.

**Flow**: (1) `claude -p` once with `app/prompts/bike_offer_decathlon.md` (`--tools WebSearch,WebFetch`, the CLI does the
decathlon.pl search/fetch; message `Find current offers on decathlon.pl for: {company} {model}`) — **no Playwright**,
Decathlon offers carry no photos →
(2) one DB transaction: bike looked up by normalised brand/model (created with the caller's casing if missing),
`INSERT … ON CONFLICT (url) DO UPDATE` per offer **limited to this bike's `decathlon.pl` rows** (a URL already stored
under another bike or source stays there and is not reported as saved), then — only when at least one offer was
stored — every `decathlon.pl` row of that bike not in the new set deleted. `bike_offer_photos` is never written.

### `POST /v1/search/allegro`

```http
POST http://localhost:8100/v1/search/allegro
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"company": "Trek", "model": "Marlin 5"}
```

```bash
curl -s -X POST http://localhost:8100/v1/search/allegro \
  -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key" \
  -d '{"company":"Trek","model":"Marlin 5"}'
```

```json
{
  "offers": [
    {"brand": "Trek", "model": "Marlin 5", "price": "2319 zł", "is_new": false,
     "url": "https://allegro.pl/oferta/rower-gorski-mtb-trek-marlin-5-29-l-shimano-hydraulika-poserwisie-noweopony-18571327937",
     "photos": [], "source": "allegro.pl", "city": null}
  ],
  "info": "",
  "bike_id": 12,
  "saved": 1
}
```

- `200` → the same `{offers, info, bike_id, saved}` shape as `/v1/search/olx`; each `BikeOffer` has `url` on an
  `allegro.pl/oferta/…` or `allegro.pl/produkt/…` page (a search or category page is dropped), `source: "allegro.pl"`,
  `is_new` as the search result says (used when the title/snippet says "używany", new when it says new or looks like a
  shop listing — the UI's `is_new` split puts a used listing in the "Używane" card), `price` as shown in the result
  snippet (`""` when none showed it — the UI then says "cena w ofercie"), `photos: []` (always — the Allegro search
  stores no photos, see below) and `city: null`. At most
  3 offers. `offers` are exactly the rows now stored under this bike for `source = 'allegro.pl'`
  (`saved == len(offers)`); nothing found is a 200 with `offers: []` and the bike's previously stored Allegro rows
  are **kept**
- `400` / `401` / `422` / `502` / `500` exactly as for `/v1/search/olx`
- `503` `{"detail": "searcher busy"}` — the `SEARCHER_MAX_CONCURRENT` slots (default 10) are **shared** with
  `/v1/search/olx`, `/v1/search/decathlon` and `/v1/search/photos`: a search of any source is refused while every
  slot is taken (nothing queues)

Probes 2026-09-26 with the CLI-tuned prompt: Kross Level 3.0 → 3 real offers in **67 s**, Trek Marlin 4 → 3 real offers
in **75 s** (the SDK-era prompt needed 286 s or gave up empty — allegro.pl answers 403 to every fetch, see "Why the
Claude Code CLI"). The Playwright photo pass those probes still ran added ~10 s and a browser launch per run and returned
0 photos every time (403 on the offer pages too), which is why it was removed — this route launches no browser.

**Flow**: (1) `claude -p` once with `app/prompts/bike_offer_allegro.md` (`--tools WebSearch,WebFetch`; the prompt tells the
CLI to use WebSearch only and never fetch allegro.pl; message `Find current offers on allegro for: {company} {model}`) —
**no Playwright**, Allegro offers carry no photos (allegro.pl answers 403 to Chromium as well, so the scrape was dropped) →
(2) one DB transaction: bike looked up by normalised brand/model (created with the caller's casing if missing),
`INSERT … ON CONFLICT (url) DO UPDATE` per offer **limited to this bike's `allegro.pl` rows** (a URL already stored
under another bike or source stays there and is not reported as saved),
then — only when at least one offer was stored — every `allegro.pl` row of that bike not in the new set deleted.
`bike_offer_photos` is never written. OLX
and Decathlon rows of the same bike are untouched, so the Decathlon search running in parallel never collides with it.

### `POST /v1/search/photos`

```http
POST http://localhost:8100/v1/search/photos
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"company": "Trek", "model": "Marlin 4"}
```

```bash
curl -s -X POST http://localhost:8100/v1/search/photos \
  -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key" \
  -d '{"company":"Trek","model":"Marlin 4"}'
```

```json
{
  "photos": [
    "https://res.cloudinary.com/trekbikes/image/upload/f_auto,c_fill,ar_4:3,w_1080,q_auto/Marlin4_21469_B_Portrait",
    "https://res.cloudinary.com/trekbikes/image/upload/f_auto,c_fill,ar_4:3,w_1080,q_auto/1010600_2018_B_1_Marlin_4",
    "https://res.cloudinary.com/trekbikes/image/upload/f_auto,c_fill,ar_4:3,w_1080,q_auto/Marlin4_21469_B_Alt1"
  ],
  "bike_id": 44,
  "saved": 6
}
```

(shortened — that run stored 6 photos.) Probe 2026-09-29, Trek Marlin 4: CLI 18 s (4 turns) →
`https://www.trekbikes.com/us/en_US/bikes/mountain-bikes/cross-country-mountain-bikes/marlin/marlin-4/p/21469/` →
scrape 17 s → 6 photos, **36 s** end to end.

- `200` → `{"photos": [str], "bike_id": int | null, "saved": int}` — `photos` are the bike's photo URLs in
  `display_order`. **The search always runs** — like the offer routes, the route reads nothing from the DB first
  (whether a search is worth a paid run is the backend's / UI's call). `photos` are the ≤ 8 URLs now stored
  (`saved == len(photos)`); when the bike already had photos (stored before, or by another search that finished first)
  those are returned with `saved: 0` and nothing is written. A search that finds nothing is a 200 with `photos: []`, `saved: 0`
  and writes **nothing** — not even a bike row, so `bike_id` is `null` for a bike the DB does not know. Photos are never
  deleted or replaced
- `400` (subscription limit) / `401` / `422` exactly as for `/v1/search/olx`
- `502` `{"detail": "claude CLI failed: exit 1" | …}` when the product-page CLI run fails (the backend's old finder
  swallowed this into `photos: []`; here it is an error so the UI's button becomes clickable again). No product page
  found, a rejected URL or a failed scrape is **not** an error — a 200 with `photos: []`
- `503` `{"detail": "searcher busy"}` — the `SEARCHER_MAX_CONCURRENT` slots (default 10) are **shared** with the three
  offer routes (nothing queues). An identical request (same normalised brand/model) arriving while that bike's search
  runs **joins** it instead — one paid run, and both callers get its result **including the same `saved`** (a joined
  caller therefore sees e.g. `saved: 6` although only the first request wrote those rows — `saved` counts the search's
  writes, not the caller's), and it never counts as busy
- `500` `{"detail": "database write failed"}`

**Flow**: (1) busy check, slot taken (no DB read before the search) →
(2) `claude -p` once with `app/prompts/bike_photos.md` — `--tools WebSearch` **only** (no `WebFetch`, unlike the offer
routes: the URL comes from search results, and text injected into a result cannot make the CLI fetch arbitrary URLs),
JSON schema `{url}`; message `Find the official product page URL for the {company} {model} bicycle on the
manufacturer's website.` → the official manufacturer product page URL, `""` when none or longer than 2048 characters →
(3) the URL is checked before any browser sees it: `http`/`https` only, no credentials, no `localhost` / `*.local` /
`*.internal` / `*.lan` / `*.home.arpa` name, no non-global IP literal in any form (dotted, IPv6, IPv4-mapped IPv6,
decimal `2130706433`, hex / octal), and every address its host resolves to must be public (no private, loopback,
link-local — e.g. the cloud metadata server `169.254.169.254` — reserved or multicast); a rejected URL ends the search
with `photos: []` →
(4) patchright Chromium (one `BROWSER_SLOTS` slot, `PLAYWRIGHT_HEADLESS`, launched with
`--host-resolver-rules=MAP metadata.google.internal ~NOTFOUND`, service workers blocked) opens that page **once**
(`domcontentloaded`, 60 s timeout, then 4 s wait, Chrome 124 desktop user agent, 1920×1080). **Every request the
browser makes** — the page, each redirect hop, sub-resources, fetch/XHR, JS navigations — passes a route guard
(`context.route("**/*")`) that aborts it unless it is `http`/`https` to a host passing the check in (3); host verdicts
are cached per scrape, `data:` / `blob:` URLs (no network) pass. The page's HTML and the regexes below are unchanged,
so a normal manufacturer page yields the same photos; the log line `photos scraped` reports `requests_allowed` /
`requests_aborted` →
(5) the first ≤ 8 distinct `src` / `data-src` image URLs (`.jpg/.jpeg/.png/.webp` or Cloudinary `/image/upload/`, minus
logos / icons / badges / payment marks / GIFs, minus URLs longer than 2048 characters and — string check, no DNS —
URLs on a local name or a non-global IP literal, since every viewer's browser loads them as `<img>`) →
(6) one DB transaction, only when (5) found something: bike created with the caller's casing if missing,
`SELECT … FOR UPDATE` on the bike row, photo rows re-checked — any there → kept and returned, nothing written —
otherwise one `bike_detail_photos` row per URL with `display_order` 0..n-1.

**Accepted limitation — DNS rebinding.** The guard resolves a host, then Chromium resolves it again when it connects; a
hostile DNS server answering public first and private second would get past the guard. Not mitigated (it would need
pinning the resolved address into the browser); the metadata name itself is additionally mapped to NOTFOUND inside
Chromium. Image hosts in (5) are checked by string only — a public-looking name that resolves privately is stored.

### `POST /v1/search/review`

```http
POST http://localhost:8100/v1/search/review
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"company": "Canyon", "model": "Grizl CF 7 ESC"}
```

```bash
curl -s -X POST http://localhost:8100/v1/search/review   -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key"   -d '{"company":"Canyon","model":"Grizl CF 7 ESC"}'
```

```json
{
  "review": {
    "score": 8,
    "explanation": "Canyon Grizl CF 7 ESC jest powszechnie chwalony za wszechstronną geometrię gravelową…",
    "ref": [
      "https://www.bikeradar.com/reviews/bikes/gravel-bikes/canyon-grizl-cf-7-esc-review",
      "https://www.reddit.com/r/gravelcycling/comments/xxxx"
    ],
    "rating": 7.8,
    "sources_used": 3
  },
  "bike_id": 12,
  "saved": 1
}
```

- `200` → `{"review": {score, explanation, ref, rating, sources_used}, "bike_id": int | null, "saved": 0 | 1}` —
  `review` has the backend's `BikeReviewResponse` shape (`score` 0–10 int, `explanation` Polish, `ref` tier-sorted URLs,
  `rating` 0–10 one decimal, `sources_used`). **The search always runs** — no DB read first, like the offer routes
  (the backend's `/v1/bike/review/search` does not pre-read the DB either). A usable result (`ref` non-empty **and** `sources_used >= 1`)
  replaces the bike's stored review and its sources → `saved: 1`, `review` = what was stored. Anything less writes and
  deletes **nothing** (not even a bike row) → `saved: 0`, `review` = what this run found (score 0 / `ref: []` /
  `sources_used: 0` — "no review"; `bike_id` then `null` for a bike the DB does not know)
- `400` (subscription limit) / `401` / `422` exactly as for `/v1/search/olx`
- `502` `{"detail": "claude CLI failed: exit 1" | …}` when the CLI run fails (the backend's old finder swallowed a
  missing JSON into the fallback review; here the CLI either returns the schema-validated object or fails)
- `503` `{"detail": "searcher busy"}` — the `SEARCHER_MAX_CONCURRENT` slots (default 10) are **shared** with the
  other five routes (nothing queues)
- `500` `{"detail": "database write failed"}`

**Flow**: (1) busy check, slot taken (no DB read before the search) →
(2) `claude -p` once with `app/prompts/bike_review.md` (`--tools WebSearch,WebFetch`, JSON schema
`{score, explanation, per_source[{source, type, score, url}], ref[]}`, message `Find reviews for: {company} {model}`) —
**no Playwright** → (3) `build_review()`: every `per_source` entry and `ref` URL failing `is_safe_review_url()` is
dropped first — `per_source` entries **before** aggregation, so they never count in `rating` / `sources_used`. A safe URL
is `http`/`https` with a non-empty host (no `javascript:` / `data:` / relative / scheme-less value — every viewer's
browser gets it as a link), ≤ 2048 characters, and not on a `BANNED_REVIEW_DOMAINS` host (`escapecollective.com`,
`velominati.com`, `www.` stripped, subdomains included — the prompt forbids them, the probe still cited one;
`backend/scripts/copy_review_cache_to_table.py` applies the same rule). Then per-source scores of a known tier
(`pro_numeric` / `pro_qualitative` / `community`) clamped to 0–10, weighted mean 3 / 2 / 1 (0.0 and `sources_used: 0`
without a pro source); spread > 3.0 → the rating anchors to the pro/numeric mean (else pro/qualitative) and a Polish
disagreement sentence is appended to `explanation`; `<cite>` markup stripped; `explanation` capped at 4000 characters
(`EXPLANATION_MAX_LEN`, the disagreement sentence included and kept whole); `ref` sorted Tier 1 → 2 → 3; no
`explanation` → the fallback review `{0, "Recenzja niedostępna.", [], 0.0, 0}` → (4) only for a usable review, one DB
transaction: bike looked up by normalised brand/model (created with the caller's casing if missing),
`INSERT … ON CONFLICT (bike_id) DO UPDATE` on `bike_review` (score, explanation, rating, sources_used, updated_at;
`created_at` kept), the review's `bike_review_source` rows deleted and re-inserted with `display_order` = index in
`ref`.

### `POST /v1/search/details`

```http
POST http://localhost:8100/v1/search/details
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"company": "Canyon", "model": "Grizl CF 7 ESC"}
```

```bash
curl -s -X POST http://localhost:8100/v1/search/details   -H "Content-Type: application/json" -H "X-Searcher-Key: dev-local-searcher-key"   -d '{"company":"Canyon","model":"Grizl CF 7 ESC"}'
```

```json
{
  "details": {
    "company": "Canyon",
    "model": "Grizl CF 7 ESC",
    "description": {
      "text": "Canyon Grizl CF 7 ESC to gravelowy rower z ramą z włókna węglowego…",
      "segments": [{"text": "Canyon Grizl CF 7 ESC to gravelowy rower z ramą z włókna węglowego…", "citations": [{"url": "https://www.canyon.com/…", "title": "Grizl CF 7 ESC", "cited_text": ""}]}],
      "citations": [{"url": "https://www.canyon.com/…", "title": "Grizl CF 7 ESC", "cited_text": ""}]
    },
    "components": [
      {"category": "Frame", "subcategories": [{"subcategory": "Frame", "elements": [
        {"name": "Grizl CF", "description": "Rama z włókna węglowego…", "is_linkable": true, "specs": [{"key": "Material", "value": "Carbon"}]}
      ]}]},
      {"category": "Lighting", "subcategories": []}
    ],
    "short_description": "Canyon Grizl CF 7 ESC to lekki gravel z karbonową ramą. Nadaje się na długie trasy i lekki bikepacking."
  },
  "bike_id": 12,
  "saved": 1
}
```

- `200` → `{"details": {company, model, description, components, short_description}, "bike_id": int | null, "saved": 0 | 1}` —
  `details` has the backend's `BikeDetailsResponse` shape (`description` is the Polish 4–5 sentence overview as
  `{text, segments, citations}`, `short_description` the Polish 2-sentence summary written by the model, `components` the
  category tree — always the 8 category shells Frame, Drivetrain, Brakes, Wheels, Cockpit, Saddle & Seatpost, Lighting,
  Accessories in that order, an empty one has `subcategories: []`; `category` / `subcategory` / spec `key` names English,
  element `description` Polish; each element's `is_linkable` is the model's verdict — ISSUE-016 — `true` only for a
  specific product with a brand and model / part number, `false` for "None included", paperwork and generic parts, stored
  per row in `bike_component.is_linkable`; a missing or non-boolean flag is stored as `false`). **The search always runs** — no DB read first, like the offer routes (the backend's
  `/v1/bike/details/search` does not pre-read the DB either). A
  usable result (non-empty components **or** non-empty description) is stored → `saved: 1`, `details` = what is stored
  after the write (read back once the search is done). Anything less writes and deletes **nothing** (not even a bike row) → `saved: 0`, `details` = what is stored
  (possibly partial) or the empty details (`bike_id` then `null` for a bike the DB does not know)
- `400` (subscription limit) / `401` / `422` exactly as for `/v1/search/olx`
- `502` `{"detail": "claude CLI failed: exit 1" | …}` when the CLI run fails
- `503` `{"detail": "searcher busy"}` — the `SEARCHER_MAX_CONCURRENT` slots (default 10) are **shared** with the
  other seven routes (nothing queues)
- `500` `{"detail": "database write failed"}`

**Flow**: (1) busy check, slot taken (no DB read before the search) →
(2) `claude -p` once with `app/prompts/bike_details.md` (`--tools WebSearch,WebFetch`, JSON schema with required `found` boolean
`{found, description, short_description, sources[{url, title}], components[{category, subcategories[{subcategory, elements[{name,
description, is_linkable, specs[{key, value}]}]}]}]}`, message `Find the full details for: {company} {model}`; budget in the prompt
about 6 searches / 3 fetches) — **no Playwright** → (3) `build_details()` (`app/details_finder.py`, pure): when `found: false` (model could not identify the bike)
no further processing and empty details are returned (never stored). Otherwise the `BikeDescription` is built from `sources` (the CLI has no per-block citations) — `text` = the description, one segment
carrying every source, `citations` = the sources with `cited_text: ""` (≤ 8, http/https URLs ≤ 2048 chars only); string
lengths capped to the column widths; the 8 category shells kept, an unknown category appended, a repeated one merged, a
keyless spec dropped → (4) only for a usable result, one DB transaction: bike row created with the caller's casing if
missing (a placeholder casing equal to its normalised form is upgraded), the bike row's `description` / `short_description` **updated in place**
(stable id; `description` JSON and `short_description` replaced) or inserted, the `bike_component` rows replaced
with the flattened tree (one row per spec, an element without specs gets one row with NULL spec columns). Only the half
this run produced is replaced: a description-only result keeps the stored components, a components-only result keeps the
stored description. Photos hang off `bike` and are never touched. TODO-042: a replaced row's `equipment_id` link is
carried to the new row whose Python-normalised element name matches (first link wins), and every element in `details`
carries its `equipment_id` (`null` when not linked). Probed 2026-09-30 (`claude` 2.1.286, Haiku): KROSS Esker
Eco 53 s / $0.12, Trek Marlin 5 142 s / $0.18, 8 of 8 categories both times (Lighting is often empty).

### `POST /v1/search/equipment/details`

```http
POST http://localhost:8100/v1/search/equipment/details
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"bike_company": "Canyon", "bike_model": "Grizl CF 7 ESC", "element_name": "Abus Hyban 2.0", "category": "helmets"}
```

```json
{
  "details": {
    "company": "", "model": "Abus Hyban 2.0", "category": "helmets",
    "description": {"text": "Abus Hyban 2.0 to kask miejski…", "segments": [{"text": "Abus Hyban 2.0 to kask miejski…", "citations": [{"url": "https://www.abus.com/…", "title": "Hyban 2.0", "cited_text": ""}]}], "citations": [{"url": "https://www.abus.com/…", "title": "Hyban 2.0", "cited_text": ""}]},
    "components": [{"category": "Helmets", "subcategories": [{"subcategory": "Construction", "elements": [
      {"name": "ABS hardshell", "description": "Twarda skorupa z ABS…", "specs": [{"key": "Weight", "value": "450 g (M)"}]}]}]}],
    "short_description": "Miejski kask z twardą skorupą i tylną lampką LED. Do codziennych dojazdów.",
    "equipment_id": 7
  },
  "equipment_id": 7,
  "saved": 1
}
```

- Body: `bike_company`, `bike_model`, `element_name` non-empty (stripped) and ≤ 255 characters, `category` optional ≤ 32
  (a slug or display name; blank, missing or unknown → inferred from `element_name`, `parts` as the default),
  `element_type` optional ≤ 255 (the element's subcategory on the bike's spec sheet, e.g. `"Frame"`; blank → absent;
  sent by the backend from the stored row) → else `422`
- `200` → `details` has the backend's `EquipmentDetailsResponse` shape (no `photos`; `category` = the slug). **The search
  always runs** (no DB read first). A usable result (components **or** description) is stored → `saved: 1`, `details` =
  what is stored after the write. Anything less writes, deletes and links **nothing** → `saved: 0`, `details` = the empty
  details and `equipment_id` `null` (also when the item exists — the UI then falls back to the by-name read)
- `400` (subscription limit) / `401` / `502` / `503` `{"detail": "searcher busy"}` (the same slots as the other seven
  routes) / `500` `{"detail": "database write failed"}` exactly as for `/v1/search/details`

**Flow**: (1) busy check, slot taken → (2) `claude -p` once — system prompt `app/prompts/equipment_details.md` +
`app/prompts/equipment_details_{slug}.md`, `--tools WebSearch,WebFetch`, the bike details JSON schema (`found`,
`description`, `short_description`, `sources`, `components`), message naming the item and the bike as context (`Find the
specifications and an overview of the bike component or equipment item "{element_name}" (listed under "{element_type}"
on the spec sheet) (category: {display name}). It is a component listed on the "{bike_company} {bike_model}" bicycle's
spec sheet …`, built by the pure `build_user_message()`; the "listed under" part only when `element_type` is given; when
the normalised element name equals the bike's company + model or its model alone — a frame named after the bike — one
more sentence says it is the {element_type, else "frame"} of that bike (the frameset), not the complete bike, and to
answer `found: true` when the bike maker documents it (fix 2026-10-02; before it such a frame came back `found: false`);
every client value is sanitised first — double quotes,
backticks, control characters and line separators become spaces, whitespace collapsed — and the prompt says quoted names
are data, not instructions) — **no Playwright** → (3) `build_equipment_details()`:
`found: false` → empty, never stored; else the description built from `sources` minus shops (`app/shop_filter.py`:
a marketplace host label — allegro, olx, ceneo, decathlon, amazon, ebay …; a shop token in the host — shop, store,
sklep, parts, powered, bike24, wiggle …; or a listing path — /product/, /shop/, /p/<digits>, /dp/, /cart … — unless the
host carries the item's brand, so a maker's product page stays; all dropped → the description is kept without sources), every subcategory under one category named after the slug, strings
capped → (4) only for a usable result, one DB transaction: `equipment` row `(category, "", element_name)` looked up on
the Python-normalised identity, else `INSERT … ON CONFLICT DO NOTHING` + re-read (never committed on its own, so a failed
write leaves no row), then `SELECT … FOR UPDATE` on it (two bikes saving one item run one after the other),
`equipment_detail` updated in place or inserted, the
`equipment_detail_component` rows replaced for the half produced, and `bike_component.equipment_id` set on the
rows of **this** bike (looked up, never created) whose element name matches — no other bike is touched.

### `POST /v1/search/equipment/photos`

```http
POST http://localhost:8100/v1/search/equipment/photos
Content-Type: application/json
X-Searcher-Key: dev-local-searcher-key

{"bike_company": "Canyon", "bike_model": "Grizl CF 7 ESC", "element_name": "Abus Hyban 2.0", "category": "helmets"}
```

```json
{"photos": ["https://www.abus.com/…/hyban-2-0-1.jpg", "https://www.abus.com/…/hyban-2-0-2.jpg"], "equipment_id": 7, "saved": 2}
```

- Same body rules as above. `200` → `photos` = the item's photos now stored, in `display_order`; when the item already
  had photos they come back with `saved: 0` (never replaced) and the element is still linked; a search that finds nothing
  writes nothing (no equipment row, no link) and is a 200 with `photos: []`. `equipment_id` is `null` whenever nothing
  was written and nothing linked. Same `400` / `401` / `422` / `502` / `503` / `500` mapping
- No single-flight inside the searcher (unlike `/v1/search/photos`); the backend's proxy single-flights and the
  insert runs under the equipment row lock

**Flow**: (1) busy check, slot taken → (2) `claude -p` once with `app/prompts/equipment_photos.md`, `--tools WebSearch`
**only**, schema `{url}`, the message from the same `build_user_message()` as the details route (element type and the
"named after the bike" sentence included) → (3)–(5) exactly steps (3)–(5) of `/v1/search/photos` (`photos_finder.find_product_photos`:
public-URL check, patchright once behind the route guard, ≤ 8 filtered `<img>` URLs) → (6) only when (5) found
something, one DB transaction: `equipment` row created if missing, `SELECT … FOR UPDATE` on it, photo rows re-checked
(any there → kept), otherwise one `equipment_detail_photos` row per URL (same sanitised message and row lock as the
details route) (`display_order` 0..n-1), then the element is
linked on this bike as in the details route.

### `GET /health`

No auth. `{"status": "ok", "claude_cli": "2.1.282 (Claude Code)" | null, "database": true | false}`.

## Docker

`searcher/Dockerfile`: `python:3.14-slim` + Node 24 (nodesource) + `@anthropic-ai/claude-code` **pinned** to the
version `app/claude_cli.py` was proven on (`ARG CLAUDE_CODE_VERSION=2.1.283`, `DISABLE_AUTOUPDATER=1` — bump it
deliberately and re-run `scripts/test_searcher.py`) + patchright Chromium, non-root user `searcher` with a writable
`HOME` (the CLI keeps state in `~/.claude`), `PLAYWRIGHT_HEADLESS=true`, `PORT=8100`. No secrets in the image — `CLAUDE_CODE_OAUTH_TOKEN`, `SEARCHER_API_KEY` and `DATABASE_URL` come from the
environment.

The root `docker-compose.yml` runs it as the `searcher` service on `8100` against the same **Cloud SQL** database as the
backend (through the `cloudsql-proxy` sidecar and the same mounted pgpass file), started after the backend with
`restart: on-failure` (the backend's `init_db()` creates the shared tables), and gives the backend
`SEARCHER_URL=http://searcher:8100`. Put `CLAUDE_CODE_OAUTH_TOKEN` and `SEARCHER_API_KEY` in `searcher/.env` for the
container — there is no interactive login inside it.

```bash
docker compose up --build -d searcher
curl -s http://localhost:8100/health
```

## Cloud Run

Deployed by the root `scripts/deploy.ps1` (`-Only searcher`, or as part of `all`, which deploys searcher → backend → frontend)
as the Cloud Run service `biker-searcher` in `europe-central2`, project `biker-engine-prod`:

- image `europe-central2-docker.pkg.dev/biker-engine-prod/biker/searcher:<git sha>` built from `searcher/Dockerfile`;
- **scale to zero** (`--min-instances 0`), `--max-instances 10`, `--concurrency 1` (one CLI run per 2 GiB instance, plus
  one Chromium for an OLX or photo search; up to ten searches of any kind at once — on Cloud Run the parallelism comes
  from the instance count, not from `SEARCHER_MAX_CONCURRENT`, whose default 10 only matters for a single local /
  compose process; an eleventh concurrent search hits Cloud Run's **429**, which the backend maps to `SearcherBusy`
  like the searcher's own 503; with one request per instance the photo route's single-flight never meets a second
  identical request there — the `FOR UPDATE` re-check is what keeps two instances from double-inserting), `--timeout 900` (a search is minutes; the backend waits at most 600 s),
  `--cpu 2 --memory 2Gi --cpu-boost`;
- the same Cloud SQL socket as the backend: `DATABASE_URL=postgresql+psycopg://biker@/biker?host=/cloudsql/<instance>`
  with `PGPASSWORD` from the `db-password` secret;
- secrets from **Secret Manager** as env vars: `searcher-api-key` → `SEARCHER_API_KEY` (the backend reads the same secret),
  `claude-code-oauth-token` → `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token` on the developer machine);
  the service account `biker-run` needs `roles/secretmanager.secretAccessor` on both;
- the backend service gets `SEARCHER_URL=https://biker-searcher-….run.app` and `SEARCHER_API_KEY` from the same secret;
- who may call it is a one-time IAM decision outside the script: `roles/run.invoker` for `allUsers` (the endpoint is
  protected by the shared secret, and the backend calls it over its public URL).

Cold start ≈ 10–20 s (image ≈ 2.7 GB); the first request then waits on the CLI as usual.
