import logging
import time
from pathlib import Path

from anthropic import AsyncAnthropic

from .json_extract import extract_json
from .schemas import BikeCategory, BikeSubcategory, ComponentElement, SpecItem

logger = logging.getLogger("biker.details")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"

DETAIL_CATEGORIES = [
    ("Frame",             "frame"),
    ("Drivetrain",        "drivetrain"),
    ("Brakes",            "brakes"),
    ("Wheels",            "wheels"),
    ("Cockpit",           "cockpit"),
    ("Saddle & Seatpost", "saddle"),
    ("Lighting",          "lighting"),
    ("Accessories",       "accessories"),
]


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


async def _search_raw_specs(company: str, model: str) -> list[BikeCategory]:
    """Runs one focused web-search call per category and aggregates results."""
    total_input_tokens = 0
    total_output_tokens = 0
    categories: list[BikeCategory] = []

    for category_name, slug in DETAIL_CATEGORIES:
        system_prompt = (PROMPTS_DIR / f"bike_details_{slug}.md").read_text(encoding="utf-8")
        user_message = f"Search for the {category_name} specifications for the {company} {model} bicycle."

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
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens

        texts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
        raw = "".join(texts)

        logger.info(
            "category=%r | elapsed=%.2fs input_tokens=%d output_tokens=%d chars=%d",
            category_name, elapsed, input_tokens, output_tokens, len(raw),
        )

        # The model routinely narrates ("I'll search for the Brakes specs...")
        # before emitting the JSON, so pull the object out of the prose rather
        # than assuming the whole response parses.
        data = extract_json(raw)
        if isinstance(data, dict):
            cat = _parse_category(data, 0)
            if cat.category:
                categories.append(cat)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                cat = _parse_category(item, i)
                if cat.category:
                    categories.append(cat)
        else:
            logger.error("category=%r no JSON found in response | raw=%r", category_name, raw[:300])

    logger.info(
        "total usage | input_tokens=%d output_tokens=%d categories=%d",
        total_input_tokens, total_output_tokens, len(categories),
    )
    return categories


async def find_bike_details(company: str, model: str) -> list[BikeCategory]:
    t = time.perf_counter()
    logger.info("find_bike_details start | company=%r model=%r", company, model)
    result = await _search_raw_specs(company, model)
    logger.info(
        "find_bike_details done | categories=%d elapsed=%.2fs",
        len(result), time.perf_counter() - t,
    )
    return result
