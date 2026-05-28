# TODO-013 — Research Cycling Review Forums / Sources

## Goal
Produce a curated, documented list of cycling review sources (forums, magazines, communities) to feed the review prompt and the rating field (TODO-014). Research-only.

## Behaviour / Deliverable
- Evaluate and document, per source:
  - name, domain, type (pro magazine / forum / community),
  - coverage (road / MTB / gravel / e-bike),
  - language, whether reviews carry a numeric score,
  - reliability / quality notes.
- Candidate sources (extend): BikeRadar, MTBR, Reddit r/cycling & r/MTB, Velominati, Pinkbike, CyclingTips / Escape Collective, GCN, bikemagazine, Polish rowerowe forums.
- Recommend a final source allowlist + how to weight sources for an aggregate rating.

## Scope
- New doc: `backend/docs/review_sources.md`.
- May inform `app/prompts/bike_review.md` (note suggested edits; don't necessarily change the prompt here).

## Acceptance criteria
- [ ] Doc lists ≥8 sources with the attributes above.
- [ ] Final recommended allowlist + weighting suggestion.
- [ ] Output feeds TODO-014.
