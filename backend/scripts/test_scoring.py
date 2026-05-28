"""Category-scoring prompt eval (TODO-015).

Two tiers:

  1. DETERMINISTIC (default, no model, free) — pure-Python tests of the scorer's
     JSON parsing and graceful-degradation contract. Run on every commit.

         cd backend
         pytest scripts/test_scoring.py -m "not llm"

  2. LIVE EVAL  (@pytest.mark.llm, slow, run nightly/pre-release) — a full-dataset
     eval that scores every canonical query against all 11 category prompts using
     the *prod* model (Claude Haiku 4.5) and asserts the right category ranks
     highest. This tier needs NO ANTHROPIC_API_KEY: it shells out to the `claude`
     CLI, which authenticates via your subscription login.

         cd backend
         pytest scripts/test_scoring.py -m llm -s        # -s shows the metrics report

     Prerequisites for the live tier:
       - `claude` CLI installed and logged in (`claude` once, then /login).
       - Costs ~121 CLI calls (11 queries x 11 categories); takes several minutes.
       - If `claude` is not on PATH the live tests SKIP (they never hard-fail CI).

What it verifies (TODO-015 acceptance criteria):
  - >=3 canonical queries rank the expected category within its allowed top-N.
  - every score is an int in 0-10; all 11 categories are scored per query.
  - malformed model output degrades to score 0 + a "Parse error" explanation
    (NOT an empty list, NOT a 502 — that is what anthropic_scorer.py actually does).
"""

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# anthropic_scorer constructs AsyncAnthropic() at import time, which needs a key
# present (it is never used here — we monkeypatch or shell to the CLI). Set a dummy
# BEFORE importing the app package.
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test-dummy")

# Make the `app` package importable regardless of the current working directory.
BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.anthropic_scorer import MODEL, score_category, _strip_code_fence  # noqa: E402
from app.categories import BIKE_CATEGORIES, CATEGORY_PROMPTS  # noqa: E402

# ── Canonical dataset: (query, expected category, max acceptable rank) ──────────
# Unambiguous queries demand top-1; genuinely overlapping ones allow top-2.
# Category names must match app/categories.py exactly.
DATASET: list[tuple[str, str, int]] = [
    ("29 inch trail bike with full suspension for singletrack",            "Mountain (MTB)",     1),
    ("fast carbon bike for road racing on tarmac",                         "Road",               1),
    ("foldable bike for the train commute, compact for storage",           "Folding",            1),
    ("kids bike for a 6 year old, 20 inch wheels",                         "Kids",               1),
    ("bmx bike for skatepark tricks and jumps",                            "BMX",                1),
    ("beach cruiser, single speed, relaxed upright riding",                "Cruiser",            1),
    ("comfortable bike for a daily 10 km city commute on paved roads",     "Hybrid / Commuter",  2),
    ("mixed-terrain bike for gravel paths and bikepacking",                "Gravel",             2),
    ("long-distance loaded touring bike with racks and panniers",          "Touring",            2),
    ("electric bike with a 500 Wh battery for a hilly commute",            "Electric (e-bike)",  2),
    ("cyclocross race bike with knobby tires for muddy circuit racing",    "Cyclocross",         2),
]

CLI_TIMEOUT = 180
_CLAUDE = shutil.which("claude")


# ── Deterministic tier: parsing / graceful-degradation (no model call) ──────────

class _FakeText:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.content = [_FakeText(text)]


def _patch_model_output(monkeypatch, text: str) -> None:
    """Make every messages.create() call return `text` as the model's reply."""
    from app import anthropic_scorer as scorer

    async def _fake_create(**_kwargs):
        return _FakeResp(text)

    monkeypatch.setattr(scorer._client.messages, "create", _fake_create)


def test_malformed_output_degrades_to_score_zero(monkeypatch):
    _patch_model_output(monkeypatch, "this is not json at all")
    result = asyncio.run(score_category("any query", "Road", "system prompt"))
    assert result.score == 0
    assert result.explanation.startswith("Parse error")


def test_missing_score_key_degrades_to_score_zero(monkeypatch):
    _patch_model_output(monkeypatch, '{"explanation": "no score field here"}')
    result = asyncio.run(score_category("any query", "Gravel", "system prompt"))
    assert result.score == 0


def test_valid_output_parses_score_in_range(monkeypatch):
    _patch_model_output(monkeypatch, '{"score": 8, "explanation": "strong match"}')
    result = asyncio.run(score_category("any query", "Road", "system prompt"))
    assert result.score == 8
    assert 0 <= result.score <= 10


def test_code_fenced_output_is_parsed(monkeypatch):
    _patch_model_output(monkeypatch, '```json\n{"score": 5, "explanation": "partial"}\n```')
    result = asyncio.run(score_category("any query", "Touring", "system prompt"))
    assert result.score == 5


# ── Live eval tier: real prompts via the `claude` CLI (no API key) ──────────────

def _clamp(value: int) -> int | None:
    return value if 0 <= value <= 10 else None


