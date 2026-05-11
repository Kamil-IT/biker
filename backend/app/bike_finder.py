import asyncio
import json
import logging
import re
from pathlib import Path

from anthropic import AsyncAnthropic

from .categories import BIKE_CATEGORIES
from .schemas import BikeResult, CategoryResult

logger = logging.getLogger("biker.finder")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
_CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)
PROMPTS_DIR = Path(__file__).parent / "prompts"

_SLUG_MAP: dict[str, str] = {name: slug for name, slug in BIKE_CATEGORIES}

MIN_SCORE = 5
TOTAL_BIKES = 5


def _strip_code_fence(text: str) -> str:
    m = _CODE_FENCE.match(text)
    return m.group(1).strip() if m else text


def filter_top_categories(results: list[CategoryResult]) -> list[CategoryResult]:
    qualifying = [r for r in results if r.score >= MIN_SCORE]
    if len(qualifying) < 2:
        qualifying = sorted(results, key=lambda r: r.score, reverse=True)[:2]
    return qualifying


def allocate_bikes(top: list[CategoryResult], total: int = TOTAL_BIKES) -> list[dict]:
    total_score = sum(r.score for r in top)
    exact = [r.score / total_score * total for r in top]
    floors = [int(e) for e in exact]
    remainder = total - sum(floors)
    indices = sorted(range(len(exact)), key=lambda i: exact[i] - floors[i], reverse=True)
    for i in indices[:remainder]:
        floors[i] += 1
    # guarantee minimum 1 per category (can push total above `total` in degenerate cases)
    for i in range(len(floors)):
        if floors[i] == 0:
            floors[i] = 1
    return [
        {"category": top[i].category, "slug": _SLUG_MAP.get(top[i].category, ""), "count": floors[i]}
        for i in range(len(top))
    ]


async def find_bikes_for_category(category: str, slug: str, count: int, user_search: str) -> list[BikeResult]:
    prompt_path = PROMPTS_DIR / f"bike_search_{slug}.md"
    system_prompt = prompt_path.read_text(encoding="utf-8")
    user_message = f"User search: {user_search}\nFind exactly {count} bike(s)."

    for attempt in range(2):
        response = await _client.messages.create(
            model=MODEL,
            max_tokens=1500,
            temperature=0,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        raw = response.content[0].text.strip()
        text = _strip_code_fence(raw)
        try:
            data = json.loads(text)
            if not isinstance(data, list):
                raise ValueError("expected JSON array")
            return [
                BikeResult(
                    brand=str(item["brand"]),
                    model=str(item["model"]),
                    accessories=list(item.get("accessories", [])),
                    match_score=float(item["match_score"]),
                    explanation=str(item["explanation"]),
                )
                for item in data
            ]
        except (json.JSONDecodeError, KeyError, ValueError):
            logger.warning("parse failed (attempt %d) | category=%r raw=%r", attempt + 1, category, raw)

    logger.error("bike search failed | category=%r", category)
    return []


async def find_all_bikes(allocation: list[dict], user_search: str) -> list[BikeResult]:
    tasks = [
        find_bikes_for_category(item["category"], item["slug"], item["count"], user_search)
        for item in allocation
    ]
    results = await asyncio.gather(*tasks)
    return [bike for category_bikes in results for bike in category_bikes]
