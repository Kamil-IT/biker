# TODO-044 manual test plan and results

Change: `equipment` + `equipment_detail` merged, `equipment_detail_component` renamed `equipment_component`, details search fills `equipment.company` / `model` where missing.
Environment: worktree backend 8003, searcher 8103, Vite 5178, local PostgreSQL `biker-pg` (already migrated). Cannondale Topstone Carbon 4 (bike 39) used for equipment links.

## Traceability

| # | Requirement | Implemented in | Status |
|---|---|---|---|
| R1 | Tables merged, name stays `equipment` | backend/app/equipment_models.py, searcher/app/models.py | Implemented |
| R2 | `equipment_component` keyed by `equipment_id`, cascade | same | Implemented |
| R3 | Search fills missing company/model only | searcher/app/equipment_repository.py | Implemented |
| R4 | Read by name keeps working | backend/app/equipment_repository.py | Implemented |
| R5 | Migration script, idempotent, dry-run | backend/scripts/migrate_merge_equipment_detail.py | Implemented |

## Test cases

| ID | Case | Expected |
|---|---|---|
| TC-044-01 | Open stored item from a bike's tree by equipment_id (item 4 RD-RX812, item 1 Schwalbe) | description, components render; item 1 shows its photos; request carries `equipment_id` |
| TC-044-02 | POST /v1/equipment/details by name only (company "", model any case) | stored row found |
| TC-044-03 | Unsearched linkable element (Shimano GRX FC-RX810) shows Poproś o dane buttons; one real search via Opis button | details render; new row has name, company, model, description, components; bike_component linked |
| TC-044-04 | Re-search keeps filled company/model | covered by pytest (see below) |
| TC-044-05 | By-name read after search | still finds the row (name unchanged) |
| TC-044-06 | Migration rerun / --dry-run | already-migrated, row counts unchanged |
| TC-044-07 | Regression: bike details/photos/review/offers, Filters search, equipment review | load as before |
| TC-044-08 | Automated suites | green |

## Results, round 1

**8 passed · 0 failed · 0 blocked · round 1**

| Case | Result | Evidence |
|---|---|---|
| 01 | Pass | item 4: description, "Napęd" components, source chips; item 1: "QA fixture" text and 3 images; details POST body has `equipment_id` 4 / 1. Item 4 shows the photos Poproś button because it has no photos (correct) |
| 02 | Pass | `company ""` + model "Shimano GRX FC-RX810" (any case) returns the row; unknown name returns the empty response |
| 03 | Pass | before: 3 Poproś buttons (Zdjęcia, Opis, Specyfikacja). After one search (133 s) row id 10: name "Shimano GRX FC-RX810", company "Shimano", model "GRX FC-RX810", description not null, short_description set, 11 rows in `equipment_component`, both `bike_component` rows of bike 39 linked to equipment 10 |
| 04 | Pass | pytest: searcher `test_save_never_overwrites_researched_values_nor_blanks_them`, `test_save_fills_missing_company_and_model_by_name`, `test_photos_save_leaves_company_and_model_alone`; backend equivalents (14 searcher tests selected, all pass) |
| 05 | Pass | by name `"" / "Shimano GRX FC-RX810"`, lower case, `Shimano / GRX FC-RX810`, and `equipment_id` 10 all return row 10 with company Shimano / model GRX FC-RX810 |
| 06 | Pass | both runs: `already-migrated`, 4 equipment rows and 33 component rows before and after, old tables absent, no orphans table |
| 07 | Pass | Trek Marlin 5 via Filters: details, photos, offers cards, review section (no stored review, so button) load, no console errors. Cannondale bike page shows review, offers, components |
| 08 | Pass | backend `pytest -q` (addopts suite) 289 passed; searcher pytest 209 passed; `searcher/scripts/test_searcher.py` against 8103 ALL OK; `backend/scripts/test_search.py` against 8003 18 passed, 0 failed, 4 skipped (3 need --ai, decathlon_search needs SEARCHER_URL=8100) |

Observations (not failures):
- `POST /v1/equipment/review` answers 400 (Anthropic credits exhausted, equipment review is still on the SDK), so the equipment view hides the review section. Unchanged by this diff.
- The searched crank's description calls it "przerzutnica przednia" (front derailleur): AI content quality, not a data-model issue.
- Equipment ids jump 5 to 10 (sequence gaps from earlier rows), harmless.
- `pytest scripts -q` as written in the task INTERNALERRORs on `scripts/test_equipment_review.py` (calls `sys.exit` at import); `pytest.ini` addopts scopes the real suite, so plain `pytest -q` is the right command. Pre-existing.

Cost: 1 real equipment details search (133 s), subscription-billed, not measured (earlier probes: about $0.12 to 0.18 per details run). 0 photo runs.
