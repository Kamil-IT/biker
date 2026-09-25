# TODO-029 — Test plan: Docker image + docker compose

Scope: the full stack started with `docker compose up --build` (db + backend + frontend at http://localhost:8080),
Postgres loaded from `backend/cache.db` with `copy_sqlite_to_postgres.py --target …localhost:5433/biker`.
Only cache-backed data is used (cost guard). Out of scope: GCP (TODO-030), live Playwright scraping of new bikes.

## Traceability

| Requirement | Where implemented | Status |
|---|---|---|
| Backend image: Python 3.14 slim, Chromium, `$PORT`, non-root, no secrets | `backend/Dockerfile`, `backend/.dockerignore` | Implemented |
| `PLAYWRIGHT_HEADLESS` replaces hard-coded `headless=False` | `backend/app/browser_config.py` + 4 call sites (incl. `allegro_image_fetcher.py`, not listed in the task) | Implemented (+1 extra call site) |
| Frontend: node build → nginx, SPA fallback, `/v1` proxy, long timeout | `frontend/Dockerfile`, `frontend/nginx.conf` | Implemented |
| Compose: db (volume, healthcheck) + backend (`DATABASE_URL` → db, `env_file`) + frontend on 8080 | `docker-compose.yml` | Implemented; extra: db published on 5433, backend on 8000 |
| Loading existing data into compose Postgres | `copy_sqlite_to_postgres.py` shipped in image; run from host against 5433 | Implemented (docs pending) |
| Docs updated | README / backend / frontend / CLAUDE.md | Pending at test time |

## Test cases

| ID | Priority | Preconditions | Steps | Expected |
|---|---|---|---|---|
| TC-01 | High | stack up | GET http://localhost:8080/ | 200, app shell renders, search box visible |
| TC-02 | High | TC-01 | Type `trek madone sl`, submit | `/v1/bike/parse` 200 (cache), Filters panel shows brand/model |
| TC-03 | High | TC-02 | Submit again | `/v1/bike/search` 200 (cache hit), result card "Madone SL 6" |
| TC-04 | High | TC-03 | Click Madone SL 6 card | Details view: photos, overview, spec tree ("Specyfikacja"), expert review |
| TC-05 | High | TC-04 | Wait for offers | "Nowe" and "Używane" cards show ≥1 offer each (Allegro, Decathlon, OLX from cache) |
| TC-06 | Medium | any | Reload page on `/` and on an unknown path `/foo` | 200 index.html (SPA fallback), no nginx 404 |
| TC-07 | Medium | whole run | Collect console + network | No console errors, no `/v1` response ≥ 500 |
| TC-08 | High | stack | `docker compose down` → `up -d`, count `bike` rows | Same row count (named volume) |
| TC-09 | High | image built | inspect `/app`, env of `biker-backend` | No `.env`, `cache.db`, no `ANTHROPIC_API_KEY` |
| TC-10 | High | image built | run with `PORT=9090` | uvicorn listens on 9090 |
| TC-11 | High | image built | launch Chromium headless inside the image | Page renders, no display error |

Regression: local dev without Docker — `PLAYWRIGHT_HEADLESS` unset keeps `headless=False` (default in `browser_config.py`).

## Results — 2026-09-25 (round 3, final)

`10 passed · 1 failed (external) · round 3` — browser cases run with Playwright against http://localhost:8080.

| ID | Result | Evidence |
|---|---|---|
| TC-01 | Pass | home 200, search box visible |
| TC-02 | Pass | `/v1/bike/parse` 200 (cache), filters Marka=TREK, Model=MADONE SL |
| TC-03 | Pass | `/v1/bike/search` 200 (cache hit), Madone SL 6 + Madone SL 5 cards |
| TC-04 | Pass | 9 images, overview, review, spec tree (Kokpit…), no "Poproś o dane" buttons |
| TC-05 | Pass | Nowe: allegro.pl; Używane: olx.pl, decathlon.pl |
| TC-06 | Pass | `/` and `/foo/bar` → 200 index.html |
| TC-07 | **Fail (external, not TODO-029)** | `/v1/bike/ceneo` 500 — Ceneo for Madone SL 6 was not cached, so it called the Anthropic API, which answered `400 credit balance is too low`. The endpoint lets the upstream error bubble up as 500 (pre-existing behaviour, identical without Docker) |
| TC-08 | Pass | `bike` = 674 rows before and after `down`/`up` |
| TC-09 | Pass | `/app` holds only `app`, `scripts`, `requirements.txt`; no `ANTHROPIC_API_KEY`/`DATABASE_URL` in image env |
| TC-10 | Pass | `PORT=9090` → `Uvicorn running on http://0.0.0.0:9090` |
| TC-11 | Pass | headless Chromium (patchright) renders a page inside the image |

Round 1–2 failures were wrong test locators ("Specyfikacja" is only the empty-state title; section headings are CSS-uppercased) — fixed in the script, not the app.
