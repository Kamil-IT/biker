# ISSUE-014 — "Find my bike" needs two clicks: the first one only expands the filters

**Type:** bug
**Area:** frontend (`frontend/src/App.tsx`, `frontend/src/components/SearchInput.tsx`)
**Severity:** medium — every free-text search costs an extra click and looks like the button is broken

## Symptom

Type a bike name (or any free text) into the search box and click **Find my bike**. Nothing is
searched. The Filters panel expands with the extracted brand/model/year fields filled in, and the
button has to be clicked a **second** time to actually run the search.

To the user the first click reads as a dead click — the button says "Find my bike", so it should
find a bike.

## Steps to reproduce

1. `npm run dev` in `frontend/`, backend running on :8000
2. Type `Trek Marlin 5` into the main search input (leave every filter empty)
3. Click **Find my bike**
   → button flips to "Extracting fields…", then the Filters panel opens pre-filled with
     Brand `Trek`, Model `Marlin 5`. No results, no loading state.
4. Click **Find my bike** again
   → the search finally runs

## Root cause

`frontend/src/App.tsx:76-119` — `handleSearch()`. When the payload has free text and **no**
structured fields, it first calls `POST /v1/bike/parse`. If anything was extracted it populates the
filters, opens the panel, and **returns early**:

```ts
setShowFilters(true)
setIsParsing(false)
return  // let user review populated fields, then submit again
```

`frontend/src/App.tsx:112`. That early `return` is the whole bug — the parse result is never handed
on to `POST /v1/bike/search` in the same click.

## Expected behaviour

One click does both: reveal the extracted fields **and** run the search with them.

- Click **Find my bike** with free text →
  1. `/v1/bike/parse` runs, filters get populated, Filters panel opens (keep this — it is useful
     feedback showing what was understood)
  2. **without a second click**, the search continues immediately using the merged payload
     (free text + the just-extracted structured fields)
- The user sees `Extracting fields…` → `Analysing…` → results, in one uninterrupted flow.
- Editing a filter afterwards and clicking again re-runs the search normally (that path already
  works — the payload then has structured fields, so the parse step is skipped).

## Implementation notes

- Drop the early `return` at `App.tsx:112`; instead build the search body from the parsed values
  rather than from React state (`setFilters` is async — reading `filters` right after would still
  hold the old values). Something like: assemble `merged = { ...payload, ...parsedStructured }`
  and pass `merged` to the `/v1/bike/search` fetch below.
- Keep `setShowFilters(true)` so the user still sees what was extracted.
- `setIsParsing(false)` must fire before `setAppState('loading')` so the button label goes
  Extracting → Analysing rather than getting stuck.
- The parse-failed / nothing-extracted paths already fall through to a plain search — leave them.

## Acceptance criteria

- [ ] Typing `Trek Marlin 5` and clicking **Find my bike** once returns results
- [ ] The Filters panel is still open and pre-filled with `Trek` / `Marlin 5` when the results land
- [ ] The search request body includes the parsed `brand`/`model` (verify in the Network tab), not
      just the raw `search` string
- [ ] Free text that parses to nothing still searches on the first click
- [ ] A `/v1/bike/parse` failure still searches on the first click
- [ ] Searching with filters filled in manually is unchanged (no parse call)
