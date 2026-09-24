# TODO-017 — Expand the Bike Details Data Model

## Goal
Evolve the bike-details data model from a **component-only tree** into a richer model with
a whole-bike header, a per-size geometry table, and dedicated E-Bike/Suspension categories,
so `/v1/bike/details` can fill consistent, comprehensive specs for every bike.

Reference model file: `backend/app/prompts/bike_details_json_example.md`.

## Background
The current example (`bike_details_json_example.md`) is a flat
`category → subcategory → elements[{ name, description, specs[{key,value}] }]` tree covering
8 categories (Frame, Drivetrain, Brakes, Wheels, Cockpit, Saddle & Seatpost, Lighting, Accessories).

A 10-agent web research sweep over real manufacturer spec sheets (Canyon, Trek, Specialized,
Shimano, SRAM, DT Swiss, Bosch, RockShox/Fox, Schwalbe, 99spokes, ISO/EN standards) found
~600 spec properties. Gap analysis against the example surfaced three structural omissions and
many missing per-component spec keys.

## Structural gaps (affect every bike)
1. **No whole-bike header** — brand, model, year, variant, price, total weight, sizes, colors,
   intended use, warranty, certification (ISO 4210 / EN 15194), e-bike summary. Currently nowhere.
2. **No geometry table** — stack, reach, head/seat-tube angles, chainstay, wheelbase, BB drop,
   standover, rider-height-per-size. This is **per-size tabular** data the flat `specs` list can't hold.
3. **No E-Bike System or Suspension categories** — motor/battery/display/charger/sensors and
   rear shock / fork internals don't map to the existing 8 categories.
4. **`name` conflates brand + model + spec** (e.g. `"Shimano GRX RD-RX822 12s"`). Every agent
   independently split **brand** / **model** / spec keys — splitting these is the highest-value change.

## Proposed model
Keep the component tree (and the flexible `{key,value}` specs — correct, since keys are
type-dependent), but wrap it and add the summary/tabular layers:

```jsonc
{
  "bike": {            // NEW header: brand, model, model_year, variant, category, intended_use,
                       // is_electric, frame_material, wheel_size, total_weight_kg,
                       // max_system_weight_kg, sizes[], colors[], price{amount,currency,msrp},
                       // warranty, certification
  },
  "geometry": [        // NEW: one row per size — size, stack, reach, head_tube_angle,
                       // seat_tube_angle, chainstay, wheelbase, bb_drop, standover, rider_height_cm
  ],
  "ebike": null,       // NEW: present only when is_electric — { motor{}, battery{}, display{} }
  "components": [      // EXISTING tree, each element gains brand + model alongside display name
  ]
}
```
- Add `brand` + `model` to each element (keep `name` for display).
- Promote `bike`, `geometry`, `ebike` to top-level siblings of `components`.
- Add `Suspension` category (rear shock); fold fork-suspension internals into the Frame→Fork element specs.

## Missing per-category spec keys (high-value)
- **Frame**: frame_grade, construction/layup, bb_standard, brake_mount_standard, max_rotor_size,
  headset_standard, steerer_tube, cable_routing, derailleur_hanger (UDH), mounts (bottle/rack/fender/cargo),
  internal_storage, weight_limit_kg, intended_use, certification, wheel_size
- **Drivetrain**: groupset + tier, drivetrain_type (1x/2x/3x), speeds, actuation (mech/Di2/AXS),
  gear_range_%, cassette tooth list, freehub_standard, crank_length, chainring teeth, chainline,
  chain links/connector, clutch
- **Brakes**: brake_type + actuation, caliper mount (flat/post/IS), rotor_mount (Center Lock/6-bolt),
  rotor front/rear size separately, pad_compound, fluid_type
- **Wheels**: hub brand/model, freehub_driver, engagement_points, spoke_count/type, tubeless_ready,
  rim outer width, hookless, max_tire_pressure, max_system_weight
- **Tyres**: ETRTO size, TPI, compound, tread/type, tubeless type, bead (folding/wire), pressure min/max,
  recommended rim width
- **Cockpit**: handlebar width/drop/reach/flare/rise/backsweep, clamp_diameter, stem length/angle/steerer_clamp,
  headset SHIS code + bearing sizes
- **Saddle & Seatpost**: saddle width/length/rail_material/cutout, seatpost setback/length/clamp_type,
  dropper post (travel/actuation/remote), clamp diameter/closure
- **Lighting**: front/rear lumens/lux, power_source (dynamo/battery), StVZO approved, standlight, bell
- **Accessories**: pedal_type, fenders/rack/kickstand included booleans, "mount present" booleans

## Scope
### Backend
- `app/prompts/bike_details_json_example.md` — rewrite to the new shape (Canyon Grizl data).
- `app/prompts/bike_details_*.md` — per-category prompts: add the new spec keys to fill.
- New prompt(s) for the whole-bike header + geometry table extraction.
- `app/schemas.py` — extend `BikeDetailsResponse` with `bike`, `geometry`, `ebike`; add `brand`/`model` to `ComponentElement`.
- `app/bike_details_finder.py` — populate the new layers; keep parse-error skip behaviour.
- `backend/scripts/test_details.py` + `test_search.py` — assert new fields present; HTTP 200.
- `backend/README.md` — update the `/v1/bike/details` schema + flow.
- Anthropic API + web_search → **must use the SQLite cache** on the happy path.
### Frontend
- `src/types.ts` — extend `BikeDetailsResponse` (+ `BikeHeader`, `GeometryRow`, `EbikeSystem`); add `brand`/`model` to `ComponentElement`.
- `src/components/BikeDetailsView.tsx` / `BikeDetailsShared.tsx` — render header, geometry table, and (when present) e-bike section.

## Open questions / Notes
- Build a **master spec-key dictionary** (full per-subcategory allowed `key` list, ~600 keys from research)
  to drive consistent LLM fill-in? Recommended as a sibling deliverable.
- Phase it? Suggested order: (1) brand/model split + header, (2) geometry table, (3) E-Bike/Suspension.
- Backward compatibility: the frontend currently reads a bare array — wrapping in `{components: [...]}` is a breaking change; coordinate FE/BE.

## Acceptance criteria
- [ ] `bike_details_json_example.md` rewritten to the wrapped model with header + geometry + components.
- [ ] `BikeDetailsResponse` includes `bike`, `geometry`, optional `ebike`; elements carry `brand`/`model`.
- [ ] Per-category prompts updated with the new spec keys; details finder fills them.
- [ ] Frontend renders header + geometry table + e-bike section; component element links still work.
- [ ] Cache hit on repeat call; tests + `backend/README.md` updated.
