# TODO-047 — bike.category: eight fixed codes, enforced by the database

## Why

`bike.category` held 19 possible values (`BIKE_CATEGORIES` before this task) with nothing validating a write,
two vocabularies (the search form sent `Hybrid/Commuter` / `Touring`, the database held `City`, `Cross`,
`Trekking`) and `Electric`, which is a drive, not a type: 287 e-bikes (mostly e-MTB and e-trekking) fell out of
every type search. The user asked (2026-10-07/08, interview in this task's session) for the values to be
normalised and fixed, the list reduced to the types the UI offers, with `Kids` added.

## Decisions (user, 2026-10-08)

- Eight codes, exactly the form's "Typ roweru" options: `Road` (Szosowy), `MTB` (Górski (MTB)), `Gravel`,
  `City/Cross/Hybrid` (Miejski / crossowy), `Touring` (Trekkingowy), `BMX`, `Folding` (Składany), `Kids` (Dziecięcy).
- Grouping: Triathlon → Road; Dirt/Street → MTB; Cyclocross → Gravel; City, Cross, Hybrid/Commuter, Cruiser,
  cargo → City/Cross/Hybrid; Trekking, e-SUV → Touring; Youth, Balance → Kids.
- Electric is no type: an e-bike gets its type from the shop's subsection; "electric" stays derivable from the
  `Electric / Powertrain` components.
- Enforcement: a `CHECK` constraint (`ck_bike_category`) rather than a native PostgreSQL `ENUM` — works on SQLite
  and PostgreSQL alike and the list can change (an enum value cannot be dropped).

## Done

- `backend/app/bike_categories.py`: the 8 codes, `LEGACY_CATEGORIES`, `category_from_shop_path`,
  `canonical_category`, `category_check_sql`; search accepts old values as aliases.
- `models.Bike` + the searcher's copy: `ck_bike_category`.
- `scripts/migrate_bike_category_codes.py` (+ tests) and `webscraper/centrumrowerowe/reclassify_ebikes.py` (+ tests).
- Discovery: `ParsedBike.shop_category`, the processor types new e-bikes from the page.
- `/v1/bike/parse`: prompt on the new codes (+ Kids); a cached old type is served as its code (key unchanged).
- Frontend: form + labels on the 8 codes, old addresses rewritten (`searchQuery.ts`).
- Docs: CLAUDE.md, READMEs, `backend/app/DB_MIGRATION.md` § Bike category codes.

## Left (only on the user's explicit go)

1. Cloud SQL on-demand backup.
2. `reclassify_ebikes.py --allow-remote` then `migrate_bike_category_codes.py` on Cloud SQL through the proxy.
3. Deploy backend (+ searcher), then frontend.
4. Pull the main checkout before the next `enrich.py` / `run_loop.sh` run (old code writes old values).
