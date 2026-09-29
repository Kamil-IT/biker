"""Bike expert review search — the backend's old bike_review_finder, moved here (TODO-037).

Same prompt (prompts/bike_review.md), same user message and the same
post-processing, byte-for-byte in logic: per-source weights (pro_numeric 3×,
pro_qualitative 2×, community 1×), a non-zero rating only with ≥ 1
professional source, DISAGREEMENT_THRESHOLD anchoring plus the Polish
disagreement sentence, `ref` ordered Tier 1 → 2 → 3, `<cite>` markup stripped.

Transport changed: the Claude Code CLI (`claude -p --json-schema`, billed to
the subscription) instead of the Anthropic SDK `web_search` tool. That makes
two pieces of the old finder unnecessary, so they are gone rather than ported:
- the balanced-brace JSON scan over every text block — the CLI returns
  `structured_output`, a dict already validated against REVIEW_SCHEMA, so
  there is no narration to dig the object out of;
- the no-tool "repair pass" with a `{` prefill — it existed to rescue a turn
  that ended in prose instead of JSON. Under --json-schema such a run either
  produces the structured object or fails (ClaudeCliError → SearcherError →
  502, the UI button becomes clickable again), and a second CLI run would cost
  another full search turn for no better odds.
A result without an `explanation` is still the old fallback review (score 0,
"Recenzja niedostępna.", no sources), which the caller never stores.
"""
import asyncio
import logging
import re
import time
from urllib.parse import urlsplit

from . import config
from .claude_cli import ClaudeCliError, run_structured
from .olx_finder import URL_MAX_LEN, SearcherError
from .schemas import BikeReview

logger = logging.getLogger("searcher.review")

PROMPT_FILE = config.PROMPTS_DIR / "bike_review.md"
# The model wraps quoted claims in (cite index="..."> markup when it quotes
# search results; strip it so the explanation reads as plain prose.
_CITE_TAG = re.compile(r"</?cite\b[^>]*>")

# Domains the prompt forbids (escapecollective.com: paywalled; velominati.com:
# culture, not testing). The CLI probe still cited escapecollective.com, so
# they are also dropped in code — from per_source before aggregation (they
# never count in rating / sources_used) and from ref. Subdomains included.
BANNED_REVIEW_DOMAINS = frozenset({"escapecollective.com", "velominati.com"})
# The prompt asks for 5–10 sentences; anything far longer is a runaway answer.
EXPLANATION_MAX_LEN = 4000

FALLBACK = BikeReview(score=0, explanation="Recenzja niedostępna.", ref=[], rating=0.0, sources_used=0)

# The prompt's "Output format" object. `type` is left a free string (not an
# enum): an unknown tier is dropped by _clean_sources exactly as before, where
# an enum would make the CLI reject — and re-ask for — the whole answer.
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "explanation": {"type": "string"},
        "per_source": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "type": {"type": "string"},
                    "score": {"type": "number"},
                    "url": {"type": "string"},
                },
                "required": ["source", "type", "score", "url"],
            },
        },
        "ref": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "explanation", "per_source", "ref"],
}

# Weighting scheme (TODO-013; tier list and rationale in
# backlog/done/DONE_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md):
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
    "pro_numeric": "profesjonalnych recenzji podających ocenę liczbową",
    "pro_qualitative": "profesjonalnych recenzji",
}


