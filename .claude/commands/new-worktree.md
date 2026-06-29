# New Git Worktree

Create a new isolated working directory for a feature or fix branch, so you can work on it
simultaneously alongside `main` — without stashing or switching branches.

**Branch name from arguments:** `$ARGUMENTS`

---

## What this command does

Git worktrees let you check out multiple branches from the same repository at the same time.
Each worktree is a separate directory with its own file state, running server, and git status.
Switching "branches" means switching your terminal window — nothing to stash, nothing to lose.

```
C:\Users\kamil_wolny\Projects\
├── biker\            ← main branch (this repo, always here)
└── biker-wt\
    └── <branch>\     ← new worktree (created by this command)
```

---

## Steps to execute

### 1 — Validate arguments

If `$ARGUMENTS` is empty, stop and tell the user:
```
Usage: /new-worktree <branch-name>
Examples:
  /new-worktree feature/bike-map
  /new-worktree fix/search-crash
```

### 2 — Derive paths

From `$ARGUMENTS` (the branch name), compute:
- `BRANCH` = `$ARGUMENTS` trimmed (e.g. `feature/bike-map`)
- `SLUG` = `BRANCH` with `/` replaced by `-` (e.g. `feature-bike-map`)
- `WORKTREE_PATH` = `C:\Users\kamil_wolny\Projects\biker-wt\<SLUG>` (e.g. `C:\Users\kamil_wolny\Projects\biker-wt\feature-bike-map`)
- `MAIN_REPO` = `C:\Users\kamil_wolny\Projects\biker`

### 3 — Ensure the worktree container exists

```bash
mkdir -p "C:/Users/kamil_wolny/Projects/biker-wt"
```

### 4 — Create the worktree

First check if the branch already exists locally:
```bash
git branch --list "$BRANCH"
```

- If the branch **does not exist locally**: create it fresh
  ```bash
  git worktree add "C:/Users/kamil_wolny/Projects/biker-wt/$SLUG" -b "$BRANCH"
  ```
- If the branch **already exists locally**: check it out into the worktree
  ```bash
  git worktree add "C:/Users/kamil_wolny/Projects/biker-wt/$SLUG" "$BRANCH"
  ```

If the command fails because the worktree path already exists, tell the user and stop.

### 5 — Symlink heavy dependencies (save time and disk space)

Use PowerShell Junction points — these work on Windows without admin rights and are fully
transparent to Node and Python:

```powershell
# Symlink node_modules (saves ~500 MB and avoids npm install)
New-Item -ItemType Junction `
  -Path "C:\Users\kamil_wolny\Projects\biker-wt\$SLUG\frontend\node_modules" `
  -Target "C:\Users\kamil_wolny\Projects\biker\frontend\node_modules"

# Symlink .venv (saves ~200 MB and avoids pip install)
New-Item -ItemType Junction `
  -Path "C:\Users\kamil_wolny\Projects\biker-wt\$SLUG\backend\.venv" `
  -Target "C:\Users\kamil_wolny\Projects\biker\backend\.venv"
```

**Important note to include in the output:** These are shared — if your branch adds new npm
packages or pip packages, break the junction and install fresh:
```bash
# Break node_modules junction and reinstall:
Remove-Item ".\frontend\node_modules"   # removes junction only, not the target
cd frontend && npm install

# Break .venv junction and reinstall:
Remove-Item -Recurse ".\backend\.venv"
python -m venv backend\.venv && backend\.venv\Scripts\pip install -r backend\requirements.txt
```

### 6 — Copy .env (not a symlink — each worktree owns its own config)

```bash
cp "C:/Users/kamil_wolny/Projects/biker/backend/.env" \
   "C:/Users/kamil_wolny/Projects/biker-wt/$SLUG/backend/.env"
```

If `backend/.env` does not exist in the main repo, copy from `.env.example` and warn the user.

### 7 — Confirm and print summary

After all steps succeed, print this summary (fill in actual SLUG and port):

```
Worktree created successfully.

  Branch:   <BRANCH>
  Location: C:\Users\kamil_wolny\Projects\biker-wt\<SLUG>\

To start working:

  cd C:\Users\kamil_wolny\Projects\biker-wt\<SLUG>

Start the backend (port 8000 — same as main, run one at a time or pick a free port):
  cd backend
  .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000

Start the frontend:
  cd frontend
  npm run dev

If you need to run this worktree AND main simultaneously, use a different port:
  cd backend
  .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8001
  (then in frontend: npm run dev -- --port 5174)

When you are done with this branch:
  git worktree remove C:\Users\kamil_wolny\Projects\biker-wt\<SLUG>
  git branch -d <BRANCH>   # only if you no longer need the branch
```

---

## Port reference (for simultaneous running)

| Worktree | Backend | Frontend |
|----------|---------|----------|
| `biker\` (main) | 8000 | 5173 |
| first worktree | 8001 | 5174 |
| second worktree | 8002 | 5175 |

Note: if you change the backend port, the Vite proxy in `vite.config.ts` still points to `8000`.
For fully independent simultaneous runs, either edit `vite.config.ts` in the worktree or just
run both backends on 8000 (one at a time) and only switch between frontends.
