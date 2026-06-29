import json
import logging
import re
import time
from pathlib import Path

from anthropic import AsyncAnthropic

from .schemas import EquipmentReviewResponse

logger = logging.getLogger("biker.equipment.review")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"

_FALLBACK = EquipmentReviewResponse(score=0, explanation="Review unavailable.", ref=[])
_FENCED_JSON = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _find_json_object(text: str) -> dict | None:
    """Extract the review JSON object from a text block that may also contain
    prose and/or a code fence. Tries fenced blocks first, then any balanced
    ``{...}`` span that parses and carries a ``score`` key."""
    # 1) fenced ```json { ... } ``` anywhere in the text
    for m in _FENCED_JSON.finditer(text):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "score" in obj:
            return obj

    # 2) first balanced {...} that parses and looks like a review
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        obj = json.loads(candidate)
                        if isinstance(obj, dict) and "score" in obj:
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        start = text.find("{", start + 1)
    return None


async def find_equipment_review(company: str, model: str) -> EquipmentReviewResponse:
    system_prompt = (PROMPTS_DIR / "equipment_review.md").read_text(encoding="utf-8")
    item = f"{company} {model}".strip()
    user_message = f"Find reviews for: {item}"

    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": user_message}],
    )
    elapsed = time.perf_counter() - t

    logger.info(
        "equipment review done | elapsed=%.2fs input_tokens=%d output_tokens=%d",
        elapsed,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    # web_search responses interleave tool blocks with one or more text blocks,
    # and the JSON may be fenced and preceded by commentary. Scan text blocks
    # last-first and take the first that yields a valid review object.
    texts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    if not texts:
        logger.error("no text block in equipment review response")
        return _FALLBACK

    data: dict | None = None
    for text in reversed(texts):
        data = _find_json_object(text)
        if data is not None:
            break

    if data is None:
        logger.error("no JSON review object found | last_text=%r", texts[-1][:300])
        return _FALLBACK

    try:
        return EquipmentReviewResponse(
            score=int(data.get("score", 0)),
            explanation=str(data.get("explanation", "")) or _FALLBACK.explanation,
            ref=[str(u) for u in data.get("ref", []) if u],
        )
    except Exception as exc:
        logger.error("failed to build EquipmentReviewResponse: %s | data=%r", exc, data)
        return _FALLBACK
