# ISSUE-016 — Component names link to the equipment view even when they are not a product

**Status:** DONE — merged to `main` in [PR #146](https://github.com/Kamil-IT/biker/pull/146) on 2026-10-02 (manual QA: `docs/testing/ISSUE_016/TEST_PLAN.md`). Production: Cloud SQL backup taken 2026-10-02, the `migrate_component_linkable.py --dry-run` on Cloud SQL showed 33216 rows → 27676 linkable / 5540 not; the real run on Cloud SQL was done by the user the same day (`migrated`, 33216 rows → 27676 / 5540). The deploy (backend + searcher, then frontend) is deliberately postponed — Cloud Run still runs the old code, which is safe on the migrated database.
**Reported:** 2026-10-02, by the user, with screenshots of the "Akcesoria" section of a details page.

## Problem

In the bike details view every component element name renders as a link to the equipment view
(`ElementItem` in `frontend/src/components/BikeDetailsShared.tsx`, `linkable = !!onElementSelect && !!name`).
The data behind it (the searcher's `bike_details.md` prompt, `Accessories → Tool / Pedals / Included Items`)
regularly produces elements that are not products at all:

| Element | Subcategory | Link makes sense? |
|---|---|---|
| Giant Multi-Tool | Narzędzie (Tool) | yes — a real product |
| None included | Pedały (Pedals) | no |
| Owner's Manual · Quick Start Guide · Warranty Documentation | W zestawie (Included Items) | no |
| Alloy Platform Pedals · Hydraulic Disc Brake · Rear Rack | various | no — generic, no brand or model |

A click on such a link opens the equipment view, which fires `POST /v1/equipment/details` + `/v1/equipment/review`
(four paid Anthropic calls, category inferred as `apparel`) and shows an empty page. In the local database
"None included" alone is the pedals element of 76 bikes.

## Decision (interview 2026-10-02)

- The decision whether a name is "a product worth entering" is **data**, not a frontend guess: new column
  `bike_component.is_linkable` (bool, NOT NULL), returned as `ComponentElement.is_linkable`; the frontend
  links the name only when `true`.
- **Source of truth for new searches = the model.** The searcher's prompt and JSON schema require `is_linkable`
  per element: `true` only for a specific, searchable product (brand + model / part number); `false` for
  not-supplied placeholders ("None included", "brak w zestawie", "n/a"), paperwork (manuals, guides, warranty,
  documents) **and generic parts without a brand or model** ("Pedals", "Alloy stem"). Only the model's verdict is
  stored — the regex heuristic does **not** override it. A missing / non-boolean flag is stored `false`.
- **Existing rows and the scraper = one shared regex heuristic** (`backend/app/linkable.py`, English + Polish
  patterns): used by the backfill migration over the ~33 k stored rows and by the centrumrowerowe processor on
  every save (it has no model to ask).
- Out of scope: a 400 guard in `/v1/equipment/*` for junk names, re-searching or cleaning existing bikes, the
  equipment view (its names were never links).

## Implementation

- **Backend:** `app/models.py` `BikeComponent.is_linkable` (`Boolean NOT NULL default True server_default TRUE`
  — the old behaviour for rows an older writer might still insert); `app/schemas.py` `ComponentElement.is_linkable: bool = True`;
  `app/repository.py` reads/writes it per element; `app/linkable.py` `is_linkable(name, subcategory)`;
  `scripts/migrate_component_linkable.py` (`--dry-run` prints the distribution + most frequent names per class,
  `--reclassify`, `--db`, `--url`, one transaction, verified, idempotent — a present column keeps the model's flags).
- **Searcher:** `app/schemas.py` (`is_linkable: bool = False`), `app/details_finder.py` (schema: required boolean;
  parse: literal `true` only), `app/prompts/bike_details.md` (the rule), `app/models.py` (DDL copy + startup check
  naming the migration), `app/repository.py` (save / rebuild).
- **Webscraper:** `product_parser.py` `_Tree.build` sets `is_linkable=is_linkable(name, subcategory)`.
- **Frontend:** `types.ts` `ComponentElement.is_linkable: boolean`; `BikeDetailsShared.tsx` `ElementItem`
  links only when `is_linkable === true`.
- **Tests:** `backend/scripts/test_linkable.py`, `test_migrate_component_linkable.py`, round-trips in
  `test_details_repository.py`, `case_details` in `test_search.py` asserts the flag is a bool on every element;
  `searcher/scripts/test_details_finder.py` (schema, parse, save round-trip);
  `webscraper/centrumrowerowe/tests/test_product_parser.py` (heuristic applied).
- **Docs:** `CLAUDE.md`, `README.md`, `backend/README.md`, `backend/app/DB_MIGRATION.md` § Component link flag,
  `searcher/README.md`, `frontend/README.md`.

## Deploy order

1. Cloud SQL on-demand backup.
2. `python scripts/migrate_component_linkable.py --dry-run` through the proxy, review the split, then the real run —
   **only on the user's explicit go**.
3. Deploy backend + searcher together (the new searcher refuses to start without the column; the new backend's
   details reads fail without it; the old backend keeps working on a migrated database — server default TRUE).
4. Deploy the frontend last (against an old backend, with no `is_linkable` field, it would link nothing).

## Acceptance

- Details page of a bike whose Accessories carry "Giant Multi-Tool", "None included", "Owner's Manual",
  "Quick Start Guide", "Warranty Documentation": only "Giant Multi-Tool" is a link; the rest is plain text.
- A new details search stores the model's `is_linkable` per element; `POST /v1/bike/details` returns it.
- The migration on the local `biker-pg` gives a reviewed true/false split; a rerun is `already-migrated`.
- All unit tests green (backend, searcher, webscraper); `tsc` clean.