def _disagreement_note(info: dict) -> str:
    """One sentence (Polish, like the rest of the explanation) stating the spread
    and which camp the rating follows."""
    label = _TIER_LABEL.get(info.get("anchor_tier"), "profesjonalnych recenzji")
    return (
        f"Źródła nie są zgodne co do tego roweru: poszczególne oceny wahają się od "
        f"{info['low']:.0f} do {info['high']:.0f} na 10, czyli różnią się o "
        f"{info['spread']:.0f} pkt — więcej niż próg {DISAGREEMENT_THRESHOLD:.0f} pkt, "
        f"powyżej którego przestajemy uśredniać. Dlatego pokazana ocena opiera się na "
        f"{label}, a nie na średniej ważonej {info['weighted_mean']:.1f}, "
        f"która ukryłaby ten rozdźwięk."
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


def _host(value: str) -> str:
    """Lower-cased host of a URL or bare domain ("www." stripped), "" when there is none."""
    value = value.strip()
    if "://" not in value:
        value = "//" + value  # a bare "escapecollective.com/…" or source name
    try:
        host = (urlsplit(value).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _is_banned(value: str) -> bool:
    host = _host(value)
    return any(host == d or host.endswith("." + d) for d in BANNED_REVIEW_DOMAINS)


def is_safe_review_url(url) -> bool:
    """A review URL fit to store and to render as a link.

    http/https with a non-empty host (no javascript:, data:, relative or
    scheme-less value — every viewer's browser gets it as an <a href>), at most
    URL_MAX_LEN characters (bike_review_source.url is String(2048)), and not
    on a BANNED_REVIEW_DOMAINS host. The rule for every stored `ref` URL —
    backend/scripts/copy_review_cache_to_table.py duplicates it.
    """
    if not isinstance(url, str) or not url or len(url) > URL_MAX_LEN or url != url.strip():
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.netloc) and not _is_banned(url)


def _drop_unsafe_sources(per_source: list) -> list:
    """per_source without entries whose url fails is_safe_review_url (bad scheme, no host,
    banned domain) — dropped before aggregation, so they never count in rating / sources_used."""
    kept = []
    for entry in per_source:
        if isinstance(entry, dict) and not is_safe_review_url(entry.get("url")):
            logger.warning(
                "review source dropped (unsafe or banned url) | url=%r source=%r",
                str(entry.get("url"))[:200], entry.get("source"),
            )
            continue
        kept.append(entry)
    return kept


def build_review(data: dict) -> BikeReview:
    """The structured CLI answer → BikeReview, with the old finder's post-processing.

    Pure (no I/O), so the rating logic can be checked against the backend's
    old output on the same per-source input.
    """
    if not isinstance(data, dict) or "explanation" not in data:
        logger.error("review result has no explanation | data=%r", data)
        return FALLBACK

    per_source = data.get("per_source", [])
    if not isinstance(per_source, list):
        per_source = []
    per_source = _drop_unsafe_sources(per_source)
    rating, sources_used, info = _aggregate_rating(per_source)

    explanation = _CITE_TAG.sub("", str(data.get("explanation", ""))).strip()
    note = _disagreement_note(info) if info["disagreement"] else ""
    # Cap the model's text so explanation + note stays within EXPLANATION_MAX_LEN.
    explanation = explanation[: EXPLANATION_MAX_LEN - (len(note) + 1 if note else 0)].rstrip()
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
        explanation = f"{explanation} {note}".strip()

    refs = data.get("ref", [])
    if not isinstance(refs, list):
        refs = []
    # Unsafe, banned or over-long (> String(2048), which would fail the write after
    # the CLI run was already paid for) URLs are dropped here.
    ref = _order_ref([u for u in refs if is_safe_review_url(u)], per_source)

    try:
        return BikeReview(
            score=int(data.get("score", 0)),
            explanation=explanation,
            ref=ref,
            rating=rating,
            sources_used=sources_used,
        )
    except Exception as exc:  # noqa: BLE001 — a malformed score must not sink the request
        logger.error("failed to build BikeReview: %s | data=%r", exc, data)
        return FALLBACK


async def find_bike_review(company: str, model: str) -> BikeReview:
    """One CLI review search for the bike.

    Raises SearcherError when the CLI run fails; a run that found no review is
    a BikeReview with an empty `ref` and sources_used 0, not an error.
    """
    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")
    user_message = f"Find reviews for: {company} {model}"

    t = time.perf_counter()
    try:
        # Blocking subprocess → worker thread, so /health keeps answering meanwhile.
        data = await asyncio.to_thread(run_structured, system_prompt, user_message, REVIEW_SCHEMA)
    except ClaudeCliError as exc:
        raise SearcherError(str(exc)) from exc
    elapsed = time.perf_counter() - t

    review = build_review(data)
    per_source = data.get("per_source") if isinstance(data, dict) else None
    logger.info(
        "review search done | company=%r model=%r per_source=%d ref=%d rating=%.1f sources_used=%d elapsed=%.2fs",
        company, model, len(per_source) if isinstance(per_source, list) else 0,
        len(review.ref), review.rating, review.sources_used, elapsed,
    )
    if not review.ref or review.sources_used < 1:
        logger.warning("no usable review found | company=%r model=%r", company, model)
    return review
