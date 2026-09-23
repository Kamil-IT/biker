# TODO-023 — Remove five search filters

## Goal

Remove these filters from the search form **and** from the backend:

- Rider height (cm) — `rider_height_cm`
- Rider weight (kg) — `rider_weight_kg`
- Max price (PLN) — `price_max`
- Has suspension (front or full) — `has_suspension`
- Kids bike — `is_kids`

## Decisions (agreed 2026-09-23)

1. **Scope: frontend + backend.** The fields are dropped from `SearchRequest`, `enriched_query()`, the
   generic-cache key in `main.py`, `ParseResponse`, `bike_parser.py` and the `bike_parse.md` prompt.
   Pydantic ignores unknown fields, so an old client sending them is not rejected. The only exception is a
   payload made *only* of removed fields, which now has no search field and returns 422.
2. **Parse stops extracting them.** `/v1/bike/parse` returns only `brand`, `model`, `year`, `wheel_size`,
   `is_electric`.
3. **An empty parse returns 400.** Text that mentions only removed attributes (e.g. "rower dla dziecka, mam
   130 cm") parses to nothing, so the backend returns 400 and the UI shows the "Not found" warning without
   searching. This is the existing PR #81 behaviour and is accepted as-is.
4. **Dead code removed.** The `price_max` DB-first gate is gone, and so are `store.find_offer_prices()`,
   `app/price_parse.py`, `tests/test_price_parse.py`, the old TC-23/TC-24 price-gate tests and their fixtures.
   `pytest.ini` no longer collects `tests/`.
5. **Layout.** "Electric bike (e-bike) only" stays as the only toggle in the Basic group.

## Acceptance criteria

- [x] The Filters panel shows none of the five controls (Basic: brand, model, bike type, year, wheel size,
      frame size + electric toggle).
- [x] The search payload never contains the five fields.
- [x] Free text like "Trek Marlin 7 with suspension" fills brand/model but sets no suspension flag.
- [x] Free text that mentions only height/weight/kids shows the "Not found" warning.
- [x] The backend enriched query never contains "Max price", "Rider height", "Rider weight", "Suspension" or
      "Kids bike".
- [x] `npm run build` passes, `pytest -m "not llm"` passes, and `scripts/test_search.py` is updated (TC-11,
      TC-12b, TC-23, parse test).
- [x] Docs updated: `CLAUDE.md`, `backend/README.md`.
