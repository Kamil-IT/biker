# TODO-029 — Dockerfile for the backend + docker-compose for the full stack

**Notion:** [15. Dockerfile + docker-compose (Postgres, backend, frontend)](https://app.notion.com/p/3e5bd10a98bf81438808f92623fac6d9) — tick **Zrobione** there once the PR is merged

## Goal
Package the app so it runs the same way locally and on GCP. The backend image is what Cloud Run runs (TODO-030).
docker-compose runs Postgres + backend + frontend on one machine for development and for testing the image.

Depends on TODO-028 (Postgres via `DATABASE_URL`).

## Decisions (agreed 2026-09-24)
1. **Backend image** is production-ready: Python 3.14 slim, Playwright Chromium installed in the image, runs `uvicorn` on
   `$PORT` (Cloud Run sets it; default 8000).
2. **Playwright headless is configurable**: new env var `PLAYWRIGHT_HEADLESS` (default `true` in the image, `false`
   allowed for local debugging). It replaces the hard-coded `headless=False` in `olx_image_fetcher.py`,
   `bike_photos_finder.py` and `equipment_photos_finder.py`. A server has no display.
3. **Frontend in compose** is served by nginx from `npm run build` output, with `/v1/*` proxied to the backend — the same
   routing Vite does in dev. On GCP the frontend goes to Firebase Hosting instead (TODO-030), so this image is for local
   use only.
4. **Secrets** never go into images: `ANTHROPIC_API_KEY` comes from `backend/.env` (compose) or Secret Manager (GCP).

## Scope
- `backend/Dockerfile` (+ `backend/.dockerignore`: `.venv`, `cache.db`, `.env`, `__pycache__`, `scripts/` test output).
  Use `playwright install --with-deps chromium`. Run as a non-root user.
- `frontend/Dockerfile`: multi-stage — node build → nginx; `frontend/nginx.conf` with SPA fallback and the `/v1` proxy
  (long `proxy_read_timeout`, `/v1/bike/details` takes minutes).
- `docker-compose.yml` in the repo root: `db` (`postgres:17`, named volume, healthcheck), `backend` (depends on a healthy
  `db`, `DATABASE_URL` pointing at `db`, `env_file: backend/.env`), `frontend` (port 8080 → nginx).
- `PLAYWRIGHT_HEADLESS` in the three Playwright call sites, plus `backend/.env.example`.
- How to load existing data into the compose Postgres with `copy_sqlite_to_postgres.py` (TODO-028).

**Docs**: `README.md` (a "Run with Docker" section), `backend/README.md`, `frontend/README.md`, `CLAUDE.md`
(setup + Playwright rows that say `headless=False`).

## Out of scope
- Anything on GCP (TODO-030)
- CI building images
- Elasticsearch service in compose (add later)

## Acceptance criteria
- [ ] `docker compose up --build` starts all three services; the app works at http://localhost:8080 (search, details
      with photos, review, offers, used bikes).
- [ ] Playwright photo scraping works inside the container in headless mode.
- [ ] Data survives `docker compose down` / `up` (named volume).
- [ ] The backend image has no `.env`, `cache.db` or API key baked in (`docker history` / inspect).
- [ ] The backend honours `$PORT`.
- [ ] Without Docker, local dev (`uvicorn` + `npm run dev`) still works as before.
- [ ] Docs updated (see Scope).
- [ ] After the PR is merged to `main`: tick **Zrobione** on the Notion task [15. Dockerfile + docker-compose (Postgres, backend, frontend)](https://app.notion.com/p/3e5bd10a98bf81438808f92623fac6d9).
