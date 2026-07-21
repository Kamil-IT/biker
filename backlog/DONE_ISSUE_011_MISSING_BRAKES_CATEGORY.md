# ISSUE 011 — `/v1/bike/details` almost never returns a Brakes category

## Symptom

`POST /v1/bike/details` silently omits the **Brakes** component category for
nearly every bike. Across all cached `/v1/bike/details` rows, **14 of 16 bikes
had no Brakes category at all** — only `electra / townie 7d` and `trek / fx 3 disc`
had one.

This is not a web-data gap. A Trek Marlin 5 has Tektro/Shimano hydraulic disc
brakes published on Trek's own spec page, and the bike's own accessory chips in
the UI already read "Hydraulic disc brakes".

Other categories were dropped the same way, just less often — e.g. Canyon Grizl
CF 7 ESC was missing both **Brakes** and **Lighting** (6 of 8 categories).

## Root cause

`_strip_code_fence()` in `backend/app/bike_details_finder.py`, not the prompt.

The model reliably answers with a line of narration *before* the JSON:

```
I'll search for the brake specifications of the Trek Marlin 5 bicycle.

```json
{"category":"Brakes","subcategories":[ ... ]}
```
```

The anchored fence regex (`^``` ... ```$`) does not match, because the text
starts with prose. Execution then falls into the fallback:

```python
if "```" in text:
    text = text[:text.index("```")].strip()
```

...which truncates at the **opening** fence marker and keeps only the preamble.
`json.loads()` then fails, the category is logged and skipped, and the brakes
data — which the model had already produced correctly — is thrown away.

`backend/app/equipment_details_finder.py` carried a byte-for-byte copy of the
same helper. Worse there: it searches a single category, so a preamble empties
the entire component tree.

Commit `21e969f` had already fixed this exact bug class for the four offer
endpoints and introduced the shared `backend/app/json_extract.py` helper. The
two details finders were simply never migrated onto it.

## Fix

Migrate `bike_details_finder.py` and `equipment_details_finder.py` onto the
existing shared `extract_json()` from `app/json_extract.py`, which pulls the
first parseable fenced block or balanced `{...}` / `[...]` out of surrounding
prose. Delete the two duplicated `_strip_code_fence()` copies.

No prompt changes — the prompts were already correct and the model was already
returning correct data.

## Verification

Cold cache, both reference bikes now return 8/8 categories with real values:

- Trek Marlin 5 — Brakes: Shimano M315 levers (front/rear), Shimano SM-RT30 rotor, 160 mm
- Canyon Grizl CF 7 ESC — Brakes: SRAM Level Ultimate levers (4-piston), SRAM Centerline rotors, 160 mm

`backend/scripts/test_details.py` (PR #45) was tightened to assert a floor of
structurally universal categories (`Frame`, `Drivetrain`, `Wheels`, `Brakes`);
it fails against the unfixed code and passes against this fix.
