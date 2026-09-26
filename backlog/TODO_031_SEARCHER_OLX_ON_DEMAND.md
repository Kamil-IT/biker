# TODO-031 — On-demand OLX searcher (separate serverless service, Claude Code CLI)

**Notion:** [18. Wyszukiwanie ofert na OLX endpoint tylko na prośbę użytkownika lub background process](https://app.notion.com/p/9cacc48f141644d283823ab17a04ae86?v=95008c68ebf24597847cd93a0502fff2&p=3e6bd10a98bf80d2a3eed30e44729e0a&pm=s)
— sub-tasks 18.1 (serverless service, runs only on request) · 18.2 (uses the Claude Code subscription token, not an
API key) · 18.3 (the user gets a real offer back when the search finishes) · 18.4 (the search really runs in that
process and its result is written to the database). Tick **Zrobione** there once the PR is merged.

## Goal
The OLX used-bike search (`web_search` + Playwright photos) eats API tokens on every uncached details view. Move
**all** of it out of the backend into a new top-level module `searcher/` — a small FastAPI app that runs only when
asked, calls Claude through the **Claude Code CLI** (`claude -p`, billed to the Max subscription via the OAuth token)
instead of the Anthropic SDK, and writes the offers it finds into PostgreSQL. The backend only reads the database; the
search is triggered by the user clicking **Poproś o dane** in the "Używane" offer card.

## Decisions (agreed 2026-09-25)
1. **Same logic, different transport.** The searcher does exactly what `/v1/bike/used` did: system prompt
   `bike_offer_olx.md` → JSON `{info, offers[]}` (≤ 5 listings) → Playwright scrapes ≤ 4 `apollo.olxcdn.com` photos per
   listing. No new verification of whether listings are active. `bike_used_finder.py`, `olx_image_fetcher.py` and the
   prompt **move** to `searcher/` (deleted from `backend/`).
2. **CLI, not SDK.** `claude -p "<user message>" --system-prompt <prompt> --output-format json --json-schema <schema>
   --tools WebSearch,WebFetch --allowedTools WebSearch,WebFetch --permission-prompts none --strict-mcp-config
   --setting-sources "" --no-session-persistence --model claude-haiku-4-5-20251001`, `ANTHROPIC_API_KEY` stripped from
   the child environment so the CLI authenticates with the subscription. Locally that is the logged-in CLI; on a
   server it is `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`). `structured_output` in the JSON result is the
   validated offers object — no prose parsing. Probe on 2026-09-25: Trek Marlin 5 → 5 real listings in 34 s.
