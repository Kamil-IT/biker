# ISSUE 012 — Consolidate JSON extraction onto the shared `json_extract.extract_json()`

## The bug class

Every prompt in this repo asks the model for "ONE valid JSON object and nothing
else". The model does not reliably comply — it routinely opens with a line of
narration and wraps the object in a fence:

```
I'll search for the brake specifications of the Trek Marlin 5 bicycle.

```json
{"category":"Brakes","subcategories":[ ... ]}
```
```

Two distinct ways a private helper mishandles this:

1. **Silent truncation.** The anchored `^```...```$` regex does not match text
   that starts with prose, so a `text[: text.index("```")]` fallback truncates at
   the **opening** fence and keeps only the preamble. `json.loads()` then fails
   and the payload is dropped. This is what caused ISSUE 011 (Brakes missing on
   14 of 16 bikes).
2. **Regex-only, no fallback.** `return m.group(1).strip() if m else text` —
   returns the prose unchanged, `json.loads()` fails, result discarded. No
   truncation, but the same data loss.

Both degrade **silently**: a logged warning and an empty result. Nothing raises,
so a caller cannot tell "the model had no data" from "we threw the data away".

## Intended single implementation

`backend/app/json_extract.py` → `extract_json(text) -> dict | list | None`.
Tries fenced blocks, then the whole text, then the last balanced `{...}` / `[...]`
found in prose, ignoring braces inside strings. Returns `None` only when the
response genuinely carries no JSON.

Commit `21e969f` established this helper while fixing the four offer endpoints.
**The migration was never finished** — that is the actual root cause of ISSUE
011. The details finders were left on a private copy and nobody noticed for
weeks. This task is to finish the job so the same gap cannot recur.

## Call-site inventory

Produced by grepping `backend/app` for `_strip_code_fence`, `code_fence`,
`CODE_FENCE`, `index("```")` and `from .json_extract import`.
State assumes **both PR #47 and PR #52 have landed**.

### On the shared helper — done, no action (6)

| File | Migrated by |
|---|---|
| `app/bike_offer_finder.py` | `21e969f` |
| `app/bike_offer_ceneo_finder.py` | `21e969f` |
| `app/bike_offer_decathlon_finder.py` | `21e969f` |
| `app/bike_used_finder.py` | `21e969f` |
| `app/bike_details_finder.py` | PR #52 (ISSUE 011) |
| `app/equipment_details_finder.py` | PR #52 (ISSUE 011) |

### Private implementations — to migrate (5)

| File | Own extractor | Failure mode | Risk |
|---|---|---|---|
| `app/bike_review_finder.py` | `_extract_json_object()` **plus** a retained `_strip_code_fence` (`:65`, `:75` on PR #47's branch) | prose-tolerant after #47 | **Low** — correct, but a 2nd implementation of the same logic |
| `app/equipment_review_finder.py` | `_find_json_object()` + `_FENCED_JSON` regex (`:18`, `:21`) | prose-tolerant | **Low** — correct, but a 3rd implementation |
| `app/anthropic_scorer.py` | `_strip_code_fence` (`:17`), regex-only | preamble → parse fails → retries once → returns an **error CategoryResult** (`:40-44`) | **Medium** — a narrated response silently zeroes a category's relevance score |
| `app/bike_finder.py` | `_strip_code_fence` (`:26`), regex-only | preamble → parse fails → retries once → returns **`[]`** (`:96-100`) | **Medium** — a narrated response silently yields zero bikes for that category |
| `app/bike_parser.py` | `_strip_code_fence` (`:19`), regex-only | preamble → parse fails (`:36`) | **Medium** — free-text parse silently degrades |

**Net after #47 and #52: four independent implementations of one behaviour.**

The three regex-only copies (`anthropic_scorer`, `bike_finder`, `bike_parser`)
are the ones that still carry live risk. Their single retry masks the problem
rather than fixing it — the details finder had `web_search` disabled and still
got preambles, so "no tools" is not protection. Note `/v1/bike/search` depends
on all three, and a silently-zeroed category there looks exactly like "no
matching bikes" — the same indistinguishable-from-real-data failure that let
ISSUE 011 survive.

## Proposed work

1. Migrate the three regex-only call sites first — they carry live risk:
   `anthropic_scorer.py`, `bike_finder.py`, `bike_parser.py`.
2. Then fold `bike_review_finder.py` and `equipment_review_finder.py` onto the
   shared helper and delete their private extractors. **Do this only after PR
   #47 has merged** — do not invalidate its verified testing by editing it in
   flight.
3. Delete every remaining `_strip_code_fence` / `_CODE_FENCE` from
   `backend/app`; afterwards `grep -rn "_strip_code_fence\|CODE_FENCE" app/`
   should return nothing.
4. Add a regression test asserting `extract_json` handles: preamble + fence,
   bare JSON, fence only, preamble without fence, trailing prose, a top-level
   list, braces inside strings, and genuinely-absent JSON (→ `None`).
5. Consider making the "no JSON found" path louder than a warning — every
   incarnation of this bug survived because the failure was indistinguishable
   from a legitimately empty result.

## Related

- ISSUE 011 (`DONE_ISSUE_011_MISSING_BRAKES_CATEGORY.md`) — the Brakes symptom
- `21e969f` — introduced `json_extract.py`, migrated the offer endpoints
- PR #52 — migrated the two details finders
- PR #47 — fixes `bike_review_finder` with its own extractor
