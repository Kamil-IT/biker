# TODO-015 — Category-Scoring Prompt Tests

## Goal
Add tests validating the category-scoring prompts (`app/prompts/<category>.md`) driven by `anthropic_scorer.py`, beyond the existing HTTP smoke test.

## Behaviour
- For representative queries, assert Phase-1 scoring behaves sensibly:
  - obvious queries map to the right top category (e.g. "29 inch trail bike with suspension" → Mountain (MTB) scores high; "daily city commute, paved roads" → Hybrid/Commuter or Road high),
  - every score is an int in 0–10,
  - malformed model output degrades to `score 0` with a `"Parse error …"` explanation (NOT an empty list) and never a 502 — this is what `anthropic_scorer.score_category` actually does (it catches the parse error after one retry; the endpoint's 502 only fires on a raised upstream/API exception),
  - all 11 categories are scored (guaranteed by construction: `main.py` loops all 11 and the scorer never raises on bad JSON).
- Treat as directional/threshold assertions (allow variance), not exact scores.

## Scope
- `backend/scripts/` — new `test_scoring.py` (or extend `test_search.py`) calling the scorer / search and asserting category ordering for a few canonical queries.
- No app change unless a prompt bug surfaces.

## Open questions / Notes — RESOLVED
- Acceptable to assert "expected category in top N" rather than exact #1? → **Yes, per-query**: 6 unambiguous queries demand top-1; 5 overlapping ones allow top-2. Tagged individually in `DATASET`.
- Which canonical query set to standardise on? → 11 canonical queries in `test_scoring.py::DATASET`, one per category.

## Resolution
Implemented in `backend/scripts/test_scoring.py` (pytest), two tiers:
- **Deterministic** (`-m "not llm"`, no API key): mocks the client to test JSON parsing, range, and graceful score-0-on-parse-error.
- **Live eval** (`@pytest.mark.llm`, no API key): scores 11 queries × 11 categories via the **`claude` CLI** (subscription OAuth, prod model Haiku 4.5) and asserts per-query top-N rank + aggregate top-1/top-2/MRR.

Result of the live run: **all 11 per-query rank tests pass**; deterministic tier passes. See `backend/README.md` → "Category-Scoring Prompt Eval" for how to run.

## Acceptance criteria
- [x] ≥3 canonical queries assert the expected category in top results. (11 queries, all passing)
- [x] Asserts score range (0–10) + all 11 categories scored.
- [x] Asserts graceful parse-error handling (score 0 + "Parse error", never 502).