3. **Persistence** in the existing, until now unused, `bike_offer` + `bike_offer_photos` tables (FK `bike.id`,
   `source = 'olx.pl'`, `city`, photos as rows ordered by `display_order`). The bike identity is looked up with the
   same Python-normalised brand/model compare the backend uses and **created if missing** (a direct `curl` call may
   name a bike that was never searched). A new search **replaces** that bike's OLX offers (`INSERT … ON CONFLICT
   (url) DO UPDATE`, stale rows of that bike/source deleted). No TTL on the read path for now — as long as rows exist
   the button never shows, so nothing re-triggers the search.
4. **Backend**: `POST /v1/bike/used` becomes a pure DB read (`repository.get_used_offers`) — no generic cache, no AI,
   `{offers, info}` shape unchanged, empty list when nothing is stored. New `POST /v1/bike/used/search` proxies to the
   searcher (`SEARCHER_URL` + `X-Searcher-Key`, long timeout), waits, returns the searcher's `{offers, info}`;
   **503** when the searcher is not configured/reachable, **502** when it fails. `POST /v1/bike/missing` is untouched.
5. **Frontend**: the existing **Poproś o dane** button in the "Używane" card records the click as before **and**
   calls `/v1/bike/used/search`; while that runs it shows "Szukam na OLX…"; the rows replace the button when offers
   arrive; no offers → "Nie znaleziono ofert"; a failed call makes the button clickable again. Nothing else changes —
   `/v1/bike/used` is still called automatically on opening the details view (fast, DB only).
6. **Auth**: one shared secret. The searcher requires header `X-Searcher-Key` equal to `SEARCHER_API_KEY` (401
   otherwise; fail closed when unset). `GET /health` is open. Simple enough for `curl` from the laptop.
7. **Order of work**: implement → run `/manual-tester` locally against the local Postgres (`biker-pg`) → ask the user
   for permission to deploy and which database the GCP searcher should write to → Cloud Run (scale-to-zero, image with
   Node + `claude` CLI + Playwright Chromium, secrets in Secret Manager). Nothing is deployed without that go-ahead.

## Scope
**`searcher/`** (new, standalone — own `requirements.txt`, `Dockerfile`, `.env.example`, `README.md`)
- `app/main.py` — FastAPI: `POST /v1/search/olx` `{company, model}` → `{offers, info, bike_id, saved}`; `GET /health`.
- `app/claude_cli.py` — subprocess wrapper around `claude -p` returning the structured JSON (or `None` on failure).
- `app/olx_finder.py` — the moved `find_used_bikes` (CLI call + photo scrape).
- `app/olx_image_fetcher.py`, `app/browser_config.py`, `app/prompts/bike_offer_olx.md` — moved/copied from backend.
- `app/models.py` + `app/repository.py` — SQLAlchemy over the shared `bike` / `bike_offer` / `bike_offer_photos`
  tables (identical DDL to `backend/app/models.py`), `save_used_offers(...)`.
- `scripts/test_searcher.py` — smoke test against a running searcher (auth 401, health, one real search).
- `Dockerfile` — `python:3.14-slim` + Node 24 + `@anthropic-ai/claude-code` + `patchright install chromium`, non-root.

**Backend**
- `app/main.py` — `/v1/bike/used` DB-only; new `/v1/bike/used/search`; drop the `bike_used_finder` import.
- `app/repository.py` — `get_used_offers(company, model)`.
- `app/searcher_client.py` — httpx call to the searcher.
- Delete `app/bike_used_finder.py`, `app/olx_image_fetcher.py`, `app/prompts/bike_offer_olx.md`.
- `.env.example` — `SEARCHER_URL`, `SEARCHER_API_KEY`.
- `scripts/test_search.py` — replace the old `/v1/bike/used` AI tests: DB read with a seeded fixture, unknown bike →
  200 empty, `/v1/bike/used/search` → 200 when the searcher is up (503 when not configured).
- `docker-compose.yml` — `searcher` service on 8100; backend gets `SEARCHER_URL=http://searcher:8100`.

**Frontend**
- `RequestDataButton.tsx` — optional `onRequested` + `pendingLabel` props.
- `BikeDetailsView.tsx` / `App.tsx` — wire the Used card's button to `POST /v1/bike/used/search`.

**Docs**: `CLAUDE.md`, `README.md`, `backend/README.md` (`## Endpoints` + Flow for both routes), `frontend/README.md`,
`searcher/README.md`, `docs/DEPLOYMENT.md` section for the searcher (written when deploying).

## Out of scope
- Verifying that listings are still active; any change to Allegro / Ceneo / Decathlon.
- A scheduler / background refresh — "background process" is satisfied by the searcher having its own endpoint that
  anything (cron, curl) can call.
- Polling, job queues, async status endpoints — the wait is synchronous.
- TTL / refresh of stored OLX offers.
- Deploying to GCP before the user says so, or choosing the GCP database for them.

## Acceptance criteria
- [x] `POST /v1/bike/used` makes **zero** Anthropic/CLI calls and returns the stored OLX offers (empty list if none).
- [x] Clicking **Poproś o dane** in the "Używane" card increments `bike_missing_request` **and** runs the searcher;
      the card then shows real OLX listings with photos, and `bike_offer` / `bike_offer_photos` hold them.
- [x] `curl -H "X-Searcher-Key: …" -d '{"company":"Trek","model":"Marlin 5"}' http://localhost:8100/v1/search/olx`
      returns offers; without the header → 401.
- [x] `backend/app/bike_used_finder.py` and `olx_image_fetcher.py` no longer exist in the backend.
- [x] Smoke tests in `backend/scripts/test_search.py` and `searcher/scripts/test_searcher.py` pass.
- [x] `/manual-tester` run locally is green.
- [x] Docs updated (see Scope). After the PR merges: tick **Zrobione** on the Notion task.
- [x] Deployed: Cloud Run `biker-searcher` (scale to zero, same Cloud SQL as the backend), backend + frontend redeployed with `SEARCHER_URL`; end-to-end verified on the public URLs (`docs/testing/TODO_031/TEST_PLAN.md` § Cloud Run). PR: https://github.com/Kamil-IT/biker/pull/97
