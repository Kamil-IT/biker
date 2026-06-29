import json
import logging
import re
import time

from anthropic import AsyncAnthropic

from .equipment_categories import EQUIPMENT_PROMPTS, display_name, resolve_category
from .schemas import BikeCategory, BikeSubcategory, ComponentElement, SpecItem

logger = logging.getLogger("biker.equipment.details")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
_CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = _CODE_FENCE.match(text)
    if m:
        return m.group(1).strip()
    if "```" in text:
        text = text[: text.index("```")].strip()
    return text


def _parse_spec(raw: object, idx: int) -> SpecItem:
    if not isinstance(raw, dict):
        logger.error("spec[%d] is not a dict: %r", idx, raw)
        return SpecItem(key="", value="")
    return SpecItem(key=str(raw.get("key", "")), value=str(raw.get("value", "")))


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


async def _search_raw_specs(company: str, model: str, slug: str) -> list[BikeCategory]:
    """Runs one focused web-search call for the resolved equipment category."""
    system_prompt = EQUIPMENT_PROMPTS[slug]
    item = f"{company} {model}".strip()
    user_message = f"Search for the {display_name(slug)} specifications for the {item} cycling equipment item."

    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        # TODO: enable web_search before prod
        # tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": user_message}],
    )

    elapsed = time.perf_counter() - t
    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens

    texts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    raw = _strip_code_fence("".join(texts))

    logger.info(
        "category=%r | elapsed=%.2fs input_tokens=%d output_tokens=%d chars=%d",
        slug, elapsed, input_tokens, output_tokens, len(raw),
    )

    categories: list[BikeCategory] = []
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            cat = _parse_category(data, 0)
            if cat.category:
                categories.append(cat)
        elif isinstance(data, list):
            for i, item_raw in enumerate(data):
                cat = _parse_category(item_raw, i)
                if cat.category:
                    categories.append(cat)
        else:
            logger.error("category=%r unexpected JSON type %s", slug, type(data).__name__)
    except json.JSONDecodeError as exc:
        logger.error("category=%r JSON decode failed: %s | raw=%r", slug, exc, raw[:300])

    logger.info(
        "total usage | input_tokens=%d output_tokens=%d categories=%d",
        input_tokens, output_tokens, len(categories),
    )
    return categories


async def find_equipment_details(company: str, model: str, category: str | None) -> tuple[str, list[BikeCategory]]:
    """Returns (resolved category slug, component tree)."""
    slug = resolve_category(company, model, category)
    t = time.perf_counter()
    logger.info("find_equipment_details start | company=%r model=%r category=%r", company, model, slug)
    result = await _search_raw_specs(company, model, slug)
    logger.info(
        "find_equipment_details done | category=%r categories=%d elapsed=%.2fs",
        slug, len(result), time.perf_counter() - t,
    )
    return slug, result
