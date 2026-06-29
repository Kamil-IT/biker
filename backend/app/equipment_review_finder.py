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
_CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)
PROMPTS_DIR = Path(__file__).parent / "prompts"

_FALLBACK = EquipmentReviewResponse(score=0, explanation="Review unavailable.", ref=[])


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = _CODE_FENCE.match(text)
    if m:
        return m.group(1).strip()
    if "```" in text:
        text = text[: text.index("```")].strip()
    return text


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

    # Take the last text block — comes after any web_search tool results
    texts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    if not texts:
        logger.error("no text block in equipment review response")
        return _FALLBACK

    raw = _strip_code_fence(texts[-1])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("JSON decode failed: %s | raw=%r", exc, raw[:300])
        return _FALLBACK

    if not isinstance(data, dict):
        logger.error("unexpected JSON type %s", type(data).__name__)
        return _FALLBACK

    try:
        return EquipmentReviewResponse(
            score=int(data.get("score", 0)),
            explanation=str(data.get("explanation", "")),
            ref=[str(u) for u in data.get("ref", []) if u],
        )
    except Exception as exc:
        logger.error("failed to build EquipmentReviewResponse: %s | data=%r", exc, data)
        return _FALLBACK
