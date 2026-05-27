import json
import logging
import re
from pathlib import Path

from anthropic import AsyncAnthropic

from .schemas import ParseResponse

logger = logging.getLogger("biker.parser")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"
_CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)
_FALLBACK = ParseResponse()


def _strip_code_fence(text: str) -> str:
    m = _CODE_FENCE.match(text)
    return m.group(1).strip() if m else text


async def parse_free_text(text: str) -> ParseResponse:
    system_prompt = (PROMPTS_DIR / "bike_parse.md").read_text(encoding="utf-8")

    try:
        response = await _client.messages.create(
            model=MODEL,
            max_tokens=256,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": text}],
        )
        raw = response.content[0].text.strip()
        cleaned = _strip_code_fence(raw)
        data = json.loads(cleaned)

        return ParseResponse(
            brand=data.get("brand") or None,
            model=data.get("model") or None,
            year=data.get("year"),
            wheel_size=data.get("wheel_size") or None,
            is_electric=data.get("is_electric"),
            has_suspension=data.get("has_suspension"),
            is_kids=data.get("is_kids"),
        )
    except Exception:
        logger.warning("parse_free_text failed | text=%r", text[:100])
        return _FALLBACK
