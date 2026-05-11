---
name: ship-to-main
description: >
  Automates the full end-of-session git workflow: create a branch, commit all
  uncommitted changes with a single-sentence message, push, open a PR whose
  description is a bullet list of features implemented, and auto-merge to main.
  Invoke this skill whenever the user says "ship", "commit and merge",
  "push to main", "create PR and merge", "commit my changes", "wrap up the
  session", "send this to main", "merge everything", or any phrasing that means
  'get my current work into main in one shot'. Always use this skill for
  end-of-session shipping — don't attempt the git workflow manually.
---

# Ship to Main

This skill turns a working session into a merged commit in one pass.
The goal is a clean, descriptive git history without making the user think
about branch names or commit messages — those come from the work itself.

## Step 1 — Check for changes

Run `git status`. If there is nothing to commit, tell the user and stop.

Also note which branch you're on. If already on a non-main feature branch,
commit there and skip creating a new branch (go straight to Step 3).

## Step 2 — Create a branch

Pick a branch name that is a short kebab-case slug of the work done,
prefixed by type:

- `feature/` — new capability added
- `fix/` — bug corrected
- `chore/` — tooling, docs, config, refactor with no behaviour change

Derive the name from what actually changed, not from a generic label.
Keep it under 50 characters.

```
feature/real-bike-search
fix/score-allocation-rounding
chore/update-docs-policy
```

Run: `git checkout -b <branch-name>`

## Step 3 — Stage files

Stage only the files that were created or modified during this Claude Code
session. The conversation history is the source of truth: look back through
the tools used (Write, Edit, Bash commands that created files) and collect
the exact set of paths that were touched. Stage those paths by name — never
use `git add .` or `git add -A`, because the repo may contain pre-existing
dirty files or unrelated work-in-progress that should not be included.

If a file appears in `git status` but was not touched in this session,
leave it unstaged and mention it to the user at the end.

Regardless of session history, never stage:
- `.env`, `*.key`, `*.pem`, `credentials.*`, `secrets.*`
- `node_modules/`, `__pycache__/`, `.venv/`, `dist/`, `build/`
- Any file the user explicitly says to leave out

## Step 4 — Craft the commit message

**Commit subject** — one sentence, imperative present tense, ≤ 72 characters,
no trailing period. It should complete the sentence "This commit will…"

Good: `Add real bike search with category filtering and parallel Claude calls`
Bad: `Added various changes to the bike search system and some other stuff`

**Body** — a bullet list of the features / changes implemented, one per line,
in the same order you'd explain them to a colleague. Group related items.
Close with the Co-Authored-By trailer.

Derive both from: `git diff --stat`, `git diff`, and the conversation context
(what did the user ask for, what was built, what was fixed).

Commit using a heredoc so multi-line messages work reliably:

```bash
git commit -m "$(cat <<'EOF'
<one-sentence subject>

- Feature or change 1
- Feature or change 2
- Feature or change 3

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

## Step 5 — Push

```bash
git push -u origin <branch-name>
```

## Step 6 — Create PR

Use `gh pr create`. The PR title is the same one-sentence subject from the
commit. The body is the feature bullet list, wrapped in a `## Summary` heading,
plus the Claude Code footer.

```bash
gh pr create --title "<subject>" --body "$(cat <<'EOF'
## Summary

- Feature or change 1
- Feature or change 2
- Feature or change 3

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

## Step 7 — Merge

```bash
gh pr merge --merge
```

If the merge is blocked (branch protection, required checks), report the
reason clearly and stop — don't force-push or bypass checks.

## Step 8 — Sync main

```bash
git checkout main && git pull
```

## Reporting back

After a successful merge, tell the user:
- The branch name
- The one-sentence commit message
- The PR URL
- That main is now up to date

Keep it to 3–4 lines. They don't need a recap of every command that ran.
