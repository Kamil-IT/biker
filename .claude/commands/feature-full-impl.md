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

Use Playwright (already installed as `patchright`) to take a screenshot of the frontend after the feature loads. Save to `backend/scripts/ss_*.png` and read the file so the image is visible in the conversation.

**Do NOT delete the screenshots.** Leave all `backend/scripts/ss_*.png` files in place until `/ship-to-main` is triggered — the ship step cleans them up as part of the commit.

Example: after saving `backend/scripts/ss_3_details_loaded.png`, read it with the Read tool and show it inline as proof.

## 4 — Create PR with screenshots

Once the user approves, create a feature branch, commit all changes (including the `ss_*.png` screenshots), push, and open a PR whose description embeds the screenshots inline.

```bash
# 1. Create and switch to branch
git checkout -b feature/<slug>

# 2. Stage all changed files + screenshots
git add backend/app/... frontend/src/... CLAUDE.md backend/README.md \
        .claude/commands/feature-full-impl.md \
        backend/scripts/ss_*.png

# 3. Commit
git commit -m "Short description of the feature"

# 4. Push
git push -u origin feature/<slug>

# 5. Create PR — embed screenshots using raw GitHub URLs on the branch
BRANCH="feature/<slug>"
REPO="Kamil-IT/biker"   # adjust if different

gh pr create \
  --title "..." \
  --body "$(cat <<'EOF'
## Summary
- bullet 1
- bullet 2

## Screenshots

### <Caption for ss_1>
![ss_1](https://raw.githubusercontent.com/${REPO}/${BRANCH}/backend/scripts/ss_1_<name>.png)

### <Caption for ss_2>
![ss_2](https://raw.githubusercontent.com/${REPO}/${BRANCH}/backend/scripts/ss_2_<name>.png)

## Test plan
- [ ] smoke tests pass
- [ ] UI works end-to-end

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

GitHub renders the `raw.githubusercontent.com` URLs as inline images in the PR description. The screenshots live on the branch and are cleaned up when the PR is merged.

After creating the PR, share the link with the user.

## 5 — Ship

When the user confirms, invoke `/ship-to-main`.
