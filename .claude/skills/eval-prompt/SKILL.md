---
name: eval-prompt
description: Evaluate any prompt file against test inputs via the claude CLI (no API key required)
usage: Use when testing or iterating on prompt files to see how they respond to different inputs
argument-hint: "<prompt-file> \"<input>\" [\"<input>\" ...]"
---

# Evaluate Prompt

Evaluate a prompt file against one or more test inputs, using the project's no-API-key prompt-eval runner.

## What this skill does

Tests prompt files interactively by:
1. Loading a prompt from `backend/app/prompts/` as the system prompt
2. Sending test inputs (user messages) to Claude Haiku via the `claude` CLI
3. Extracting and displaying responses, including any numeric scores

No ANTHROPIC_API_KEY required — uses subscription OAuth via the `claude` CLI.

## Usage

Provide the prompt file path and one or more test inputs:

```
/eval-prompt app/prompts/road.md "Looking for a gravel bike"
/eval-prompt app/prompts/mountain.md "MTB for beginners" "Technical downhill"
/eval-prompt app/prompts/road.md "Road bike under $1500" --model sonnet
```

Arguments:
- First token = path to the prompt file to evaluate (relative to `backend/`)
  - Example: `app/prompts/road.md`
- Remaining quoted tokens = test inputs (user messages) to score
- Optional flags: `--model sonnet` to override the model (default: Haiku 4.5)

## Steps to execute

### 1 — Handle missing arguments

If no arguments were given, list the available prompt files and ask which prompt + inputs to run:

```bash
Glob "app/prompts/*.md"
```

Ask the user to provide the prompt file and test inputs.

### 2 — Run the evaluator

From the `backend/` directory, run the prompt evaluation runner with the user's arguments:

```powershell
cd C:\Users\kamil_wolny\Projects\biker\backend
.venv\Scripts\python.exe scripts/eval_prompt.py $ARGUMENTS
```

The runner shells out to the `claude` CLI (subscription OAuth, Haiku 4.5 by default).

### 3 — Present results

Display the results as a compact table:
- Input (test query)
- Extracted score (if the prompt is a scorer) or "n/a" if no numeric rating found
- One-line gist of each response

Call out anything surprising:
- A score that contradicts the input expectations
- A `<CLI call failed>` error
- An `n/a` score meaning no numeric rating was found

## Notes

- This runs an **ad-hoc** prompt against ad-hoc inputs.
- For the fixed directional category-scoring eval (11 queries × 11 categories), use instead:
  ```bash
  pytest scripts/test_scoring.py -m llm -s
  ```
- If the `claude` CLI is not on PATH, the runner exits with a clear error — install it and run `claude` once to log in.
- You can override the model with `--model sonnet` in the arguments.
