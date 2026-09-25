# TODO-030 — Test plan: deploy to GCP (Cloud Run + Cloud SQL), step 1 "minimal deploy with UI"

Scope of this round (agreed 2026-09-25): backend + frontend as two Cloud Run services in `europe-central2`, data from
Cloud SQL `biker-pg`, secrets in Secret Manager, `scripts/deploy.ps1`. Rate limit, budget alerts, `docs/DEPLOYMENT.md`
and Firebase Hosting are step 2 / out of scope. The Anthropic credit is exhausted, so **only the cache happy path**
is testable: every input below is already cached in the GCP database (cost guard) and no AI call is expected.

Two rounds with the same cases: **local** (docker compose at http://localhost:8080, the same two images, backend →
`cloudsql-proxy` sidecar → Cloud SQL) before the deploy, then **public** (the Cloud Run frontend URL) after it.

## Traceability

| Requirement | Where implemented | Status |
|---|---|---|
| Backend talks to Cloud SQL, not a local DB | `docker-compose.yml` (`cloudsql-proxy` sidecar, `DATABASE_URL` → proxy, `PGPASSFILE`), `backend/.env.example` | Implemented |
| Backend image runs on Cloud Run (`$PORT`, headless Chromium, no secrets) | `backend/Dockerfile`, `backend/.dockerignore` (TODO-029) | Implemented |
| Frontend image proxies `/v1` to a configurable backend (compose: `backend:8000`, Cloud Run: https URL) | `frontend/nginx.conf.template`, `frontend/Dockerfile` (`BACKEND_URL`, `PORT`, `NGINX_ENVSUBST_FILTER`) | Implemented |
| One-command redeploy of both services | `scripts/deploy.ps1` | Implemented; IAM (public access) deliberately outside the script |
| Secrets only in Secret Manager (`anthropic-api-key`, `db-password` → `ANTHROPIC_API_KEY`, `PGPASSWORD`) | `scripts/deploy.ps1` `--set-secrets`; secrets created by hand (auto mode blocks secret writes) | Implemented |
| Cached data served with no AI call | backend cascade (TODO-024) — unchanged | Regression only |
| Rate limit 429, budget alerts, `docs/DEPLOYMENT.md`, Firebase Hosting | — | Step 2 (not in this round) |

## Test cases

Script: session scratchpad `qa030.py <base_url> <label>` (Playwright, Chromium headless, screenshots in `qa-030/<label>/`).

| ID | Priority | Steps | Expected |
|---|---|---|---|
| TC-01 | High | GET `/` | 200, search box `#bike-search` visible |
| TC-02 | High | Type `trek madone sl`, submit | `/v1/bike/parse` 200 (cache), filters show brand TREK, model MADONE SL |
| TC-03 | High | Submit again | `/v1/bike/search` 200 (cache), result cards incl. Trek Madone SL 6 |
| TC-04 | High | Click Madone SL 6 | `/v1/bike/details` 200: ≥1 photo, overview text, ≥1 spec category, `/v1/bike/review` 200; no "Poproś o dane" button |
| TC-05 | High | Wait for offers | `/v1/bike/offer`, `/v1/bike/decathlon`, `/v1/bike/used` 200; ≥1 allegro.pl link, ≥1 olx.pl/decathlon.pl link. `/v1/bike/ceneo` is **not cached** for this bike → 500 on the exhausted credit (known, external) |
| TC-06 | High | New search, Filtry → Marka `Trek`, submit | `/v1/bike/search` 200 from the DB-first step, ≥1 Trek bike, **no** `/v1/bike/parse` call |
| TC-07 | Medium | GET `/v1/bike/search-cache?brand=Trek`, GET `/v1/bike/details-cache?company=Canyon&model=Grizl CF 7 ESC` | both 200 with data (cache-only endpoints) |
| TC-08 | Medium | GET `/foo/bar` | 200 `index.html` (SPA fallback through nginx) |
| TC-09 | Medium | Whole run | no console errors and no `/v1` ≥ 400 other than the known Ceneo miss |
| TC-10 | High | Backend log at startup | `cache loaded \| db=postgresql+psycopg://biker@…` names the Cloud SQL target (proxy locally, `/cloudsql/` socket on Cloud Run) |

## Results — local round (2026-09-25, compose → cloudsql-proxy → Cloud SQL)

`9 passed · 0 failed` (TC-01–TC-09 via Playwright), TC-10 pass by log inspection.

| ID | Result | Evidence |
|---|---|---|
| TC-01 | Pass | 200, search box visible |
| TC-02 | Pass | parse 200, Marka=TREK, Model=MADONE SL |
| TC-03 | Pass | search 200 → Madone SL 6, SL 5, SL 7 |
| TC-04 | Pass | details 200: 8 photos (9 `<img>`), overview 598 chars, 8 spec categories, review 200, 0 request buttons |
| TC-05 | Pass | offer/decathlon/used 200; links: allegro 1, decathlon 1, olx 5; ceneo 500 = known external (`credit balance is too low`) |
| TC-06 | Pass | search 200, 5 Trek bikes, parse not called |
| TC-07 | Pass | search-cache 200 (8 bikes), details-cache 200 (6 categories) |
| TC-08 | Pass | `/foo/bar` → 200 index.html |
| TC-09 | Pass | no console errors besides the browser logging the known ceneo 500 |
| TC-10 | Pass | `cache loaded \| db=postgresql+psycopg://biker@cloudsql-proxy:5432/biker rows=266` |

Note: the first local run flagged TC-09 because the browser logs the known Ceneo 500 as a console error; the case now
counts that single, already-listed failure as known. No app code changed.

## Results — public round (2026-09-26, https://biker-frontend-919806073640.europe-central2.run.app, no token)

Deployed with `scripts/deploy.ps1` (image tag `7ac12ef-dirty`): `biker-backend-00001-fht`, `biker-frontend-00001-rr9`.
Before the `allUsers` binding both services answered 403 without a token and 200 with one; `/v1` through nginx reached
the backend's IAM layer (401, not 404), which proves DNS, SNI and the `Host` header.

`9 passed · 0 failed` — identical evidence to the local round (same cached inputs), plus:

| ID | Result | Evidence |
|---|---|---|
| TC-01–TC-09 | Pass | same values as locally: parse/search/details/review/offer/decathlon/used 200, ceneo 500 = known external, 5 Trek bikes from the DB step, cache endpoints 200, SPA fallback 200, no unexpected console/network errors |
| TC-10 | Pass | Cloud Run log: `cache loaded \| db=postgresql+psycopg://biker@/biker?host=%2Fcloudsql%2Fbiker-engine-prod%3Aeurope-central2%3Abiker-pg rows=266` |
| Latency (warm) | info | cache endpoints through nginx ≈ 0.15 s; `/docs` on the backend ≈ 0.4 s |

Ready for the step-2 work (rate limit, budget alerts, `docs/DEPLOYMENT.md`) in the same PR; the task moves to
`backlog/done/` once that PR merges.
