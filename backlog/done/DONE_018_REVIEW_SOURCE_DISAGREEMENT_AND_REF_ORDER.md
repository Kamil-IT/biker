# TODO-018 — Review rating: source-disagreement rule + `ref` priority ordering

## Goal

Close the two gaps between the curated review-source guide and what `/v1/bike/review`
actually does. Everything else in the guide already shipped with TODO-014.

**Depends on:** TODO-014 (PR #47) being merged. This builds directly on its aggregation code.

## Background — why this file carries the guide inline

The research for this came from TODO-013. Its PR (#46) added
`backend/docs/review_sources.md` but was **closed rather than merged**, so that document
does not exist in the repo. The parts needed to implement and review this task are
reproduced below so nothing depends on a closed PR.

### Curated sources and tiers

| Tier | Class | Sources | Weight |
|---|---|---|---|
| 1 | Pro magazine, publishes a numeric score | `bikeradar.com`, `cyclingweekly.com`, `bikeperfect.com` | **3×** |
| 2 | Pro editorial, qualitative verdict | `pinkbike.com`, `bikemag.com`, `gcn.com` | **2×** |
| 3 | Community sentiment | `mtbr.com`, `reddit.com`, `forumrowerowe.org` / `bikestats.pl` | **1×** |

Excluded: `escapecollective.com` (paywalled — reputation context only),
`velominati.com` (cycling culture, not product testing), small regional PL forums (too thin per model).

Already implemented by TODO-014 and **not** in scope here: the tier list itself, the
3×/2×/1× weights, normalisation to 0–10, coverage routing (MTB → Pinkbike/BikePerfect/MTBR;
road & gravel → BikeRadar/Cycling Weekly/GCN), the exclusions, and requiring at least one
Tier 1/2 source before emitting a non-zero rating.

## Scope — the two gaps

### 1. Source-disagreement rule

The guide's rule, currently unimplemented:

> If sources disagree by more than ~3 points, prefer the Tier 1 number and note the
> spread in the explanation rather than averaging blindly.

Today the aggregation takes a straight weighted mean. So a `9` from BikeRadar and a `4`
from a Reddit thread silently average to something in the middle, and the reader is never
told the sources disagreed. A genuinely divisive bike reads identically to a
universally-mediocre one — the number hides the very thing a buyer needs to know.

Required behaviour when the spread between the highest and lowest normalised per-source
score exceeds the threshold:

- Anchor the emitted `rating` to the **Tier 1** score rather than the weighted mean.
  If there is no Tier 1 source, fall back to Tier 2; if neither, keep current behaviour.
- Surface the disagreement in `explanation` — state the spread and what the camps say,
  rather than silently smoothing it.
- Do **not** change `sources_used`; all consulted sources still count.

Make the threshold a named module-level constant, not a literal buried in a comparison.

### 2. `ref` ordering

The guide asks for `ref` in priority order, best professional source first. It is currently
unverified — check whether ordering is incidental (whatever order the model emitted) or
guaranteed. If incidental, sort by tier (1 → 2 → 3) before returning.

This is user-visible: the frontend renders `ref` as the source table (PR #38) and citation
chips (PR #40), so whatever lands first in the array is what a reader sees first. A Reddit
thread appearing above BikeRadar is a real quality signal being thrown away.

## Files likely involved

- `backend/app/bike_review_finder.py` — aggregation, ordering, threshold constant
- `backend/app/prompts/bike_review.md` — if the model must report per-source scores for the spread to be computable
- `backend/scripts/test_review.py` — assertions below
- `backend/README.md` · `CLAUDE.md` — document the disagreement behaviour if it changes the response's meaning

## Acceptance criteria

- [ ] Spread > threshold with a Tier 1 source present → `rating` anchors to the Tier 1 score, not the weighted mean
- [ ] The `explanation` states the disagreement and the spread
- [ ] Spread ≤ threshold → behaviour unchanged from TODO-014 (no regression)
- [ ] No Tier 1 source present → documented, deliberate fallback; not a crash and not a silent zero
- [ ] `ref` is ordered Tier 1 → Tier 2 → Tier 3
- [ ] Threshold is a named constant
- [ ] Smoke tests in `test_review.py` cover both the agreeing and disagreeing paths

## Testing notes — read before starting

Assertions here must be able to **fail**. TODO-014 shipped an endpoint that returned
all-zeros for every uncached bike while its own smoke test passed, because the test asserted
`rating in [0, 10]` and `0.0` satisfies that. ISSUE-011 survived the same way: the test
asserted `len(names) >= 1` and merely *printed* the missing categories.

- Construct the disagreement case from **captured or synthetic per-source scores**, not by
  hunting for a real bike that happens to divide reviewers. Each uncached review is a billed
  `web_search` call, and a bike's reception is not a controllable input.
- Demonstrate the new assertion **failing against the pre-change code** and passing after.
  An assertion that passes both ways tests nothing.
- Prompt changes are invisible to the SQLite cache, which keys on request text only. Purge
  with `DELETE FROM cache WHERE endpoint = '/v1/bike/review'` by SQL — not by deleting
  `cache.db`, which a running server holds open.

## Open question

The threshold is written as "~3 points" in the research, which was a suggestion rather than
a measured value. Confirm 3.0 is sensible against real spreads before hard-coding it, and
say in the PR what evidence the final number rests on.
