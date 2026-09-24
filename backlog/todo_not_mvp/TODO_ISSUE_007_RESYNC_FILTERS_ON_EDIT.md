# ISSUE-007 — Editing free text does not re-sync filter checkboxes (electric)

## Problem
If the query first describes an electric bike (so the **Electric** checkbox gets set), then the user edits the text to remove the electric mention, the checkbox stays checked. Removing info from the query should clear the corresponding filter.

## Root cause
The parse-merge in `frontend/src/App.tsx` (`handleSearch`, ~L84-94) is **additive only**: it spreads parsed fields onto existing `filters` and never clears a field that is no longer present. Booleans like `is_electric` set on a previous parse persist. There is also no re-parse when the text is edited — merge only runs on submit of a free-text-only query.

## Proposed fix (confirm desired UX before implementing)
Decide the reconciliation model, then implement consistently:
- **Option A (reconcile on parse):** when re-parsing free text, explicitly set fields the parser did *not* return back to `EMPTY_FILTERS` defaults (clear `is_electric` to `undefined` when absent), rather than leaving stale values.
- **Option B (explicit ownership):** track which filters were auto-populated by parse vs. set by the user; only auto-clear the parse-owned ones.

Whichever is chosen, ensure the `is_electric` checkbox (`SearchInput.tsx` ~L262) reflects the latest parse, and the dependent Battery field hides when electric is cleared.

## Acceptance criteria
- [ ] Removing the electric mention and re-running unsets the Electric checkbox.
- [ ] User-set filters are not unexpectedly wiped (per chosen option).
- [ ] Battery-capacity field hides when electric becomes unset.
