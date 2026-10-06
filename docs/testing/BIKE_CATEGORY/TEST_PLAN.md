# Test plan — bike.category (column + API + UI)

Stack: this worktree's backend :8011 + frontend :5184 on an isolated PostgreSQL copy `biker_qa_cat` (copy of local `biker`, 723 bikes). No AI calls; DB reads only.

| ID | Case | Expected | Result |
|---|---|---|---|
| TC-01 | `migrate_bike_category.py --dry-run` then real run on copy | column added, 55 of 723 filled, nothing written on dry run | Pass |
| TC-02 | Re-run migration | `already-migrated`, 0 changes | Pass |
| TC-03 | `POST /v1/bike/search` brand=Kross | `category` key on every bike; Explorer 5.0 = `Trekking`, Esker Eco = `null` | Pass |
| TC-04 | `POST /v1/bike/details` known / null / unknown bike | `Trekking` / `null` / `null` (empty response) | Pass |
| TC-05 | `GET /v1/bike/popular` | `category` key; Cannondale (set to Gravel) = `Gravel`, others `null` | Pass |
| TC-06 | OpenAPI schema | `category` in BikeResult, BikeDetailsResponse, PopularBike | Pass |
| TC-07 | UI result card, category set | label "TREKKINGOWY" above brand | Pass |
| TC-08 | UI result card, category NULL | no label, layout intact | Pass |
| TC-09 | UI details view (Trekking / null / popular Gravel) | header label "TREKKINGOWY" / none / "GRAVEL" | Pass |
| TC-10 | UI popular card on home page | "GRAVEL" label on Cannondale only | Pass |
| TC-11 | Console errors / HTTP >= 400 during UI run | none | Pass |
| TC-12 | Regression: backend pytest (289), discovery pytest (188), `tsc -b` | green | Pass (after round 2) |

## Rounds
- Round 1: 6 failures in existing tests, all stale fixtures not product bugs: `test_searcher_client_details` (DETAILS/EMPTY lack `category: None`), two migration-chain ORM tests (needed `migrate_bike_category` in the chain), two `test_process_queue` tests (a skipped bike now gets its NULL category back-filled — intended). Fixtures updated; expectation for the skipped bike now asserts the back-fill.
- Round 1 doc gap: CLAUDE.md / backend/README.md did not mention the column or migration. Added.
- Round 2: all green.

Notes: `GET /v1/bike/details-cache` no longer exists (404) — not applicable. Searcher not started (no searcher route changed; only its `init_db` guard and ORM column). Free-text search not exercised (parse needs the Anthropic API).
