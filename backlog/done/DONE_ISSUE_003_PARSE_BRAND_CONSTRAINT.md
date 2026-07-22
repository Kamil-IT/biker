# ISSUE-003 — Brand constraint not extracted from free text

## Problem
A brand stated in free text is not populated into the **Brand** filter.

**Repro:** search
> "Szukam roweru na pordóże po wrocławiu na wałach... Mam 185cm wzrostu i waze 100kg. **Firma tylko tesla**"

Expected: `brand = "Tesla"` populated. Actual: brand stays empty.

## Root cause
`app/prompts/bike_parse.md` lists `brand` but all examples are real bike makers ("Trek", "Canyon"…) and the prompt does not cover the Polish constraint phrasing *"Firma tylko X"* / *"marka X"*. The Haiku call (`app/bike_parser.py`) therefore returns no brand. (See also ISSUE-005 — "Tesla" is not a real bike brand, so even when extracted, the search must handle a brand with no matching bikes gracefully.)

## Proposed fix
- Extend `bike_parse.md` to recognise brand-constraint phrasings in Polish and English ("Firma tylko X", "marka X", "tylko X", "brand X only") and map to `brand`.
- Add an example: "Firma tylko Tesla" → `{"brand": "Tesla"}`.
- Verify `App.tsx` already merges `parsed.brand` (it does, ~L87) — no change expected there.

## Acceptance criteria
- [ ] The repro prompt populates Brand = "Tesla" (casing preserved).
- [ ] Works for "marka Trek", "tylko Specialized".
- [ ] Does not over-extract brand from unrelated proper nouns (e.g. city "Wrocław").
