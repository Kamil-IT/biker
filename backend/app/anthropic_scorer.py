import json
import logging
import re
from anthropic import AsyncAnthropic
from .schemas import CategoryResult

logger = logging.getLogger("biker.scorer")

MODEL = "claude-haiku-4-5-20251001"

# Instantiated at import time; ANTHROPIC_API_KEY must be in env before this module loads
_client = AsyncAnthropic()

_CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    m = _CODE_FENCE.match(text)
    return m.group(1).strip() if m else text


async def score_category(search: str, category_name: str, system_prompt: str) -> CategoryResult:
    for attempt in range(2):
        response = await _client.messages.create(
            model=MODEL,
            max_tokens=200,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": search}],
        )
        raw = response.content[0].text.strip()
        text = _strip_code_fence(raw)
        try:
            data = json.loads(text)
            return CategoryResult(
                category=category_name,
                score=int(data["score"]),
                explanation=str(data["explanation"]),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning("parse failed (attempt %d) | category=%r raw=%r", attempt + 1, category_name, raw)
            if attempt == 1:
                logger.error("returning error result | category=%r raw=%r", category_name, raw)
                return CategoryResult(
                    category=category_name,
                    score=0,
                    explanation=f"Parse error — raw response: {raw}",
                )
