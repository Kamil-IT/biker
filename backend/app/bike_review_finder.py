import json
import logging
import re
import time
from pathlib import Path

from anthropic import AsyncAnthropic

from .schemas import BikeReviewResponse

logger = logging.getLogger("biker.review")

MODEL = "claude-haiku-4-5-20251001"
_client = AsyncAnthropic()
_CODE_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)
PROMPTS_DIR = Path(__file__).parent / "prompts"

_FALLBACK = BikeReviewResponse(
    score=0, explanation="Review unavailable.", ref=[], rating=0.0, sources_used=0
)

# Weighting scheme (TODO-013, see backend/docs/review_sources.md):
# pro/numeric 3x, pro/qualitative 2x, community 1x. A non-zero aggregate
# rating requires at least one professional source.
_SOURCE_WEIGHTS = {"pro_numeric": 3.0, "pro_qualitative": 2.0, "community": 1.0}
_PRO_TYPES = {"pro_numeric", "pro_qualitative"}


def _aggregate_rating(per_source: list) -> tuple[float, int]:
    """Weighted mean of per-source scores, normalised to 0–10.

    Returns (rating, sources_used). Requires >=1 professional source for a
    non-zero rating; otherwise returns (0.0, 0)."""
    weighted_sum = 0.0
    weight_total = 0.0
    used = 0
    has_pro = False

    for entry in per_source:
        if not isinstance(entry, dict):
            continue
        stype = str(entry.get("type", "")).strip().lower()
        weight = _SOURCE_WEIGHTS.get(stype)
        if weight is None:
            continue
        try:
            score = float(entry.get("score"))
        except (TypeError, ValueError):
            continue
        score = max(0.0, min(10.0, score))
        weighted_sum += score * weight
        weight_total += weight
        used += 1
        if stype in _PRO_TYPES:
            has_pro = True

    if weight_total == 0 or not has_pro:
        return 0.0, 0
    return round(weighted_sum / weight_total, 1), used


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    m = _CODE_FENCE.match(text)
    if m:
        return m.group(1).strip()
    if "```" in text:
        text = text[: text.index("```")].strip()
    return text


async def find_bike_review(company: str, model: str) -> BikeReviewResponse:
    system_prompt = (PROMPTS_DIR / "bike_review.md").read_text(encoding="utf-8")
    user_message = f"Find reviews for: {company} {model}"

    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=system_prompt,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": user_message}],
    )
    elapsed = time.perf_counter() - t

    input_tokens = response.usage.input_tokens
    output_tokens = response.usage.output_tokens
    logger.info(
        "review search done | elapsed=%.2fs input_tokens=%d output_tokens=%d",
        elapsed,
        input_tokens,
        output_tokens,
    )

    # Take the last text block — comes after any web_search tool results
    texts = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    if not texts:
        logger.error("no text block in response")
        return _FALLBACK

    raw = _strip_code_fence(texts[-1])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("JSON decode failed: %s | raw=%r", exc, raw[:300])
        return _FALLBACK

    if not isinstance(data, dict):
        logger.error("unexpected JSON type %s", type(data).__name__)
        return _FALLBACK

    per_source = data.get("per_source", [])
    if not isinstance(per_source, list):
        per_source = []
    rating, sources_used = _aggregate_rating(per_source)

    try:
        return BikeReviewResponse(
            score=int(data.get("score", 0)),
            explanation=str(data.get("explanation", "")),
            ref=[str(u) for u in data.get("ref", []) if u],
            rating=rating,
            sources_used=sources_used,
        )
    except Exception as exc:
        logger.error("failed to build BikeReviewResponse: %s | data=%r", exc, data)
        return _FALLBACK
