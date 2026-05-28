import json
import re
from typing import Optional, Union

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def _try_load(s: str) -> Optional[Union[dict, list]]:
    try:
        value = json.loads(s)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, (dict, list)) else None


def _balanced_candidates(text: str) -> list[str]:
    """Return every balanced top-level {...} / [...] substring, ignoring braces inside strings."""
    candidates: list[str] = []
    stack: list[str] = []
    start: Optional[int] = None
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            if not stack:
                start = i
            stack.append(ch)
        elif ch in "}]":
            if stack:
                stack.pop()
                if not stack and start is not None:
                    candidates.append(text[start : i + 1])
                    start = None
    return candidates


def extract_json(text: str) -> Optional[Union[dict, list]]:
    """Extract a JSON object/array from model output.

    Handles three shapes, in order of preference:
    1. ```json ... ``` (or plain ```) fenced blocks
    2. The whole response when it is already pure JSON
    3. A balanced {...}/[...] block embedded in prose — models often narrate
       their search, then emit the JSON last, so the last parseable block wins.
    """
    text = text.strip()
    if not text:
        return None

    for block in _FENCE_RE.finditer(text):
        parsed = _try_load(block.group(1).strip())
        if parsed is not None:
            return parsed

    parsed = _try_load(text)
    if parsed is not None:
        return parsed

    for block in reversed(_balanced_candidates(text)):
        parsed = _try_load(block)
        if parsed is not None:
            return parsed

    return None
