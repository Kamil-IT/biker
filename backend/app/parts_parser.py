"""Free text → parts-catalogue filters (TODO-046): POST /v1/parts/parse.

One Claude Haiku call, no tools, prompt prompts/parts_parse.md — the parts
counterpart of bike_parser.py. The answer is validated here: part_type must be
one of the 12 slugs (anything else is dropped), strings are stripped and cut to
the search request's lengths, so a parse result always makes a valid
/v1/parts/search body. Any failure → the empty result (the route answers 400 "Part
not available in our database"), except an Anthropic 400 (e.g. no credits), which
reaches the app-wide handler (400 with Anthropic's message).
"""
import logging
from pathlib import Path

import anthropic
from anthropic import AsyncAnthropic

from .json_extract import extract_json
from .part_types import valid_part_type
from .schemas import PARTS_BRAND_MAX_LEN, PARTS_GROUPSET_MAX_LEN, PARTS_MODEL_MAX_LEN, PartsParseResponse

logger = logging.getLogger("biker.parts.parser")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
PROMPTS_DIR = Path(__file__).parent / "prompts"
TIMEOUT_S = 30.0  # a stuck parse reads as "nothing extracted", not a 10-minute wait


def _text(value, max_len: int):
    """A non-empty string cut to `max_len`, else None (numbers, lists, "" and whitespace are dropped)."""
    if not isinstance(value, str):
        return None
    s = " ".join(value.split())[:max_len].strip()
    return s or None


def to_parse_response(data) -> PartsParseResponse:
    """The model's JSON object → a validated PartsParseResponse (unknown keys and bad values dropped). Pure."""
    if not isinstance(data, dict):
        return PartsParseResponse()
    return PartsParseResponse(
        part_type=valid_part_type(data.get("part_type")),
        brand=_text(data.get("brand"), PARTS_BRAND_MAX_LEN),
        model=_text(data.get("model"), PARTS_MODEL_MAX_LEN),
        groupset=_text(data.get("groupset"), PARTS_GROUPSET_MAX_LEN),
    )


async def parse_parts_text(text: str) -> PartsParseResponse:
    # Read per call: `uvicorn --reload` only watches .py files.
    system_prompt = (PROMPTS_DIR / "parts_parse.md").read_text(encoding="utf-8")
    try:
        response = await _client.messages.create(
            model=MODEL,
            max_tokens=256,
            # anthropic 1.x dropped `temperature` from create(); it goes in the raw body (see bike_parser.py).
            extra_body={"temperature": 0},
            system=system_prompt,
            messages=[{"role": "user", "content": text}],
            timeout=TIMEOUT_S,
        )
        raw = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        return to_parse_response(extract_json(raw))
    except anthropic.BadRequestError:
        raise  # e.g. no credits: the app-wide handler answers 400 with Anthropic's message
    except Exception as exc:  # noqa: BLE001 — a bad answer or an API hiccup reads as "nothing extracted"
        logger.warning("parse_parts_text failed | text=%r | %s", text[:100], exc)
        return PartsParseResponse()
