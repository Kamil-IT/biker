"""Reusable prompt evaluator — run ANY prompt file against one or more inputs.

The prompt file is used as the *system prompt*; each input is sent as the user
message. It calls the `claude` CLI (subscription OAuth), so it needs NO
ANTHROPIC_API_KEY. For each input it prints the model's reply and, when the reply
contains a numeric rating (JSON `score`, `score: N`, or `N/10`), the extracted
0-10 value.

Usage (run from backend/):
    python scripts/eval_prompt.py app/prompts/road.md "fast carbon bike for tarmac racing"
    python scripts/eval_prompt.py app/prompts/road.md "input one" "input two"
    python scripts/eval_prompt.py app/prompts/road.md --dataset inputs.txt   # 1 input/line
    python scripts/eval_prompt.py app/prompts/road.md --model sonnet "input"
    type inputs.txt | python scripts/eval_prompt.py app/prompts/road.md      # inputs on stdin

This is the generic sibling of `test_scoring.py`: that suite runs the fixed
directional category eval; this script runs an ad-hoc prompt against ad-hoc inputs.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
CLI_TIMEOUT = 180

_CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    m = _CODE_FENCE.match(text.strip())
    return m.group(1).strip() if m else text.strip()


def _parse_score(text: str) -> int | None:
    """Extract a 0-10 score: JSON object -> `score: N` -> `N/10`. None if absent."""
    cleaned = _strip_code_fence(text)
    for candidate in (cleaned, _first_json_object(cleaned)):
        if candidate:
            try:
                value = int(json.loads(candidate)["score"])
                return value if 0 <= value <= 10 else None
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                pass
    for pattern in (r'"?score"?\s*[:=]\s*(\d{1,2})', r"(\d{1,2})\s*/\s*10"):
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            value = int(m.group(1))
            if 0 <= value <= 10:
                return value
    return None


def _first_json_object(text: str) -> str | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else None


def run_prompt(query: str, system_prompt: str, model: str, claude: str) -> tuple[str | None, int | None]:
    """Return (raw_reply, parsed_score) for one input, or (None, None) on failure."""
    # Drop ANTHROPIC_API_KEY so the CLI uses subscription OAuth, not a stray key.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    proc = subprocess.run(
        [
            claude, "-p", query,
            "--system-prompt", system_prompt,
            "--tools", "",
            "--exclude-dynamic-system-prompt-sections",
            "--model", model,
            "--output-format", "json",
        ],
        stdin=subprocess.DEVNULL, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=CLI_TIMEOUT,
    )
    if proc.returncode != 0:
        return None, None
    try:
        result = str(json.loads(proc.stdout).get("result", ""))
    except json.JSONDecodeError:
        return None, None
    return result, _parse_score(result)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate a prompt file against inputs via the claude CLI (no API key).")
    parser.add_argument("prompt_file", help="path to the prompt file used as the system prompt")
    parser.add_argument("inputs", nargs="*", help="one or more user inputs to send")
    parser.add_argument("--dataset", help="file with one input per line (alternative to positional inputs)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"model alias or id (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    claude = shutil.which("claude")
    if claude is None:
        print("ERROR: `claude` CLI not found on PATH. Install it and run `claude` once to log in.", file=sys.stderr)
        return 2

    prompt_path = Path(args.prompt_file)
    if not prompt_path.is_file():
        print(f"ERROR: prompt file not found: {prompt_path}", file=sys.stderr)
        return 2
    system_prompt = prompt_path.read_text(encoding="utf-8")

    inputs = list(args.inputs)
    if args.dataset:
        inputs += [ln.strip() for ln in Path(args.dataset).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not inputs and not sys.stdin.isatty():
        inputs += [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
    if not inputs:
        print("ERROR: no inputs. Pass them as arguments, via --dataset, or on stdin.", file=sys.stderr)
        return 2

    print(f"Prompt:  {prompt_path}")
    print(f"Model:   {args.model}")
    print(f"Inputs:  {len(inputs)}\n")
    for i, query in enumerate(inputs, 1):
        raw, score = run_prompt(query, system_prompt, args.model, claude)
        score_str = "n/a" if score is None else str(score)
        print(f"[{i}] input: {query}")
        print(f"    score: {score_str}")
        if raw is None:
            print("    reply: <CLI call failed>")
        else:
            reply = " ".join(raw.split())
            print(f"    reply: {reply[:300]}{'...' if len(reply) > 300 else ''}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
