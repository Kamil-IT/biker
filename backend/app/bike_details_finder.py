import json
import logging
import re
import time
from pathlib import Path

from anthropic import AsyncAnthropic

from .schemas import BikeCategory, BikeSubcategory, ComponentElement, SpecItem

logger = logging.getLogger("biker.details")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
_CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)
PROMPTS_DIR = Path(__file__).parent / "prompts"


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = _CODE_FENCE.match(text)
    if m:
        return m.group(1).strip()
    if "```" in text:
        text = text[:text.index("```")].strip()
    return text


def _parse_spec(raw: object, idx: int) -> SpecItem:
    if not isinstance(raw, dict):
        logger.error("spec[%d] is not a dict: %r", idx, raw)
        return SpecItem(key="", value="")
    return SpecItem(
        key=str(raw.get("key", "")),
        value=str(raw.get("value", "")),
    )


def _parse_element(raw: object, idx: int) -> ComponentElement:
    if not isinstance(raw, dict):
        logger.error("element[%d] is not a dict: %r", idx, raw)
        return ComponentElement(name="", description="", specs=[])
    return ComponentElement(
        name=str(raw.get("name", "")),
        description=str(raw.get("description", "")),
        specs=[_parse_spec(s, i) for i, s in enumerate(raw.get("specs", []))],
    )


def _parse_subcategory(raw: object, idx: int) -> BikeSubcategory:
    if not isinstance(raw, dict):
        logger.error("subcategory[%d] is not a dict: %r", idx, raw)
        return BikeSubcategory(subcategory="", elements=[])
    return BikeSubcategory(
        subcategory=str(raw.get("subcategory", "")),
        elements=[_parse_element(e, i) for i, e in enumerate(raw.get("elements", []))],
    )


def _parse_category(raw: object, idx: int) -> BikeCategory:
    if not isinstance(raw, dict):
        logger.error("category[%d] is not a dict: %r", idx, raw)
        return BikeCategory(category="", subcategories=[])
    return BikeCategory(
        category=str(raw.get("category", "")),
        subcategories=[_parse_subcategory(s, i) for i, s in enumerate(raw.get("subcategories", []))],
    )


def _try_parse(text: str) -> list[BikeCategory] | None:
    """Return parsed categories if text is valid JSON array, else None."""
    text = _strip_code_fence(text)
    try:
        data = json.loads(text)
        if not isinstance(data, list):
            return None
        return [_parse_category(item, i) for i, item in enumerate(data)]
    except (json.JSONDecodeError, Exception):
        return None


async def _search_raw_specs(company: str, model: str) -> tuple[list, str]:
    """Phase 1: web search. Returns (conversation_messages, raw_text)."""
    example = (PROMPTS_DIR / "bike_details_json_example.md").read_text(encoding="utf-8")
    user_message = {
        "role": "user",
        "content": (
            f"Search for the complete technical specifications for the {company} {model} bicycle.\n\n"
            f"<example_output>\n{example}\n</example_output>"
        ),
    }

    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[
            user_message,
            {"role": "assistant", "content": "```json"},
        ],
    )

    texts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    combined = "".join(texts)
    logger.info(
        "phase1 done | elapsed=%.2fs input_tokens=%d output_tokens=%d raw_chars=%d",
        time.perf_counter() - t,
        response.usage.input_tokens,
        response.usage.output_tokens,
        len(combined),
    )

    if "```" in combined:
        logger.info("phase1 truncating at ``` | before_chars=%d preview=%r", len(combined), combined[:200])
        combined = combined[:combined.index("```")].strip()
        logger.info("phase1 after truncation | chars=%d", len(combined))

    # Preserve full conversation for Phase 2 continuation
    messages = [user_message, {"role": "assistant", "content": response.content}]
    return messages, combined


async def _format_as_json(
    company: str, model: str, prev_messages: list, raw_specs: str
) -> list[BikeCategory]:
    """Phase 2: continue Phase 1 conversation and request structured JSON."""
    system_prompt = (PROMPTS_DIR / "bike_details.md").read_text(encoding="utf-8")

    messages = prev_messages + [{
        "role": "user",
        "content": (
            f"Convert the following specifications for the {company} {model} "
            f"into the required JSON format:\n\n{raw_specs}"
        ),
    }]

    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=8000,
        system=system_prompt,
        messages=messages,
    )

    text = ""
    for block in response.content:
        if getattr(block, "type", None) == "text":
            text = block.text

    text = _strip_code_fence(text)
    logger.info(
        "phase2 done | elapsed=%.2fs input_tokens=%d output_tokens=%d response_chars=%d",
        time.perf_counter() - t,
        response.usage.input_tokens,
        response.usage.output_tokens,
        len(text),
    )

    try:
        data = json.loads(text)
        if not isinstance(data, list):
            logger.error("expected JSON array, got %s | raw=%r", type(data).__name__, text[:300])
            return []
        categories = [_parse_category(item, i) for i, item in enumerate(data)]
        logger.info(
            "phase2 parsed | categories=%d subcategories=%d elements=%d",
            len(categories),
            sum(len(c.subcategories) for c in categories),
            sum(len(s.elements) for c in categories for s in c.subcategories),
        )
        return categories
    except json.JSONDecodeError as exc:
        logger.error("JSON decode failed: %s | raw=%r", exc, text[:500])
        return []


async def find_bike_details(company: str, model: str) -> list[BikeCategory]:
    t = time.perf_counter()
    logger.info("find_bike_details start | company=%r model=%r", company, model)

    messages, raw_specs = await _search_raw_specs(company, model)

    if not raw_specs.strip():
        logger.error("phase1 returned no text | company=%r model=%r", company, model)
        return []

    result = _try_parse(raw_specs)
    if result is not None:
        logger.info(
            "phase1 parse OK — skipping phase2 | categories=%d elapsed=%.2fs",
            len(result),
            time.perf_counter() - t,
        )
        return result

    logger.info("phase1 parse FAILED — not valid JSON, proceeding to phase2 | raw=%r", raw_specs)

    result = await _format_as_json(company, model, messages, raw_specs)
    logger.info(
        "find_bike_details done | categories=%d elapsed=%.2fs",
        len(result),
        time.perf_counter() - t,
    )
    return result
