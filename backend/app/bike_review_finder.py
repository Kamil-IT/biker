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

# TODO-018 — source-disagreement rule. When the highest and lowest per-source
# scores differ by MORE than this many points (on the 0–10 scale), a weighted
# mean would hide the split, so we anchor the rating to the professional
# sources instead and say so in the explanation.
#
# Evidence for the value: the research behind TODO-013 wrote it as "~3 points"
# without a measured corpus, and the repo has no captured spread data to fit
# against. 3.0 holds up against the scoring bands the prompt itself defines
# (0–3 poor, 4–5 average, 6–7 good, 8–9 excellent): a spread of <=3 keeps every
# source inside two adjacent bands — normal reviewer variance — while a spread
# of >3 means at least one source calls the bike average-or-worse while another
# calls it excellent. That is the divisive case a buyer must be told about.
DISAGREEMENT_THRESHOLD = 3.0

# Rank used to order `ref` and to pick the anchor tier: Tier 1 → 2 → 3.
_TIER_RANK = {"pro_numeric": 0, "pro_qualitative": 1, "community": 2}
_UNKNOWN_TIER_RANK = 3


def _clean_sources(per_source: list) -> list[dict]:
    """Keep only entries with a known tier type and a parseable 0–10 score."""
    cleaned: list[dict] = []
    for entry in per_source:
        if not isinstance(entry, dict):
            continue
        stype = str(entry.get("type", "")).strip().lower()
        if stype not in _SOURCE_WEIGHTS:
            continue
        try:
            score = float(entry.get("score"))
        except (TypeError, ValueError):
            continue
        cleaned.append(
            {
                "type": stype,
                "score": max(0.0, min(10.0, score)),
                "url": str(entry.get("url") or ""),
                "source": str(entry.get("source") or ""),
            }
        )
    return cleaned


def _aggregate_rating(per_source: list) -> tuple[float, int, dict]:
    """Aggregate per-source scores into a single 0–10 rating.

    Normally a weighted mean (pro_numeric 3x, pro_qualitative 2x, community
    1x). When the spread between the highest and lowest score exceeds
    DISAGREEMENT_THRESHOLD, the mean is replaced by the mean of the best tier
    present (Tier 1, else Tier 2) so a divisive bike is not smoothed into a
    middling number.

    Returns (rating, sources_used, info) where info describes what happened:
    `{"disagreement": bool, "spread": float, "low": float, "high": float,
      "anchor_tier": str | None, "weighted_mean": float}`. Requires >=1
    professional source for a non-zero rating; otherwise returns (0.0, 0, ...)."""
    cleaned = _clean_sources(per_source)
    info = {
        "disagreement": False,
        "spread": 0.0,
        "low": 0.0,
        "high": 0.0,
        "anchor_tier": None,
        "weighted_mean": 0.0,
    }

    has_pro = any(e["type"] in _PRO_TYPES for e in cleaned)
    if not cleaned or not has_pro:
        return 0.0, 0, info

    weighted_sum = sum(e["score"] * _SOURCE_WEIGHTS[e["type"]] for e in cleaned)
    weight_total = sum(_SOURCE_WEIGHTS[e["type"]] for e in cleaned)
    weighted_mean = round(weighted_sum / weight_total, 1)

    scores = [e["score"] for e in cleaned]
    low, high = min(scores), max(scores)
    spread = round(high - low, 1)
    info.update(
        {"spread": spread, "low": low, "high": high, "weighted_mean": weighted_mean}
    )

    # sources_used counts every consulted source regardless of the rule taken.
    used = len(cleaned)

    if spread <= DISAGREEMENT_THRESHOLD:
        return weighted_mean, used, info

    for tier in ("pro_numeric", "pro_qualitative"):
        anchored = [e["score"] for e in cleaned if e["type"] == tier]
        if anchored:
            info["disagreement"] = True
            info["anchor_tier"] = tier
            return round(sum(anchored) / len(anchored), 1), used, info

    # Unreachable while has_pro is required, but keep the documented fallback:
    # no professional source to anchor to → behave exactly as before.
    return weighted_mean, used, info


_TIER_LABEL = {
    "pro_numeric": "professional reviews that publish a score",
    "pro_qualitative": "professional reviews",
}


def _disagreement_note(info: dict) -> str:
    """One sentence stating the spread and which camp the rating follows."""
    label = _TIER_LABEL.get(info.get("anchor_tier"), "professional reviews")
    return (
        f"Sources disagree on this bike: individual scores range from "
        f"{info['low']:.0f} to {info['high']:.0f} out of 10, a spread of "
        f"{info['spread']:.0f} points — wider than the {DISAGREEMENT_THRESHOLD:.0f}-point "
        f"threshold at which we stop averaging. The rating shown therefore follows the "
        f"{label} rather than the blended average of "
        f"{info['weighted_mean']:.1f}, which would hide the split."
    )


def _order_ref(refs: list[str], per_source: list) -> list[str]:
    """Order `ref` by source tier (1 → 2 → 3), stable within a tier.

    The model emits `ref` in whatever order it happened to compile — a Reddit
    thread can land above BikeRadar. Sorting here makes the priority ordering
    the guide asks for a guarantee rather than an accident. URLs with no
    matching `per_source` entry keep their relative order at the end."""
    rank_by_url = {}
    for entry in _clean_sources(per_source):
        if entry["url"] and entry["url"] not in rank_by_url:
            rank_by_url[entry["url"]] = _TIER_RANK[entry["type"]]
    return sorted(refs, key=lambda u: rank_by_url.get(u, _UNKNOWN_TIER_RANK))


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
    rating, sources_used, info = _aggregate_rating(per_source)

    explanation = _CITE_TAG.sub("", str(data.get("explanation", ""))).strip()
    if info["disagreement"]:
        logger.info(
            "source disagreement | spread=%.1f low=%.1f high=%.1f "
            "weighted_mean=%.1f anchored=%.1f tier=%s",
            info["spread"],
            info["low"],
            info["high"],
            info["weighted_mean"],
            rating,
            info["anchor_tier"],
        )
        explanation = f"{explanation} {_disagreement_note(info)}".strip()

    ref = _order_ref([str(u) for u in data.get("ref", []) if u], per_source)

    try:
        return BikeReviewResponse(
            score=int(data.get("score", 0)),
            explanation=explanation,
            ref=ref,
            rating=rating,
            sources_used=sources_used,
        )
    except Exception as exc:
        logger.error("failed to build BikeReviewResponse: %s | data=%r", exc, data)
        return _FALLBACK
