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

Use Playwright (already installed as `patchright`) to take screenshots of the frontend. Save to `backend/scripts/ss_*.png`, read the files to show them inline in the conversation, then **delete them** — they will be hosted on GitHub, not committed to the repo.

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

After reading/showing the images inline, delete the local files — they stay out of the repo.

## 4 — Create PR with screenshots

Screenshots are hosted on a GitHub release (not committed to the repo). The flow:

```bash
TOKEN=$(gh auth token)
REPO="Kamil-IT/biker"
PR_NUM=<number>   # fill in after creating the PR, or use a label like "pr-<slug>"

# 1. Create a published release to host the images (one release per PR)
RELEASE_ID=$(curl -s -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d "{\"tag_name\":\"screenshots-pr-${PR_NUM}\",\"name\":\"PR #${PR_NUM} screenshots\",\"draft\":false,\"body\":\"\"}" \
  "https://api.github.com/repos/${REPO}/releases" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")

# 2. Upload each screenshot as a release asset
upload_asset() {
  local file=$1; local name=$(basename "$file")
  curl -s -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: image/png" \
    --data-binary @"$file" \
    "https://uploads.github.com/repos/${REPO}/releases/${RELEASE_ID}/assets?name=${name}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['browser_download_url'])"
}

BASE="https://github.com/${REPO}/releases/download/screenshots-pr-${PR_NUM}"
# after uploading: BASE/ss_1_<name>.png, BASE/ss_2_<name>.png, etc.

# 3. Create branch, commit code (no screenshots), push
git checkout -b feature/<slug>
git add backend/app/... frontend/src/... CLAUDE.md backend/README.md .claude/commands/feature-full-impl.md
git commit -m "Short description of the feature"
git push -u origin feature/<slug>

# 4. Create PR with release-hosted images embedded
gh pr create \
  --title "..." \
  --body "$(cat <<'EOF'
## Summary
- bullet 1
- bullet 2

## Screenshots

### <Caption 1>
![ss_1](https://github.com/REPO/releases/download/screenshots-pr-NUM/ss_1_<name>.png)

### <Caption 2>
![ss_2](https://github.com/REPO/releases/download/screenshots-pr-NUM/ss_2_<name>.png)

## Test plan
- [ ] smoke tests pass
- [ ] UI works end-to-end

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

GitHub renders release asset URLs as inline images. The release persists so images stay visible in the PR history. Screenshots never touch the repo.

After creating the PR, share the link with the user.

## 5 — Ship

When the user confirms, invoke `/ship-to-main`.
