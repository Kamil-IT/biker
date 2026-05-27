# Feature workflow

Follow this workflow for every new backend feature in this project.

## 1 — Implement

**Backend**
- Add a new module in `app/` with an async entry-point function
- Add the response model to `app/schemas.py`
- Wire it into `app/main.py` — run it in parallel with existing calls via `asyncio.gather` where possible
- If the module calls the Anthropic API, wrap it with the SQLite cache from `app/cache.py` (see CLAUDE.md for the exact pattern)

**Frontend**
- Add new types to `src/types.ts`
- Add state + fetch call in `App.tsx`
- Render in the relevant component (usually `BikeDetailsView.tsx`)

## 2 — Test with Ruflo agents

Ruflo is configured with `maxAgents: 20` — you can start as many parallel agents as you need.

Use the persistent Ruflo terminal to start the backend and run all checks:

```
mcp__ruflo__terminal_create(name="biker-server")
mcp__ruflo__terminal_execute: cd /d C:\...\backend && .venv\Scripts\activate && start "biker-backend" cmd /k "uvicorn app.main:app --reload --port 8000"
```

Then in the same or a new terminal session run the smoke test:

```
mcp__ruflo__terminal_execute: cd /d C:\...\backend && .venv\Scripts\python.exe scripts/test_details.py
```

**Required checks before shipping:**
1. Smoke test exits 0 — new field present, correct type, expected value
2. Cache hit — run the smoke test a second time, must complete in < 2 s, same JSON
3. Fallback — call the endpoint with `FakeBrand / NoSuchModel XYZ999`, must return HTTP 200 with empty/default value for the new field

## 3 — Screenshot proof

Use Playwright (already installed as `patchright`) to take a screenshot of the frontend after the feature loads. Save to `backend/scripts/ss_*.png`, read the file so the image is visible in the conversation, then delete the file.

Example: after saving `backend/scripts/ss_3_details_loaded.png`, read it with the Read tool and show it inline as proof.

## 4 — Ship

Ask the user: **"All checks passed. Do you want to ship this to main?"**

If yes, invoke `/ship-to-main`.
