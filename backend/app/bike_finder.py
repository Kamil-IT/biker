"""Single-call AI bike finder — the fallback when the DB has no match (TODO-024)."""
import logging
import time
from pathlib import Path

from anthropic import AsyncAnthropic

from .json_extract import extract_json
from .schemas import BikeResult

logger = logging.getLogger("biker.finder")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"

# No result cap (TODO-025): room for a long list without cutting the JSON mid-array.
MAX_TOKENS = 8000


def _to_bike(item) -> BikeResult | None:
    if not isinstance(item, dict):
        return None
    try:
        return BikeResult(
            brand=str(item["brand"]).strip(),
            model=str(item["model"]).strip(),
            accessories=[str(a) for a in item.get("accessories") or []],
            match_score=max(0.0, min(10.0, float(item["match_score"]))),
            explanation=str(item.get("explanation", "")),
        )
    except (KeyError, TypeError, ValueError):
        return None


async def find_bikes(user_search: str) -> list[BikeResult]:
    """ONE Claude call → every matching bike (min 1, closest match). [] only on bad JSON."""
    # Read per call, like the other finders: `uvicorn --reload` only watches
    # .py files, so a module-level read kept serving a stale prompt after edits.
    system_prompt = (PROMPTS_DIR / "bike_search.md").read_text(encoding="utf-8")
    t_start = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=0,
        system=system_prompt,
        messages=[{
            "role": "user",
            "content": f"User search: {user_search}",
        }],
    )
    if response.stop_reason == "max_tokens":
        logger.warning("bike search hit max_tokens=%d — JSON may be truncated", MAX_TOKENS)
    raw = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    data = extract_json(raw)
    if isinstance(data, dict):
        data = data.get("bikes", [])
    if not isinstance(data, list):
        logger.error("bike search parse failed | raw=%r", raw[:500])
        return []

    bikes = [b for b in (_to_bike(item) for item in data) if b and b.brand and b.model]
    logger.info(
        "bikes found | count=%d out_tokens=%d elapsed=%.2fs",
        len(bikes), response.usage.output_tokens, time.perf_counter() - t_start,
    )
    return bikes
