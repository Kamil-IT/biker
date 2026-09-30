# TODO-038 — Searcher: a used-up Claude subscription is a 400, not a 502

## Goal

When the searcher's `claude -p` run fails because the Claude subscription limit is used up, the frontend must get
the **same** answer it already gets when the Anthropic API key has no credit (PR #114, commit `d682dab`: the
app-wide `anthropic.BadRequestError` handler in `backend/app/main.py` → HTTP **400** `{"detail": <Anthropic's message>}`).

Today the limit surfaces as searcher 502 `"claude CLI failed: exit 1"` → backend 502, which reads as a bug rather than
"try again later". The CLI's real output on a limit (observed): exit 1, the JSON result has `is_error: true`,
`api_error_status: 429`, `result` = `"You've hit your session limit · resets 1am (Europe/Warsaw)"`.

## Decision

- A limit is a **400 carrying the CLI's own notice**, end to end — not 502 (failed) and not 503 (busy).
- The searcher's validation errors stay **422**, so a searcher 400 is unambiguous.
- Frontend: no change. The on-demand buttons already throw on a non-OK answer and become clickable again.

## Contract

| Layer | On a used-up subscription |
|---|---|
| `searcher/app/claude_cli.py` | `run_structured` raises `ClaudeCliLimitError(ClaudeCliError)` whose `str()` is the notice |
| searcher finders | `searcher_error(exc)` → `SearcherLimitError(SearcherError)` |
| searcher routes (olx, decathlon, allegro, photos, review) | **400** `{"detail": <notice>}` via `main._search_failed` |
| `backend/app/searcher_client.py` | searcher 400 → `SearcherLimitReached(detail)`; single-flight waiters get the same exception |
| backend `/v1/bike/{used,decathlon,allegro,photos,review}/search` | **400** `{"detail": <searcher's detail>}` via the app-wide handler `searcher_limit_reached` |

**Detection rule** (`claude_cli.limit_message`): the CLI's JSON result has `is_error: true` **and** either
- its `result` text matches the CLI's limit wording — `You've hit/reached your … limit` (ASCII or curly apostrophe,
  ≤ 40 chars between "your" and "limit", no sentence break) or `usage|session|weekly|daily|5-hour|opus|sonnet limit
  reached` — relayed whitespace-collapsed, `sk-ant-…` redacted, cut to 300 chars; or
- `api_error_status == 429` — relayed as the fixed `"Claude subscription usage limit reached"`.

Anything else (another API status, non-JSON output, timeout, missing `structured_output`) stays a plain
`ClaudeCliError` → 502. The check runs before the exit-code check, because a limit exits 1.

## Acceptance criteria

- [x] A fake CLI result with the limit → `ClaudeCliLimitError`; a generic error → plain `ClaudeCliError`
      (`searcher/scripts/test_cli_limit.py`)
- [x] Every searcher CLI route answers 400 `{"detail": notice}` for a limit and still 502 for other CLI failures
- [x] Backend: a searcher 400 → `SearcherLimitReached`; joined waiters share it; all five `/v1/bike/*/search` routes
      answer 400 with the searcher's detail (`backend/scripts/test_searcher_client_limit.py`)
- [x] Docs: `backend/README.md`, `searcher/README.md`, `CLAUDE.md`, `README.md`
