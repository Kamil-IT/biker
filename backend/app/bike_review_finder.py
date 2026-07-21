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
# web_search makes the model wrap quoted claims in <cite index="..."> markup;
# strip it so the explanation reads as plain prose.
_CITE_TAG = re.compile(r"</?cite\b[^>]*>")
PROMPTS_DIR = Path(__file__).parent / "prompts"

_FALLBACK = BikeReviewResponse(
    score=0, explanation="Review unavailable.", ref=[], rating=0.0, sources_used=0
)

# Weighting scheme (TODO-013; tier list and rationale in
# backlog/TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md):
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


def _extract_json_object(text: str) -> dict | None:
    """Find the first balanced top-level {...} in text and parse it as a dict.

    The model sometimes wraps or precedes the JSON with narration of its web
    search, so we cannot assume the whole block is JSON."""
    try:
        data = json.loads(_strip_code_fence(text))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    # Scan the ORIGINAL text, not the fence-stripped one: when the model
    # narrates first and then opens a ```json fence, stripping truncates at
    # the fence marker and discards the object we are looking for.
    start = -1
    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    return data
    return None


async def _repair_to_json(
    system_prompt: str, company: str, model: str, findings: str
) -> dict | None:
    """Second-pass call that reformats the model's prose findings into JSON.

    The search turn sometimes ends with narration instead of the JSON object.
    Rather than lose an already-paid-for web search, re-send those findings
    with no tools and an assistant prefill of "{" so the only thing the model
    can produce is the object itself."""
    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": (
                    f"These are the review findings you gathered for {company} {model}:\n\n"
                    f"<findings>\n{findings}\n</findings>\n\n"
                    "Convert them into the single JSON object defined in the output "
                    "format. Use only sources named in the findings — do not invent "
                    "any. Output the object and nothing else."
                ),
            },
            {"role": "assistant", "content": "{"},
        ],
    )
    elapsed = time.perf_counter() - t
    logger.info(
        "review repair done | elapsed=%.2fs input_tokens=%d output_tokens=%d",
        elapsed,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )

    texts = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    if not texts:
        return None
    # Re-attach the prefilled opening brace the API stripped from the output.
    return _extract_json_object("{" + texts[0])


async def find_bike_review(company: str, model: str) -> BikeReviewResponse:
    system_prompt = (PROMPTS_DIR / "bike_review.md").read_text(encoding="utf-8")
    user_message = f"Find reviews for: {company} {model}"

    t = time.perf_counter()
    response = await _client.messages.create(
        model=MODEL,
        max_tokens=4000,
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

    # The model interleaves narration with web_search results, so the JSON is
    # not reliably the last block — scan every text block, newest first.
    texts = [
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
    ]
    if not texts:
        logger.error("no text block in response")
        return _FALLBACK

    data = None
    for candidate in reversed(texts):
        found = _extract_json_object(candidate)
        if found is not None and "explanation" in found:
            data = found
            break

    if data is None:
        logger.warning(
            "no JSON object in %d text block(s), attempting repair | last=%r",
            len(texts),
            texts[-1][:200],
        )
        data = await _repair_to_json(
            system_prompt, company, model, "\n\n".join(texts)
        )

    if data is None or "explanation" not in data:
        logger.error("review extraction failed after repair | last=%r", texts[-1][:300])
        return _FALLBACK

    per_source = data.get("per_source", [])
    if not isinstance(per_source, list):
        per_source = []
    rating, sources_used = _aggregate_rating(per_source)

    try:
        return BikeReviewResponse(
            score=int(data.get("score", 0)),
            explanation=_CITE_TAG.sub("", str(data.get("explanation", ""))).strip(),
            ref=[str(u) for u in data.get("ref", []) if u],
            rating=rating,
            sources_used=sources_used,
        )
    except Exception as exc:
        logger.error("failed to build BikeReviewResponse: %s | data=%r", exc, data)
        return _FALLBACK
