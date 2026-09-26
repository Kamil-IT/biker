# Test plan — TODO-031 On-demand OLX searcher

Branch `feature/031-searcher-olx` · task `backlog/TODO_031_SEARCHER_OLX_ON_DEMAND.md` · executed 2026-09-26.

## Scope

In scope: the on-demand OLX search path end to end — `searcher/` service (`POST /v1/search/olx`, `GET /health`), the
backend's DB-only `POST /v1/bike/used` and proxy `POST /v1/bike/used/search`, and the frontend's **Poproś o dane**
button in the "Używane" offer card (`RequestDataButton` with `onRequested`). Regression: the New offers card and the
other Request-data buttons, which share the component.

Out of scope (per task): listing-liveness verification, scheduler, TTL/refresh, Allegro/Ceneo/Decathlon, GCP deploy.

## Environment and constraints

- Local stack from this checkout: searcher `127.0.0.1:8100`, backend `127.0.0.1:8001`, frontend `localhost:5174`
  (ports 8000/8080 are held by another worktree's docker-compose stack connected to Cloud SQL — not touched).
- Database: local PostgreSQL 17 (`biker-pg`, `DATABASE_URL` in `backend/.env` and `searcher/.env`).
- Error/empty paths run on a second stack wired to a **fake searcher** (`127.0.0.1:8199` → backend `8002` → frontend
  `5175`), because the real CLI cannot be made to return "no offers" or fail on demand.
- **The Anthropic API key has no credits** during this run (`Your credit balance is too low`), so every uncached AI
  endpoint answers 500. All cases therefore use bikes that exist in `bike` and whose details/review/offers are already
  cached (Romet Wagant 3, Romet Aspre, Trek FX 3 Disc) or whose OLX rows already exist (Trek Marlin 5). This is also why
  the full `backend/scripts/test_search.py` cannot pass right now — its unrelated Ceneo/AI-fallback cases hit the API.

## Requirement traceability

| # | Requirement (task file) | Implemented in | Status |
|---|---|---|---|
| R1 | `POST /v1/bike/used` is a pure DB read, zero AI/CLI calls, `{offers, info}` unchanged | `backend/app/main.py` `bike_used`, `backend/app/offers_repository.py` `get_used_offers` | Implemented |
| R2 | New `POST /v1/bike/used/search` proxies to the searcher, waits, returns `{offers, info}`; 503 not configured/unreachable, 502 on failure | `backend/app/main.py` `bike_used_search`, `backend/app/searcher_client.py` | Implemented (+404 for an unknown bike, +503 busy — see X1) |
| R3 | `searcher/` runs exactly the old logic through `claude -p` and Playwright, writes `bike_offer`/`bike_offer_photos`, replace semantics, bike created if missing | `searcher/app/olx_finder.py`, `claude_cli.py`, `olx_image_fetcher.py`, `repository.py` | Implemented (replace only when ≥1 offer stored; a URL already under another bike is not re-parented — see X2) |
| R4 | Searcher auth: `X-Searcher-Key` shared secret, 401 otherwise, fail closed; `GET /health` open | `searcher/app/main.py` `require_api_key` | Implemented |
| R5 | Frontend: the Used card's Poproś o dane records the click **and** runs the search; "Szukam na OLX…" while running; rows replace the button; "Nie znaleziono ofert" on empty; clickable again on failure; `/v1/bike/used` still called automatically | `frontend/src/components/RequestDataButton.tsx`, `BikeDetailsView.tsx`, `App.tsx` `searchUsedBikes` | Implemented |
| R6 | `bike_used_finder.py`, `olx_image_fetcher.py`, prompt moved out of the backend | deleted from `backend/app`, present under `searcher/app` | Implemented |
| R7 | Smoke tests: `backend/scripts/test_search.py` (TC-30..32) and `searcher/scripts/test_searcher.py` | both files | Implemented — searcher suite ALL OK; TC-30/31/32 pass (live search 91 s, DB round-trip) |
| R8 | Docs: CLAUDE.md, README.md, backend/README.md, frontend/README.md, searcher/README.md | updated | Implemented |
| X1 | (not requested) 404 for a bike unknown to `bike`; 503 "busy" instead of queueing; single-flight per bike | `main.py`, `searcher_client.py`, `searcher/app/main.py` | Extra — review findings (anonymous callers could mint bike rows / stack paid runs) |
| X2 | (not requested) OLX CDN URLs now carry `:443` — regex fixed, one photo per file | `searcher/app/olx_image_fetcher.py` | Extra — without it every listing had 0 photos |
| X3 | (not requested) `bike_offer` `brand`/`model` come from the `bike` row, not the listing title | `offers_repository.py` | Extra — the table has no title column; visible as "Romet Wagant 3" on every row |

## Test cases

### TC-031-01 — Stored OLX offers are served from the DB
- **Requirement:** R1, R5 · **Priority:** High
- **Preconditions:** Trek Marlin 5 has 5 `olx.pl` rows with photos in `bike_offer` (written by the smoke run)
- **Steps:** open `/`, Filtry → Marka `Trek`, Model `Marlin 5` → Znajdź → click the result card → wait for the "Używane" card
- **Expected:** within ~1.5 s the Used card lists 5 rows (`olx.pl`, city, price, photo thumbnails); no Poproś o dane in it; exactly one `POST /v1/bike/used` → 200

### TC-031-02 — Empty Used card shows the button only after the 5 s grace
- **Requirement:** R5 · **Priority:** Medium
- **Preconditions:** Romet Wagant 3 has no `olx.pl` rows
- **Steps:** open its details as above; sample the Used card immediately, then wait
- **Expected:** no rows and no button right after render (skeleton); "Poproś o dane" appears within 15 s; `/v1/bike/used` → 200

### TC-031-03 — Click runs the search and the rows replace the button
- **Requirement:** R2, R3, R5 · **Priority:** High
- **Steps:** click Poproś o dane in the Used card; observe the label; wait ≤ 7 min
- **Expected:** button reads "Szukam na OLX…" with a spinner; `POST /v1/bike/missing` → 200 and `POST /v1/bike/used/search` → 200 once each; afterwards ≥ 1 OLX row with ≥ 1 photo in the card, button gone; no console errors

### TC-031-04 — A second bike's search while one runs is refused, button stays clickable
- **Requirement:** R2 (X1) · **Priority:** Medium
- **Steps:** page A: Trek FX 3 Disc → click; within seconds page B: Romet Aspre → click
- **Expected:** B's `/v1/bike/used/search` → 503 within ~6 s and its button reads "Poproś o dane" (enabled); A finishes with rows

### TC-031-05 — Search that finds nothing
- **Requirement:** R5 · **Priority:** Medium · fake-searcher stack
- **Steps:** Romet Wagant 3 → click
- **Expected:** `/v1/bike/used/search` → 200 `offers: []`; button reads "Nie znaleziono ofert", disabled; card still empty

### TC-031-06 — Searcher failure returns the button to clickable
- **Requirement:** R5 · **Priority:** High · fake-searcher stack
- **Steps:** Romet Aspre → click (fake answers 502) → click again
- **Expected:** `/v1/bike/used/search` → 502; button reads "Poproś o dane", enabled; a second click sends another request

### TC-031-07 — Regression: New card and plain Request-data buttons
- **Requirement:** regression · **Priority:** Medium
- **Steps:** on Romet Wagant 3 compare the New card before/after the Used search; click another section's Poproś o dane
- **Expected:** New card rows unchanged (cached Allegro/Ceneo/Decathlon); the other button turns into "Zgłoszono ✓"

### API-level cases (covered by the smoke suites, not repeated in the browser)
- `POST /v1/search/olx` without / with a wrong key → 401; empty company → 422; real search → 200 + rows in DB
  (`searcher/scripts/test_searcher.py`, ALL OK, 5 offers in 85 s).
- `POST /v1/bike/used/search` unknown bike → 404; live search → 200 and `/v1/bike/used` reads the same rows back;
  no generic-cache rows for either route (`test_search.py` TC-30/31/32, all OK).
- Backend proxy error mapping (401/502/malformed/timeout → 502/503) — verified by the backend agent against a fake
  searcher on 8199 during implementation.

## Results

Executed 2026-09-26 with headless Playwright (`python`, scripts in the session scratchpad — not committed).
Three rounds; every failure in rounds 1–2 was a defect of the test harness, not of the application, and each was fixed
in the script and re-run (details below). **Final: 7 passed · 0 failed · 0 blocked.**

| Case | Result | Round | Evidence / actual |
|---|---|---|---|
| TC-031-01 | Pass | 3 | Trek Marlin 5: Used card rendered 6 rows 7.4 s after the search click — 5 OLX rows with 4 photo thumbnails each (from `bike_offer` / `bike_offer_photos`) plus 1 cached Allegro used offer that the pooled card has always shown; no Request-data button; exactly one `POST /v1/bike/used` → 200 |
| TC-031-02 | Pass | 1, 2 | Romet Wagant 3: skeleton first (0 rows, 0 buttons), "Poproś o dane" after the grace; `/v1/bike/used` → 200 |
| TC-031-03 | Pass | 1, 2 | Click → "Szukam na OLX…" with spinner (`tc03_wagant3_searching.png`) → after 191–194 s 5 OLX rows with photos replaced the button (`tc03_wagant3_after_search.png`); `/v1/bike/missing` → 200, `/v1/bike/used/search` → 200, no console errors; DB: 5 `bike_offer` rows + 15 photos for bike 624 |
| TC-031-04 | Pass | 3 | Cannondale Topstone Carbon 4 search running; Romet Aspre clicked 5 s later → `/v1/bike/used/search` → 503 within 6 s, its button reads "Poproś o dane" and is enabled; the first search finished with 5 rows / 15 photos |
| TC-031-05 | Pass | 1 (fake stack) | Fake searcher `200 offers: []` → button "Nie znaleziono ofert", disabled; card empty; `/missing` and `/used/search` → 200 |
| TC-031-06 | Pass | 1 (fake stack) | Fake searcher 502 → button "Poproś o dane", enabled; second click sends a second request (`[502, 502]`); only console noise is the browser's own "Failed to load resource: 502" line |
| TC-031-07 | Pass | 2 | New card unchanged (3 cached rows before and after the Used search); the photos section's Poproś o dane → "Zgłoszono ✓", `/v1/bike/missing` → 200 |

Harness defects fixed between rounds (none of them application bugs): (1) the Used-card button locator matched the
photo-gallery `‹ ›` arrows once rows had photos → narrowed to `button[aria-live='polite']`; (2) TC-01 expected exactly
5 anchors, but the card pools every `is_new=false` source, so a cached Allegro used offer makes 6 → count OLX rows;
(3) TC-01 sampled the row count once during a re-render → wait for the first row; (4) the "other Request-data button"
locator keyed on the label, which changes to "Zgłoszono ✓" → keyed on the section eyebrow; (5) `time.sleep()` does not
pump Playwright's network events → `page.wait_for_timeout()`; (6) TC-04 first used Trek FX 3 Disc, whose cached Allegro
offer is `is_new=false`, so its Used card is never empty → Cannondale Topstone Carbon 4.

Side effects left in the local database (real, paid searches — kept on purpose): OLX rows for Trek Marlin 5, Romet
Wagant 3 and Cannondale Topstone Carbon 4; `bike_missing_request` counters for Romet Aspre / Romet Wagant 3.

## Cloud Run (2026-09-26, after PR #97 was opened)

`biker-searcher` deployed from image `searcher:f9f7c6f` (scale to zero, `--concurrency 1`, 900 s, same Cloud SQL);
backend `854b5e5` redeployed with `SEARCHER_URL` + the `searcher-api-key` secret, frontend redeployed. Checked on the public URLs:

| Check | Result |
|---|---|
| `GET /health` on the searcher (anonymous, after the `allUsers` binding) | 200 `{"status":"ok","claude_cli":"2.1.283 (Claude Code)","database":true}` |
| `POST /v1/search/olx` without `X-Searcher-Key` | 401 |
| backend `POST /v1/bike/used/search` for an unknown bike | 404 |
| backend `POST /v1/bike/used` Romet Aspre before any search | 200 `{"offers":[],"info":""}` |
| backend `POST /v1/bike/used/search` Romet Aspre | 200, 5 real OLX listings with 1–4 photos each, 78 s (CLI run on the subscription, Playwright on Cloud Run) |
| backend `POST /v1/bike/used` Romet Aspre afterwards | the same 5 rows from Cloud SQL |
| direct search on the searcher (Trek Marlin 5, identity token) | 200, 5 listings × 4 photos, 89 s; rows visible through the public backend |

The task is ready to move to `backlog/done/` once its PR merges (merged is the bar).
