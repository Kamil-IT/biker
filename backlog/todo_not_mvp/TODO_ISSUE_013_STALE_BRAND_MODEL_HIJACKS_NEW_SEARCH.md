# ISSUE-013 — A second search still returns the first bike (stale parsed brand/model)

## Problem
1. Type `INDIANA X-Pulser` in the search box → search runs, results for X-Pulser.
2. Clear the box, type `INDIANA X-Cross 2.0 D17` → search runs, but the results are **still for X-Pulser** (or for whatever the first query was).

The new free text is effectively ignored: the app keeps searching for the previous bike.

## Root cause
Two effects compound, both in `frontend/src/App.tsx` `handleSearch` (~L76-132):

1. **Parsed filters are sticky.** The first free-text-only submit calls `POST /v1/bike/parse`, merges the result into `filters` (`brand: "INDIANA"`, `model: "X-Pulser"`), opens the filters panel and `return`s so the user can review. Those values stay in `filters` afterwards — nothing clears them when the free text is edited (same additive-merge flaw as [ISSUE-007](TODO_ISSUE_007_RESYNC_FILTERS_ON_EDIT.md), but here it changes *which bike is searched*, not just a checkbox).

2. **Stale filters suppress the re-parse.** On the next submit `SearchInput.buildPayload()` (`SearchInput.tsx` L52-75) includes the still-populated `brand`/`model`, so `hasStructured` is `true` at `App.tsx:78` and the `if (payload.search && !hasStructured)` parse branch is skipped entirely. The new text is never parsed, and the request goes out as
   `{ search: "INDIANA X-Cross 2.0 D17", brand: "INDIANA", model: "X-Pulser" }`.

3. **The backend then short-circuits on the stale pair.** With both `brand` and `model` present, `POST /v1/bike/search` takes the DB-first branch (`repository.find_bike_by_brand_model`) and returns the cached **X-Pulser** row without any AI call — so the free text has zero influence and the wrong result is returned instantly. Even without a DB hit, `SearchRequest.enriched_query()` prefixes `Brand: INDIANA, Model: X-Pulser` to the query, biasing the AI pipeline toward the old bike.

## Reproduction
- Frontend on :5173, backend on :8000.
- Search `INDIANA X-Pulser`, confirm the filters panel opens with Brand/Model filled, submit again → X-Pulser results.
- Replace the free text with `INDIANA X-Cross 2.0 D17`, submit → Brand/Model still show `INDIANA` / `X-Pulser`; results are X-Pulser.
- Network tab: the `/v1/bike/search` body carries the old `brand`/`model`; `/v1/bike/parse` is never called for the second query.

## Proposed fix
Free text the user has edited must win over previously auto-parsed fields. Options (pick one, consistent with ISSUE-007):

- **A (recommended) — track parse ownership.** Remember which filter fields were populated by `/v1/bike/parse` and the exact text they were parsed from. When the free text changes, clear the parse-owned fields (and re-parse on submit). User-typed filters are untouched.
- **B — re-parse whenever the text changed.** Store `lastParsedText`; if `payload.search !== lastParsedText`, run the parse branch regardless of `hasStructured`, and reconcile (not merge) the returned fields.

Either way the second submit must send brand/model matching the *current* text, or none at all.

## Acceptance criteria
- [ ] Searching `INDIANA X-Pulser`, then `INDIANA X-Cross 2.0 D17`, returns X-Cross results.
- [ ] After editing the free text, the Brand/Model filter inputs no longer show values parsed from the previous text.
- [ ] Filters the user typed by hand are not wiped by a free-text edit.
- [ ] `/v1/bike/search` is never sent a `brand`/`model` pair that came from an earlier, since-replaced query.
- [ ] Regression test covering the two-searches-in-a-row sequence.

## Related
- `TODO_ISSUE_007_RESYNC_FILTERS_ON_EDIT.md` — same additive-merge root cause, boolean filters. Fixing both together is sensible.
- `TODO_ISSUE_009_RESULTS_FOR_SPLIT_FILTER_FREETEXT.md` — free text vs. structured fields interaction.
