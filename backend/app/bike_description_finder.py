import logging
import time
from pathlib import Path

from anthropic import AsyncAnthropic

logger = logging.getLogger("biker.description")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"

_FALLBACK = ""


async def find_bike_description(company: str, model: str) -> str:
    system_prompt = (PROMPTS_DIR / "bike_description.md").read_text(encoding="utf-8")

    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": f"Describe the {company} {model} bicycle in 4–5 sentences."}],
    )
    elapsed = time.perf_counter() - t

    texts = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    if not texts:
        logger.error("no text block in description response")
        return _FALLBACK

    text = " ".join(t.strip() for t in texts if t.strip())
    logger.info(
        "description done | elapsed=%.2fs input_tokens=%d output_tokens=%d\n%s",
        elapsed,
        response.usage.input_tokens,
        response.usage.output_tokens,
        text,
    )
    logger.info(
        response.content
    )

    return text
