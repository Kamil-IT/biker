import json
import logging
import os
import re
from anthropic import AsyncAnthropic
from .schemas import CategoryResult

logger = logging.getLogger("biker.scorer")

MODEL = "claude-haiku-4-5-20251001"

# Instantiated at import time; ANTHROPIC_API_KEY must be in env before this module loads
# Log only whether the key is present — never any part of its value, which would
# put a credential fragment into every log file the server writes.
api_key = os.getenv("ANTHROPIC_API_KEY", "NOT_SET")
logger.info("initializing anthropic client | api_key_set=%s",
            bool(api_key and api_key != "NOT_SET"))
_client = AsyncAnthropic()

_CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    m = _CODE_FENCE.match(text)
    return m.group(1).strip() if m else text


async def score_category(search: str, category_name: str, system_prompt: str) -> CategoryResult:
    for attempt in range(2):
        try:
            logger.debug("calling anthropic api | category=%r attempt=%d", category_name, attempt + 1)
            response = await _client.messages.create(
                model=MODEL,
                max_tokens=200,
                temperature=0,
                system=system_prompt,
                messages=[{"role": "user", "content": search}],
            )
            logger.debug("api call succeeded | category=%r", category_name)
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
        except Exception as e:
            logger.error("api call failed | category=%r error_type=%s error_message=%s",
                        category_name, type(e).__name__, str(e))
            raise
