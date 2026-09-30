# Biker Searcher

The on-demand marketplace, photo and review search (TODO-031 OLX, TODO-032 Decathlon, TODO-033 Allegro, bike photos, TODO-037 expert reviews). A small FastAPI service that
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
Playwright into `bike_detail_photos` — only for a bike that has no photos yet (stored photos are returned without a
search and are never replaced); the backend's `POST /v1/bike/photos` is the DB read and `POST /v1/bike/photos/search`
proxies here from the photo gallery's **Poproś o dane** button. `POST /v1/search/review` (TODO-037) searches expert
reviews of the bike (one CLI run, no Playwright) and stores a usable one in `bike_review` + `bike_review_source`; the
backend's `POST /v1/bike/review` is the DB read and `POST /v1/bike/review/search` proxies here from the "Recenzja
eksperta" section's **Poproś o dane** button. The five searches share `SEARCHER_MAX_CONCURRENT` busy
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
| `app/main.py` | FastAPI app: `GET /health` (open) · `POST /v1/search/olx` · `POST /v1/search/decathlon` · `POST /v1/search/allegro` · `POST /v1/search/photos` · `POST /v1/search/review` (all five `X-Searcher-Key`); one `asyncio.Semaphore(SEARCHER_MAX_CONCURRENT)` (default 10) shared by the five routes around the whole search (`_run_search` is the offers' common body; `locked()` is true only when every slot is taken, so the busy check holds for any slot count); the photo route answers stored photos and the review route a usable stored review before the busy check; the photo route single-flights identical searches (`_photo_searches`); the default thread pool is sized `SEARCHER_MAX_CONCURRENT + 8` so every slot gets a worker thread |
| `app/photos_finder.py` | The moved `find_bike_photos` (the backend's former `bike_photos_finder`): CLI (`WebSearch` only) → `{url}` of the official manufacturer product page → URL validated (http/https, public addresses only) → patchright opens it once (`domcontentloaded`, 60 s, + 4 s) with every browser request passing a route guard (`_RouteGuard`: http/https to public hosts only) → ≤ 8 `<img src/data-src>` URLs (`_IMG_SRC` / `_SKIP` regexes unchanged; local / non-global-IP image hosts dropped) |
| `app/review_finder.py` | The moved `find_bike_review` (TODO-037, the backend's former `bike_review_finder`): prompt → CLI (`WebSearch,WebFetch`, JSON schema `{score, explanation, per_source[], ref[]}`) → `build_review()`: URLs failing `is_safe_review_url()` (http/https + host, ≤ 2048 chars, not on `BANNED_REVIEW_DOMAINS`) dropped before aggregation, `explanation` capped at 4000 chars, then the old post-processing unchanged: weights `pro_numeric` 3 / `pro_qualitative` 2 / `community` 1, non-zero `rating` only with ≥ 1 pro source, `DISAGREEMENT_THRESHOLD` 3.0 anchoring to the pro/numeric (else pro/qualitative) mean + the Polish disagreement sentence, `ref` sorted Tier 1 → 2 → 3, `<cite>` stripped, score clamped 0–10. The SDK finder's balanced-brace scan and no-tool repair pass are gone — `--json-schema` returns a validated object or the run fails (502). No Playwright |
| `app/config.py` | Env vars (see below), loads `searcher/.env`; `DATABASE_URL` is required — no SQLite fallback |
| `app/claude_cli.py` | `run_structured(system_prompt, user_message, schema, tools=TOOLS)` — the `claude -p` subprocess wrapper (argv list, `stdin=DEVNULL`, timeout, sanitised errors — `ClaudeCliLimitError` when the subscription limit is used up (TODO-038, `limit_message`); `tools` defaults to `WebSearch,WebFetch` for the offer routes, the photo search passes `WebSearch`); `cli_version()` |
| `app/olx_finder.py` | The moved `find_used_bikes`: prompt → CLI → ≤ 5 offers (`is_new=false`, `source=olx.pl`) → photo scrape. Also home of `SearcherError`, the `{info, offers[]}` CLI schema and the `bike_offer` column widths the Decathlon and Allegro finders reuse |
| `app/decathlon_finder.py` | The moved `find_decathlon_offers` (TODO-032): prompt → CLI → ≤ 3 offers (`url` on `https://www.decathlon.pl/`, `is_new` from the page — default true, `source=decathlon.pl`, `photos=[]`, `city=null`). No Playwright |
| `app/allegro_finder.py` | The moved `find_allegro_offers` (TODO-033, the backend's former `bike_offer_finder`): prompt → CLI → ≤ 3 offers (`url` must be an `allegro.pl/oferta/…` or `allegro.pl/produkt/…` page — a search/category page is dropped, `is_new` from the result title/snippet, `price` may be `""` when no snippet showed one, `source=allegro.pl`, `photos=[]`, `city=null`). No Playwright — the photo scrape was dropped because allegro.pl answers 403 to Chromium too |
| `app/olx_image_fetcher.py` · `app/browser_config.py` | Playwright scrape of ≤ 4 `apollo.olxcdn.com` images per listing (copied from the backend); `BROWSER_SLOTS` caps browser launches per process (`BROWSER_MAX_CONCURRENCY`, default 2) for the OLX and photo scrapes alike |
| `app/models.py` · `app/repository.py` | SQLAlchemy over `bike` / `bike_offer` / `bike_offer_photos` / `bike_detail_photos` / `bike_review` / `bike_review_source` (DDL identical to `backend/app/models.py`; `init_db()` only checks they exist and that `bike_detail_photos` has `bike_id`); `save_offers(company, model, offers, source)` upserts on `url` within this bike **and** source, takes `is_new` from each offer, never re-parents a listing, deletes the bike's stale rows of that source only when something new was stored; `get_stored_photos` / `save_photos` read and write the bike's photos — insert-only, only when it has none, under a `SELECT … FOR UPDATE` on the bike row; `get_stored_review` / `save_review` read and upsert the bike's review — written only when `ref` is non-empty and `sources_used >= 1`, replacing the previous review and its sources (`created_at` kept) |
| `app/prompts/bike_offer_olx.md` · `app/prompts/bike_offer_decathlon.md` · `app/prompts/bike_offer_allegro.md` · `app/prompts/bike_photos.md` · `app/prompts/bike_review.md` | The system prompts — OLX and Decathlon byte-for-byte the backend's former prompts; the Allegro one is a CLI-tuned rewrite (WebSearch only, allegro.pl answers 403 to every fetch — see "Why the Claude Code CLI"); the photos one is the backend's with two CLI edits (`WebSearch` for `web_search` — the only tool it gets — and a `{"url": …}` JSON object for the bare URL line); the review one is the backend's former `bike_review.md` |
| `scripts/test_searcher.py` | Smoke test, free: health, 401 ×2 + 422 on `/v1/search/olx` (TC-1–4), 401 + 422 on `/v1/search/decathlon` (TC-5–6), 401 + 422 on `/v1/search/allegro` (TC-7–8), 401 + 422 on `/v1/search/photos` (TC-9–10), 401 + 422 on `/v1/search/review` (TC-12–13), a bike that already has photos → 200 from the DB, `saved: 0`, < 5 s (TC-11; `SEARCHER_PHOTOS_BIKE="Brand\|Model"` or the first such bike in `DATABASE_URL`, posted only after `DATABASE_URL` confirms ≥ 1 photo row, else SKIP — `DATABASE_URL` must be the running searcher's database, or TC-11 could start a paid search). No `claude -p` run — the one paid live search of the test set is `backend/scripts/test_search.py` `case_decathlon_search` |

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
| `SEARCHER_MAX_CONCURRENT` | no | Searches (CLI runs; the OLX and photo ones also open a browser) allowed at once, counted across **all five** search routes; further requests get 503 "searcher busy" (default **10**; locally that is up to ten CLI runs in one process, on Cloud Run each instance still serves one request and every further search gets its own instance). A photos request for a bike that already has photos never takes a slot |
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
scrape 17 s → 6 photos, **36 s** end to end; the repeat request answered from the DB in 0.5 s.

- `200` → `{"photos": [str], "bike_id": int | null, "saved": int}` — `photos` are the bike's photo URLs in
  `display_order`. **A bike that already has photo rows gets them back from the DB** (`saved: 0`) — no CLI run, no
  browser, no busy check. Otherwise the search runs and `photos` are the ≤ 8 URLs now stored (`saved == len(photos)`);
  should another search for the same bike (another process / Cloud Run instance) have stored photos first, those are
  returned with `saved: 0` and nothing is written. A search that finds nothing is a 200 with `photos: []`, `saved: 0`
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
- `500` `{"detail": "database read failed" | "database write failed"}`

**Flow**: (1) DB read: bike looked up by normalised brand/model, its `bike_detail_photos` rows ordered by
`display_order, id` — any rows → returned, **stop** →
(1b) once a slot is taken, the same read **again** — photos stored meanwhile by another process / instance → returned,
**stop** (no paid run) →
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
  `rating` 0–10 one decimal, `sources_used`). **A bike with a usable stored review** (`ref` non-empty **and**
  `sources_used >= 1`) **gets it back from the DB** (`saved: 0`) — no CLI run, no busy check, like
  `/v1/search/photos`, so repeated calls cannot burn subscription runs. Otherwise the search runs; a usable result
  replaces the bike's stored review and its sources → `saved: 1`, `review` = what was stored. Anything less writes and
  deletes **nothing** (not even a bike row) → `saved: 0`, `review` = what this run found (score 0 / `ref: []` /
  `sources_used: 0` — "no review"; `bike_id` then `null` for a bike the DB does not know)
- `400` (subscription limit) / `401` / `422` exactly as for `/v1/search/olx`
- `502` `{"detail": "claude CLI failed: exit 1" | …}` when the CLI run fails (the backend's old finder swallowed a
  missing JSON into the fallback review; here the CLI either returns the schema-validated object or fails)
- `503` `{"detail": "searcher busy"}` — the `SEARCHER_MAX_CONCURRENT` slots (default 10) are **shared** with the
  other four routes (nothing queues); never for a bike whose review is already stored
- `500` `{"detail": "database read failed" | "database write failed"}`

**Flow**: (1) DB read: bike looked up by normalised brand/model, its `bike_review` + `bike_review_source` rows
(`display_order, id`) — a usable review → returned, **stop** → (1b) once a slot is taken, the same read **again** — a
review stored meanwhile by another request / instance → returned, **stop** (no paid run) →
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
