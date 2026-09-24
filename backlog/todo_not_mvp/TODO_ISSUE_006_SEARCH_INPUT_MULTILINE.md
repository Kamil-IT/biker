# ISSUE-006 — Search input does not grow with multi-line text

## Problem
As the user types a long query, the search box does not expand. Text scrolls within a single line instead of wrapping; new lines are not visible. The field should auto-grow vertically as content is added.

## Root cause
The main search field is a single-line `<input type="text">` in `frontend/src/components/SearchInput.tsx` (~L98-118). It also handles Enter via `handleKeyDown` to submit, so it cannot wrap.

## Proposed fix
- Replace the `<input>` with an auto-growing `<textarea>` (e.g. set `rows={1}` and adjust `height` to `scrollHeight` on input, or use `field-sizing: content`).
- Keep submit on **Enter**, allow **Shift+Enter** for a newline (update `handleKeyDown`).
- Preserve current styling (icon padding, focus ring, disabled state) and the `value`/`onChange` contract so `App.tsx` is unaffected.

## Acceptance criteria
- [ ] Typing a long/multi-line query grows the box and shows all text.
- [ ] Enter submits; Shift+Enter inserts a newline.
- [ ] Styling matches the rest of the form; no layout shift on the hero.
