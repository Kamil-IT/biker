# TODO-030 — Deploy to GCP (Cloud Run + Cloud SQL + Firebase Hosting)

**Notion:** [16. Wdrożenie na GCP (Cloud Run + Cloud SQL + Firebase Hosting)](https://app.notion.com/p/3e5bd10a98bf81e3ac0ef20329cdf2d5) — tick **Zrobione** there once the PR is merged · parent task [8. Zdeployuj](https://app.notion.com/p/3e2bd10a98bf81a9adcff945838a8b91)

## Goal
Put biker on the public internet on GCP, paid from the Free Trial credits (1114 zł, expires 2026-12-24 — no charges
while the billing account is not upgraded). Deployment is a script run by hand from the developer machine.

Depends on TODO-028 (Postgres) and TODO-029 (backend image, headless Playwright).

## Already done (2026-09-24)
- `gcloud` SDK 586 installed, logged in as the project owner.
- Project `biker-engine-prod` (number 919806073640) created, set as the gcloud default, billing account
  `01BCBC-E85F03-9949DB` (Free Trial) linked.

## Decisions (agreed 2026-09-24)
1. **Stack**: Cloud Run (backend) + Cloud SQL for PostgreSQL (smallest shared-core instance) + Firebase Hosting
   (frontend), region `europe-central2` (Warsaw).
2. **Deploy by hand**: `scripts/deploy.ps1`. No CI and no Terraform for now.
3. **Public app + per-IP rate limit** on the endpoints that call Anthropic. No login.
4. **Data**: the local `cache.db` is copied into Cloud SQL once (`copy_sqlite_to_postgres.py`, TODO-028).
5. **Secrets** in Secret Manager: `ANTHROPIC_API_KEY`, DB password. Nothing secret in the repo or the image.

## Scope
**One-time setup (documented, run by the developer — auto mode blocks resource creation from Claude)**
- Enable APIs: Cloud Run, Cloud SQL Admin, Artifact Registry, Secret Manager, Cloud Build (optional), Firebase.
- Artifact Registry Docker repo in `europe-central2`.
- Cloud SQL Postgres 17 instance, database `biker`, user `biker`; automated backups on.
- Secrets `anthropic-api-key`, `db-password`; a dedicated service account for Cloud Run with only
  `secretmanager.secretAccessor` + `cloudsql.client`.
- Budget alerts on the billing account: 100 / 300 / 600 zł (email only).
- Anthropic Console: hard monthly spend limit (GCP credits do not cover Anthropic).

**`scripts/deploy.ps1`**
- Build + push the backend image, `gcloud run deploy` with: Cloud SQL connection (`--add-cloudsql-instances`,
  unix-socket `DATABASE_URL`), secrets as env vars, `PLAYWRIGHT_HEADLESS=true`, memory ≥ 2 GiB (Chromium),
  `--max-instances` low (cost cap, e.g. 2), `--min-instances 0`, request timeout long enough for `/v1/bike/details`.
- `npm run build` + `firebase deploy --only hosting`.
- Prints the public URLs at the end.

**Backend**
- Rate limiting per client IP on the AI endpoints (search, parse, details, review, offer, ceneo, decathlon, used,
  equipment/*). Read the client IP from `X-Forwarded-For` behind Cloud Run / Firebase. Return 429 with a clear message.
  Limits configurable by env var.
- CORS only if the frontend calls Cloud Run directly (see risk below).

**Frontend**
- `firebase.json` / `.firebaserc`: SPA fallback; `/v1/**` rewrite to the Cloud Run service (same origin, no CORS).
- Show the 429 message to the user.

**Docs**: new `docs/DEPLOYMENT.md` (one-time setup + deploy + rollback + cost notes, including the Free Trial end date),
`README.md`, `backend/README.md` (rate limit), `CLAUDE.md`.

## Risks to check first
- **Firebase Hosting → Cloud Run rewrites time out after 60 s.** `/v1/bike/details` (8 sequential web searches) can
  take longer. If it does: the frontend calls the Cloud Run URL directly for the slow endpoints (`VITE_API_BASE_URL` +
  CORS limited to the Hosting domain), or everything goes direct.
- **Cold starts** with a Chromium image (~1 GB+): measure; accept or set `--min-instances 1` (costs credits 24/7).
- **Free Trial end (2026-12-24)**: resources stop. Decide before then: upgrade, move Postgres to Neon, or Hetzner.

## Out of scope
- Custom domain (separate Notion task "Kup domenę i wprowadź ją")
- CI/CD, Terraform
- Analytics (Umami, separate task)
- Elasticsearch

## Acceptance criteria
- [ ] The app works on the public Firebase Hosting URL: search, details with photos, review, offers, used bikes.
- [ ] Data copied from `cache.db` is served (a known cached search returns with no AI call).
- [ ] Exceeding the rate limit returns 429 and the UI shows it.
- [ ] No secret in the repo, the image, or plain Cloud Run env vars (secrets referenced from Secret Manager).
- [ ] `scripts/deploy.ps1` redeploys both parts from a clean checkout.
- [ ] Budget alerts and the Anthropic spend limit are set.
- [ ] `docs/DEPLOYMENT.md` written; other docs updated.
- [ ] After the PR is merged to `main`: tick **Zrobione** on the Notion task [16. Wdrożenie na GCP (Cloud Run + Cloud SQL + Firebase Hosting)](https://app.notion.com/p/3e5bd10a98bf81e3ac0ef20329cdf2d5).
