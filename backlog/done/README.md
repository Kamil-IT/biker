# Completed tasks

Tasks whose PR has **merged to `main`**. Kept rather than deleted — they are the record of what was built and why.

Merged is the bar. A task with finished code and an open PR is not done and does not belong here; leave it in `backlog/` until its PR lands.

## Completed this session

| ID | Task | PR |
|---|---|---|
| 005 | Citation footnote chips | [#40](https://github.com/Kamil-IT/biker/pull/40) |
| 012 | Component prompt tests | [#45](https://github.com/Kamil-IT/biker/pull/45) |
| 014 | Bike rating field | [#47](https://github.com/Kamil-IT/biker/pull/47) |
| ISSUE_001 | Parse rider height | [#49](https://github.com/Kamil-IT/biker/pull/49) |
| ISSUE_002 | Rider weight field | [#49](https://github.com/Kamil-IT/biker/pull/49) |
| ISSUE_011 | Missing Brakes category | [#52](https://github.com/Kamil-IT/biker/pull/52) |
| — | Dangling doc links | [#53](https://github.com/Kamil-IT/biker/pull/53) |

ISSUE_001 and ISSUE_002 share a PR: both added a field to the same `ParseResponse` model on branches cut from the same commit, and neither contained the other's field — whichever merged second would have silently dropped one. They were combined into #49 and PR #48 was closed.

#53 has no task file. It was unplanned repair work: PR #47 merged carrying five references to `backend/docs/review_sources.md`, a file that PR #46 would have supplied — but #46 was closed rather than merged, so those links were dead on `main`.

## Completed earlier

| ID | Task |
|---|---|
| 001 | Merge offers list |
| 002 | Decathlon offer |
| 003 | Bike search filters |
| 015 | Category prompt tests |
| 016 | Equipment details page |
| ISSUE_004 | Search performance |

## Worth reading before writing new tasks

Three features in this batch shipped with **passing tests while being broken**, and each was caught only by exercising the real endpoint:

- **014** returned `{"score":0,"rating":0.0,"sources_used":0}` for every uncached bike. Its smoke test asserted `rating in [0,10]` — and `0.0` satisfies that.
- **ISSUE_011** — 14 of 16 bikes silently lost their Brakes category. The test asserted `len(names) >= 1` and merely *printed* which categories were missing.
- **007** (still open) returns zero offers for a live Trek Marlin 5. Its test uses that exact bike and only asserts `isinstance(offers, list)` — an empty list skips every downstream assertion.

The shared lesson: **an assertion that cannot fail is not a test.** When adding one, demonstrate it failing against the unfixed code before trusting it.

ISSUE_011 also turned out not to be a new defect at all, but an incomplete migration — the same JSON-extraction bug had already been fixed once in a shared helper (`21e969f`, `app/json_extract.py`), and the details finders were never moved onto it. See `backlog/TODO_ISSUE_012_CONSOLIDATE_JSON_EXTRACTION.md`.

## Note for open PRs

PRs opened before this folder existed rename their task file to `backlog/DONE_*.md` at the **old** path. On merge, move the file into this folder.
