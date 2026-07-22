# ISSUE-004 — Search is very slow

## Problem
A search takes a long time before results appear.

## Root cause (suspected)
Two compounding costs:
1. **Phase 1 scoring is sequential.** `/v1/bike/search` scores relevance with **11 sequential** `claude-haiku-4-5-20251001` calls (one per category — see CLAUDE.md "Phase 1" and `app/anthropic_scorer.py` / `app/main.py`). That is 11 serial round-trips before any bike is found. (Phase 3 `find_all_bikes` in `app/bike_finder.py` is already parallel via `asyncio.gather`.)
2. **Free-text parse adds a round-trip + a second submit.** `App.tsx handleSearch` first POSTs `/v1/bike/parse`, then requires the user to submit again to run the search.

## Proposed fix (investigate first, confirm before implementing)
- Parallelise Phase 1 category scoring with `asyncio.gather` (cap concurrency if rate-limited). Biggest expected win.
- Consider scoring all categories in a **single** Haiku call returning an array, instead of 11 calls.
- Verify the SQLite cache (`app/cache.py`) is hit on repeat searches; warm-cache latency is the floor.
- Frontend: show progressive/streamed status; consider parsing + searching in one flow so the user submits once.

## Acceptance criteria
- [x] Cold search latency measurably reduced (record before/after for the repro prompt).
- [x] Result quality unchanged (same/similar categories selected).
- [x] Cache still hit on repeat identical search.

## Resolution (2026-05-28)
Implemented fix #1: Phase 1 category scoring is now parallel via `asyncio.gather`
in `app/main.py` (was an 11-iteration sequential `for` loop). Error semantics
preserved — any single category upstream failure still raises HTTP 502
(`return_exceptions=True` + per-result check).

Measured (repro prompt):
- Phase 1: ~13.0s → ~2.0s (the 11 serial round-trips now run concurrently).
- Total cold search: 17.8s → ~9.5–13.5s (remainder is Phase 3 `find_all_bikes`,
  already parallel and out of scope here).
- Cache hit: ~3 ms steady-state (unchanged).
- Result quality unchanged: each category is scored by its own prompt at
  `temperature=0`, so concurrency cannot alter scores or category selection.

Optional follow-ups (not done — out of scope for #1):
- #2 single-call scoring of all 11 categories (bigger win, quality risk).
- Frontend: avoid the parse round-trip + forced re-submit in `App.tsx handleSearch`.
