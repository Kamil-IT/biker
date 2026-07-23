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
| 004 | Review star table (at bottom) | [#54](https://github.com/Kamil-IT/biker/pull/54) |
| 013 | Research review forums | [#46](https://github.com/Kamil-IT/biker/pull/46) — *closed, see below* |
| 011 | SQLite follow-up cache | [#51](https://github.com/Kamil-IT/biker/pull/51) |
| ISSUE_003 | Parse brand constraint | [#50](https://github.com/Kamil-IT/biker/pull/50) |
| 008 ⚠️ | Remove aggregate rating bar | committed directly to `main` |
| 018 | Review source disagreement + `ref` order | [#65](https://github.com/Kamil-IT/biker/pull/65) — *moved here in its own PR, ahead of merge, as requested* |

> ⚠️ **ID collision.** "Remove aggregate rating bar" was numbered **008**, which is already held by `backlog/blocked/TODO_008_ALLEGRO_API_OFFER.md`. Two different tasks now share that ID. The Allegro task is the older claimant and is referenced by PR #42's title, body and branch name, so renumbering *this* task is the cheaper fix — 019 is the next free ID. Left as-is pending a decision, since renaming someone else's task ID is not a call to make silently.

ISSUE_001 and ISSUE_002 share a PR: both added a field to the same `ParseResponse` model on branches cut from the same commit, and neither contained the other's field — whichever merged second would have silently dropped one. They were combined into #49 and PR #48 was closed.

#53 has no task file. It was unplanned repair work: PR #47 merged carrying five references to `backend/docs/review_sources.md`, a file that PR #46 would have supplied — but #46 was closed rather than merged, so those links were dead on `main`.

**013 is done, but its PR was closed rather than merged** — the only entry here of that shape. The research was completed: 13 cycling review sources evaluated, tiered, and given a weighting scheme. By the time it was reviewed, TODO-014 had already implemented all of it in code (the 9-source tier list, the 3×/2×/1× weights, normalisation to 0–10, coverage routing, exclusions), so merging a standalone document describing shipped behaviour would have created a second place to keep in sync.

Its findings live on in three places: the code in `bike_review_finder.py`, the tier table reproduced inline in `TODO_018_REVIEW_SOURCE_DISAGREEMENT_AND_REF_ORDER.md`, and branch `worktree-feature+013-research-review-forums` if the full document is ever wanted. The two recommendations #47 did *not* implement — the source-disagreement rule and `ref` priority ordering — became TODO-018 rather than being lost as prose.

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

**011 was the exact inverse, and worth knowing about.** Its tests were correct and *failing* while the code was wrong: `save_search()` / `save_bike_details()` sat after the generic cache's early return, so the follow-up tables only ever filled on a cache MISS. On a warm `cache.db` almost nothing misses, leaving them permanently empty on exactly the deployments with the most data. The tell had been visible all along — the author's own `cache.db` contained both new tables with zero rows. When a good test fails, suspect the code before the test.

**ISSUE_003 shows a third failure mode: a merge that is textually clean but semantically wrong.** Its prompt example was `"…Mam 185cm wzrostu i waze 100kg. Firma tylko Tesla" → {"brand": "Tesla"}` — correct on its own branch, where height and weight did not exist. After merging ISSUE_002 they did, and the input contains both. Keeping either side verbatim would have shipped a worked example teaching the model to *drop* height and weight whenever a brand is present. Neither side was wrong alone; the pair was. When merging prompt examples, re-read them against the merged feature set — `git` cannot see this class of conflict.

ISSUE_011 also turned out not to be a new defect at all, but an incomplete migration — the same JSON-extraction bug had already been fixed once in a shared helper (`21e969f`, `app/json_extract.py`), and the details finders were never moved onto it. See `backlog/TODO_ISSUE_012_CONSOLIDATE_JSON_EXTRACTION.md`.

## Note for open PRs

PRs opened before this folder existed rename their task file to `backlog/DONE_*.md` at the **old** path. On merge, move the file into this folder.
