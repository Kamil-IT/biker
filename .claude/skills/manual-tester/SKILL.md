---
name: manual-tester
description: Manual QA loop for a finished change — finds the change context (backlog task, branch, PR, diff), compares what was implemented against what the task asked for, builds an ISTQB test plan with qa-manual-istqb, executes it in a real browser with webapp-testing (Playwright), reports failures to the main conversation, and re-tests after fixes until everything passes. Use when asked to "manually test", "QA this change", "verify the task was implemented", or before moving a backlog task to done.
---

# Manual Tester

Acts as a human QA tester for one change: understands what was requested, checks what was built, plans tests, clicks through the real app, and loops fix → retest until green.

## Prerequisites

- Plugins enabled for this project: `test-automation-skills-agents@fugazi-test-automation` (provides `qa-manual-istqb`) and `example-skills@anthropic-agent-skills` (provides `webapp-testing`)
- Python with Playwright installed globally (`pip install playwright && playwright install chromium`)
- Backend on `:8000` and frontend on `:5173` (started in Step 5 if not running)

## Quick Start

```
/manual-tester                      # test the current uncommitted/branch change
/manual-tester TODO_ISSUE_006       # test a specific backlog task
/manual-tester #81                  # test a PR
```

---

## Step-by-Step

### Step 1 — Find the context of the change

Resolve the **task input** (what was requested) and the **change set** (what was built):

| Argument given | Task input | Change set |
|---|---|---|
| Backlog ID / file name | `backlog/**/*<ID>*.md` | commits/diff mentioning the ID, else current diff |
| PR number | `gh pr view <n>` body + linked backlog file | `gh pr diff <n>` |
| Nothing | backlog file matching the branch name or diff topic; ask the user if none fits | `git diff main...HEAD` + `git status` / `git diff` (uncommitted) |

Read the backlog task file in full (description, acceptance criteria, clarifications). If no written request exists, ask the user for one sentence of intent — do not invent requirements.

### Step 2 — Analyse what was changed

- List changed files; classify each as backend endpoint, finder/prompt, schema, frontend component, docs, data.
- For each changed area, note the **user-visible behaviour** it affects (which screen, which button, which API response).
- Skip noise (`cache.db`, pipeline scratch files, lockfiles) unless the task is about them.

### Step 3 — Compare request vs implementation

Build a traceability table (template in [resources/templates.md](resources/templates.md#traceability)):

`Requirement → Where implemented (file:line) → Status (Implemented / Partial / Missing / Extra)`

- **Missing / Partial** requirements become failed findings immediately (no browser needed).
- **Extra** behaviour not requested is flagged for the user, not silently accepted.

### Step 4 — Create the test plan

Invoke `Skill("test-automation-skills-agents:qa-manual-istqb")` with: the task input, the traceability table, and the changed user-visible behaviour. Ask it for:

- Test conditions derived from each requirement (equivalence partitions, boundary values, state transitions where relevant)
- Test cases with ID, preconditions, steps, test data, expected result, priority
- A short regression set for adjacent features the diff touches

Save the plan to `docs/testing/<TASK_ID>/TEST_PLAN.md` (use the branch name when there is no task ID).

### Step 5 — Execute the test cases

1. Check servers: `curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs` and `http://localhost:5173`. If down, spawn the `app-runner` agent, or use the webapp-testing `scripts/with_server.py` helper.
2. Invoke `Skill("example-skills:webapp-testing")` and write Python Playwright scripts in the session scratchpad (never in the repo) that execute each test case: navigate, wait for `networkidle`, act, assert, screenshot.
3. Capture evidence per case: screenshot path, console errors, failing network responses (status + URL).
4. Mark each case **Pass / Fail / Blocked** against its expected result.

**Cost guard:** the backend calls the Anthropic API on cache misses. Prefer inputs that are already cached (bikes in `cache.db`), and reuse the same query across cases. Tell the user before a run that will trigger many uncached searches.

### Step 6 — Report and loop until fixed

Post the report to the main conversation (template in [resources/templates.md](resources/templates.md#report)):

- Summary line: `N passed · M failed · K blocked · round R`
- One row per failure: case ID, what happened vs expected, severity, evidence, suspected cause as `file:line`

Then loop:

1. Fix the failures (or let the user fix them if they asked only for a report).
2. Re-run **the failed cases plus the regression set** — not only the failed case.
3. Post the updated report for the round.
4. Stop when every case passes. Also stop and ask the user when: the same case fails 3 rounds in a row, a fix would change the requirement itself, or 5 rounds have passed.

Never make a case pass by editing its expected result to match the bug. A wrong expectation is changed only with the user's agreement, and noted in the report.

When all pass, append the final results table to `docs/testing/<TASK_ID>/TEST_PLAN.md` and say the task is ready to move to `backlog/done/` once its PR merges (per CLAUDE.md, merged is the bar).

---

## Troubleshooting

- **Frontend loads but API calls fail** — backend not on `:8000`, or the Vite proxy is pointed elsewhere; check `frontend/vite.config.ts`.
- **Search hangs for a long time** — uncached query running the full AI pipeline; switch to a cached bike or raise the Playwright timeout to 120 s for that case.
- **`qa-manual-istqb` not found** — the plugin is disabled; run `claude plugin enable test-automation-skills-agents@fugazi-test-automation --scope project` and restart.
- **Photos pages open a visible Chrome window** — expected; the photo/OLX finders run Playwright with `headless=False`.

## Related

- `sparc-tester` — automated smoke tests in `backend/scripts/test_search.py`
- `verification-quality` — code-level verification scoring
