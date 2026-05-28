---
description: Evaluate any prompt file against test inputs via the claude CLI (no API key)
argument-hint: <prompt-file> "<input>" ["<input>" ...]
allowed-tools: Bash(*), Read, Glob
---

Evaluate a prompt file against one or more test inputs, reusing the project's
no-API-key prompt-eval runner.

Arguments: `$ARGUMENTS`
- First token = path to the prompt file to evaluate (used as the system prompt),
  e.g. `app/prompts/road.md`. Paths are relative to `backend/`.
- Remaining quoted tokens = test inputs (user messages) to score.

## Steps

1. If no arguments were given, list the available prompt files with
   `Glob app/prompts/*.md` (from `backend/`) and ask which prompt + inputs to run.
2. From the `backend/` directory, run the runner with the user's arguments:

   ```powershell
   cd C:\Users\kamil_wolny\Projects\biker\backend
   .venv\Scripts\python.exe scripts/eval_prompt.py $ARGUMENTS
   ```

   The runner shells out to the `claude` CLI (subscription OAuth, prod model
   Haiku 4.5 by default) — it needs **no ANTHROPIC_API_KEY**. Add `--model sonnet`
   (etc.) inside `$ARGUMENTS` to override the model.
3. Present the results as a compact table: input, extracted score (if the prompt
   is a scorer), and a one-line gist of each reply. Call out anything surprising
   (a score that contradicts the input, a `<CLI call failed>`, or an `n/a` score
   meaning no numeric rating was found).

## Notes
- This runs an **ad-hoc** prompt against ad-hoc inputs. For the fixed directional
  category-scoring eval (11 queries × 11 categories with top-N + MRR gates), use
  `pytest scripts/test_scoring.py -m llm -s` instead.
- If the `claude` CLI is not on PATH, the runner exits with a clear error — tell
  the user to install it and run `claude` once to log in.