def _parse_score(text: str) -> int | None:
    """Extract the 0-10 score from a model reply.

    The prod scorer gets strict JSON from the raw API, but the `claude` CLI is an
    agent harness that tends to answer in prose ("## Score: 9/10 ..."), so we try,
    in order: a JSON object, an embedded `score: N`, then an `N/10` rating.
    """
    cleaned = _strip_code_fence(text.strip())
    for candidate in (cleaned, _first_json_object(cleaned)):
        if candidate:
            try:
                return _clamp(int(json.loads(candidate)["score"]))
            except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                pass
    m = re.search(r'"?score"?\s*[:=]\s*(\d{1,2})', text, re.IGNORECASE)
    if m:
        return _clamp(int(m.group(1)))
    m = re.search(r"(\d{1,2})\s*/\s*10", text)
    if m:
        return _clamp(int(m.group(1)))
    return None


def _first_json_object(text: str) -> str | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else None


def _score_via_cli(query: str, system_prompt: str) -> int | None:
    """Score one (query, category) using the prod model via the Claude CLI.

    `--system-prompt` fully replaces the default agent prompt with the category
    scoring prompt (matching prod, where it is passed as `system=`); `--tools ""`
    disables all tools (the prod scorer uses none).
    """
    # Strip the dummy ANTHROPIC_API_KEY (set above so anthropic_scorer can import)
    # so the CLI authenticates via the subscription OAuth login, not a fake key.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    proc = subprocess.run(
        [
            _CLAUDE, "-p", query,
            "--system-prompt", system_prompt,
            "--tools", "",
            "--exclude-dynamic-system-prompt-sections",
            "--model", MODEL,
            "--output-format", "json",
        ],
        stdin=subprocess.DEVNULL, env=env,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=CLI_TIMEOUT,
    )
    if proc.returncode != 0:
        return None
    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    return _parse_score(str(envelope.get("result", "")))


def _ranked(scores: dict[str, int | None]) -> list[str]:
    """Category names sorted by score descending; unscored (None) sink to the bottom."""
    return [
        name for name, _ in sorted(
            scores.items(),
            key=lambda kv: (kv[1] if kv[1] is not None else -1),
            reverse=True,
        )
    ]


@pytest.fixture(scope="session")
def eval_scores() -> dict[str, dict[str, int | None]]:
    """Score the whole dataset once (query -> {category -> score}). Shared by all live tests."""
    if _CLAUDE is None:
        pytest.skip("`claude` CLI not found on PATH — live eval skipped")
    out: dict[str, dict[str, int | None]] = {}
    for query, _expected, _rank in DATASET:
        out[query] = {
            name: _score_via_cli(query, CATEGORY_PROMPTS[name])
            for name, _slug in BIKE_CATEGORIES
        }
    return out


@pytest.mark.llm
@pytest.mark.parametrize(
    "query,expected,max_rank", DATASET, ids=[d[1] for d in DATASET]
)
def test_canonical_query_ranks_expected_category(eval_scores, query, expected, max_rank):
    scores = eval_scores[query]
    assert len(scores) == 11, "all 11 categories must be scored"
    for name, value in scores.items():
        if value is not None:
            assert 0 <= value <= 10, f"{name} score {value} out of 0-10 range"
    assert scores[expected] is not None, (
        f"expected category {expected!r} produced no parseable score for {query!r}"
    )
    rank = _ranked(scores).index(expected) + 1
    assert rank <= max_rank, (
        f"{expected!r} ranked #{rank} for {query!r}; expected top-{max_rank}. "
        f"Scores: {scores}"
    )


@pytest.mark.llm
def test_aggregate_metrics(eval_scores):
    n = len(DATASET)
    top1 = top2 = 0
    reciprocal_rank = 0.0
    rows = []
    for query, expected, _max_rank in DATASET:
        rank = _ranked(eval_scores[query]).index(expected) + 1
        top1 += rank == 1
        top2 += rank <= 2
        reciprocal_rank += 1.0 / rank
        rows.append((expected, rank, _ranked(eval_scores[query])[0]))

    top1_acc, top2_acc, mrr = top1 / n, top2 / n, reciprocal_rank / n
    # ASCII only: -s sends this to the real console, which is cp1252 on Windows.
    print("\n== Category-scoring prompt eval ==")
    print(f"{'expected':<20} {'rank':>4}  winner")
    for expected, rank, winner in rows:
        print(f"{expected:<20} {rank:>4}  {winner}")
    print(f"\nTop-1 accuracy: {top1_acc:.2f}  Top-2 accuracy: {top2_acc:.2f}  MRR: {mrr:.2f}")

    # The per-query tests are the hard gates; this is a loose trend guard. The
    # dataset deliberately includes 5 overlapping queries allowed to land at #2,
    # so top-1 can be as low as 6/11 by design.
    assert top1_acc >= 0.50, f"top-1 accuracy {top1_acc:.2f} below 0.50"
    assert top2_acc >= 0.85, f"top-2 accuracy {top2_acc:.2f} below 0.85"
    assert mrr >= 0.70, f"MRR {mrr:.2f} below 0.70"
