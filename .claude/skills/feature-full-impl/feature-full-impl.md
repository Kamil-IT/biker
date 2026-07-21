---
name: feature-full-impl
description: Complete workflow for implementing a backend feature end-to-end with testing and PR
usage: Use when implementing a new feature to follow the standard workflow from code to PR
---

# Feature Implementation Workflow

Follow this workflow for every new backend feature in this project.

## What this skill does

Guides you through a complete feature implementation cycle:
1. Code implementation (backend + frontend)
2. Testing with smoke tests
3. Screenshot verification
4. PR creation with evidence
5. Ship to main

## Overview

The workflow ensures:
- Backend changes are properly cached and tested
- Frontend integration works end-to-end
- Screenshots document the feature
- PR is created with proper formatting
- All smoke tests pass before shipping

## Steps

### 1 — Implement

**Backend**
- Add a new module in `app/` with an async entry-point function
- Add the response model to `app/schemas.py`
- Wire it into `app/main.py` — run it in parallel with existing calls via `asyncio.gather` where possible
- If the module calls the Anthropic API, wrap it with the SQLite cache from `app/cache.py` (see CLAUDE.md for the exact pattern)

**Frontend**
- Add new types to `src/types.ts`
- Add state + fetch call in `App.tsx`
- Render in the relevant component (usually `BikeDetailsView.tsx`)

### 2 — Test with smoke tests

**Before running the test dedicated to your change, run the existing smoke tests first** — this catches regressions in other endpoints before you focus on the new one.

Start the backend server (if not already running):
```bash
cd backend
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Run all existing smoke tests against the running server and confirm they all exit 0:

```bash
cd backend
.venv\Scripts\python.exe scripts/test_search.py
.venv\Scripts\python.exe scripts/test_review.py
.venv\Scripts\python.exe scripts/test_offer.py
.venv\Scripts\python.exe scripts/test_details.py
```

Then run the smoke test for your change. If it doesn't exist yet, create it in `backend/scripts/test_<feature>.py`.

**Required checks before shipping:**
1. Smoke test exits 0 — new field present, correct type, expected value
2. Cache hit — run the smoke test a second time, must complete in < 2 s, same JSON
3. Fallback — call the endpoint with `FakeBrand / NoSuchModel XYZ999`, must return HTTP 200 with empty/default value for the new field

### 3 — Screenshot proof

Use Playwright (already installed as `patchright`) to take screenshots of the frontend. Save to `backend/scripts/ss_*.png`.

Example:
```python
from patchright.async_api import async_playwright
import asyncio

async def shoot():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        await page.goto("http://localhost:5174", wait_until="domcontentloaded")
        await page.wait_for_selector("#bike-search", timeout=12000)
        await page.screenshot(path="scripts/ss_1_default.png")
        # ... more states ...
        await browser.close()

asyncio.run(shoot())
```

After taking screenshots, read and display them inline in the conversation, then **keep them** — they get committed to the repo on the feature branch and embedded in the PR via raw blob URLs.

### 4 — Create PR with screenshots

Screenshots are committed to the repo on the feature branch and embedded in the PR body via raw blob URLs. The flow:

```bash
REPO="Kamil-IT/biker"
SLUG=<slug>   # the feature branch suffix, e.g. bike-search-filters

# 1. Create branch, commit code AND screenshots, push
git checkout -b feature/${SLUG}
git add backend/app/... frontend/src/... CLAUDE.md backend/README.md
git add backend/scripts/ss_*.png
git commit -m "Short description of the feature"
git push -u origin feature/${SLUG}
```

Raw blob URL pattern for the committed images:
```
https://github.com/${REPO}/blob/feature/${SLUG}/backend/scripts/ss_<n>_<name>.png?raw=true
```

Create the PR with blob-hosted images embedded:
```bash
gh pr create \
  --title "Feature: <short description>" \
  --body "$(cat <<'EOF'
## Summary
- bullet 1
- bullet 2

## Screenshots

### Caption 1
![ss_1](https://github.com/Kamil-IT/biker/blob/feature/<slug>/backend/scripts/ss_1_<name>.png?raw=true)

### Caption 2
![ss_2](https://github.com/Kamil-IT/biker/blob/feature/<slug>/backend/scripts/ss_2_<name>.png?raw=true)

## Test plan
- [ ] smoke tests pass
- [ ] UI works end-to-end

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

GitHub renders `blob/<branch>/<path>?raw=true` URLs as inline images. The images live on the feature branch, so they stay visible in the PR history after merge.

After creating the PR, share the link with the user.

### 5 — Ship

When the user confirms, invoke `/ship-to-main` (or use the `ship-to-main` skill).
