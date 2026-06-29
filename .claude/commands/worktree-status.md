# Worktree Status

Show all active git worktrees for this repository, their branches, and whether their backend
and frontend servers are currently running.

---

## Steps to execute

### 1 — List all worktrees

```bash
git worktree list
```

This shows each worktree path, its HEAD commit, and branch name.

### 2 — Check running servers

For each port from the table below, check if something is listening:

```bash
netstat -ano 2>/dev/null | grep -E "0\.0\.0\.0:800[0-9]|127\.0\.0\.1:800[0-9]" | grep -i LISTENING
netstat -ano 2>/dev/null | grep -E "0\.0\.0\.0:517[0-9]|127\.0\.0\.1:517[0-9]" | grep -i LISTENING
```

Port convention:

| Worktree | Backend port | Frontend port |
|----------|-------------|---------------|
| `biker\` (main) | 8000 | 5173 |
| first worktree | 8001 | 5174 |
| second worktree | 8002 | 5175 |

### 3 — Read the app-runner state file if it exists

```bash
cat "C:/Users/kamil_wolny/Projects/biker/.claude-flow/data/app-runner-state.json" 2>/dev/null
```

If it exists, include the status from there for any worktree the app-runner agent is managing.

### 4 — Format and print the result

Print a table like this:

```
Git Worktrees — biker

  PATH                                              BRANCH              BACKEND   FRONTEND
  C:\Users\kamil_wolny\Projects\biker               main                8000 ✓    5173 ✓
  C:\Users\kamil_wolny\Projects\biker-wt\feature-x  feature/x           8001 ✗    5174 ✗

  ✓ = port is listening   ✗ = not running

Useful commands:
  /new-worktree <branch>   — create a new worktree
  git worktree remove <path>  — remove a worktree when done
```

If no extra worktrees exist (only main), say so clearly and remind the user how to create one.
