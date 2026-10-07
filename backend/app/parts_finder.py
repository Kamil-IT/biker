"""AI parts search (TODO-046): POST /v1/parts/search/ai — clicked, never automatic.

ONE Claude Haiku call with the web_search tool (the model and tool of
equipment_review_finder.py), prompt prompts/parts_search.md. The query goes in
as a JSON object inside <query> tags: every field is data, never instructions,
and JSON encoding keeps a quote or a newline in it from breaking out. The answer
is ≤ 10 parts {brand, model, part_type, groupset, key_specs}, parsed with
json_extract.extract_json() — bad JSON → [] (never a 502) — and each part is
cleaned (clean_found_part): part_type one of the 12 slugs, strings cut to the
equipment column widths, ≤ 6 chips of ≤ 40 characters, the brand dropped from
the start of the model. With a part_type in the query, a part of another type is
dropped and an untyped one takes the query's type.
"""
import json
import logging
import time
from pathlib import Path
from typing import Optional

from anthropic import AsyncAnthropic

from .json_extract import extract_json
from .part_types import part_type_name, valid_part_type
from .parts_repository import COMPANY_MAX, GROUPSET_MAX, MODEL_MAX, FoundPart, clean_key_specs
from .schemas import PartsSearchRequest

logger = logging.getLogger("biker.parts.finder")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"

MAX_PARTS = 10
MAX_TOKENS = 4000
WEB_SEARCH_MAX_USES = 4


def _text(value, max_len: int) -> str:
    return " ".join(value.split())[:max_len].strip() if isinstance(value, str) else ""


def clean_found_part(item, requested_type: Optional[str]) -> Optional[FoundPart]:
    """One element of the model's list → a FoundPart, or None when unusable (no brand / model,
    another type than the requested one). Pure."""
    if not isinstance(item, dict):
        return None
    brand = _text(item.get("brand"), COMPANY_MAX)
    model = _text(item.get("model"), MODEL_MAX)
    # The model is stored WITHOUT the brand ("Shimano" + "Deore CS-M6100-12"); name = "Brand Model".
    if brand and model.lower().startswith(brand.lower() + " "):
        model = model[len(brand):].strip()
    if not brand or not model:
        return None
    part_type = valid_part_type(item.get("part_type"))
    if requested_type:
        if part_type and part_type != requested_type:
            return None
        part_type = requested_type
    return FoundPart(
        brand=brand, model=model, part_type=part_type,
        groupset=_text(item.get("groupset"), GROUPSET_MAX) or None,
        key_specs=clean_key_specs(item.get("key_specs")),
    )


def user_message(req: PartsSearchRequest) -> str:
    """The query as data: a JSON object inside <query> tags (the prompt says so). Pure."""
    query = {
        "part_type": f"{req.part_type} ({part_type_name(req.part_type)})" if req.part_type else None,
        "brand": req.brand, "model": req.model, "groupset": req.groupset, "text": req.search,
    }
    body = json.dumps({k: v for k, v in query.items() if v}, ensure_ascii=False)
    return f"Find real bicycle parts matching this catalogue query.\n<query>\n{body}\n</query>"


def parse_found(raw: str, requested_type: Optional[str]) -> list[FoundPart]:
    """The model's text → ≤ 10 cleaned parts, duplicates (same brand + model) dropped. Pure."""
    data = extract_json(raw)
    if isinstance(data, dict):
        data = data.get("parts", [])
    if not isinstance(data, list):
        logger.error("parts search parse failed | raw=%r", raw[:500])
        return []
    parts: list[FoundPart] = []
    seen: set[tuple[str, str]] = set()
    for item in data:
        part = clean_found_part(item, requested_type)
        key = (part.brand.lower(), part.model.lower()) if part else None
        if part and key not in seen:
            seen.add(key)
            parts.append(part)
        if len(parts) == MAX_PARTS:
            break
    return parts


async def find_parts_ai(req: PartsSearchRequest) -> list[FoundPart]:
    """ONE Haiku + web_search call → the cleaned parts ([] on bad JSON). API errors raise."""
    system_prompt = (PROMPTS_DIR / "parts_search.md").read_text(encoding="utf-8")
    t_start = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": WEB_SEARCH_MAX_USES}],
        messages=[{"role": "user", "content": user_message(req)}],
    )
    if response.stop_reason == "max_tokens":
        logger.warning("parts search hit max_tokens=%d — JSON may be truncated", MAX_TOKENS)
    texts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
    # The JSON comes last, after any narration between the searches: the last text block when it
    # holds the JSON, else all of them joined (a cited answer is split over several blocks).
    last = texts[-1] if texts else ""
    parts = parse_found(last if extract_json(last) is not None else "".join(texts), req.part_type)
    logger.info(
        "parts found by AI | count=%d in_tokens=%d out_tokens=%d elapsed=%.2fs",
        len(parts), response.usage.input_tokens, response.usage.output_tokens, time.perf_counter() - t_start,
    )
    return parts
