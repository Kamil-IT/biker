# TODO-043 — Drop `search_cache` + `search_bike_rating_cache` — Test Plan

**Branch:** `feature/043-drop-search-cache-tables` · **Commit under test:** `4c41342` · **Date:** 2026-10-01
**Environment:** backend `:8002` on an isolated SQLite copy of `cache.db` (`qa043.db`, tables already dropped);
frontend `:5178` (`BIKER_API_URL=http://localhost:8002`); searcher not running; Anthropic API credits exhausted
(AI search path verified by unit test / direct call only). The shared local PostgreSQL `biker-pg` is **not** used
(another session is refactoring it); the PostgreSQL dialect is tested on a throwaway database in the same container.

## Scope

In: backend models, `store.save_search`, migration script (both dialects), search DB-hit path, details view opening
from a result, on-demand search guards, docs. Out: the AI search call itself (no credits), Cloud SQL (user runs it).

## Traceability

| Req | Requirement | Implemented | Status |
|---|---|---|---|
| R1 | Models no longer define the tables; `init_db()` does not recreate them | `backend/app/models.py` | Implemented |
| R2 | `POST /v1/bike/search` DB-hit still returns bikes with stored explanation/chips | unchanged `repository.find_bikes_by_details` | Implemented |
| R3 | `save_search` keeps every AI-found bike in `bike` (case-insensitive, casing kept) | `backend/app/store.py` | Implemented |
| R4 | Migration: dry-run, drop, idempotent, SQLite + PostgreSQL, `bike` kept | `backend/scripts/migrate_drop_search_tables.py` | Implemented |
| R5 | Details view opens from a result; on-demand routes 404 only for unknown bikes | unchanged `bike_exists` guards | Implemented |
| R6 | No references in `backend/app`; docs updated | 5 docs, `migrate_drop_search_rating.py` deleted | Implemented |
| — | Drop on Cloud SQL | — | **Blocked** (prod access is the user's) |
| — | Extra: TODO-040 script deleted | not requested explicitly | Flagged |

## Test conditions

- TC-A `init_db()` on an empty database creates no search tables (R1)
- TC-B a running backend does not recreate them on a migrated database (R1)
- TC-C brand + model search hits the DB and renders cards with stored text/chips (R2)
- TC-D the details view opens from a card: details 200, no 5xx on any call (R5)
- TC-E on-demand routes: unknown bike → 404, known bike without searcher → 503 (R5)
- TC-F `save_search` → `bike` only, case-insensitive match (R3)
- TC-G migration SQLite: dry-run / drop / idempotent (R4)
- TC-H migration PostgreSQL: same on a throwaway DB (R4)
- TC-I code + docs references (R6)
- Regression: home page popular bikes with ratings, smoke suite `scripts/test_search.py`

## Test cases

| ID | Req | Pri | Preconditions | Steps | Expected |
|---|---|---|---|---|---|
| TC-01 | R1 | P1 | temp SQLite path | `configure_db(tmp)`; `init_db()`; list tables | no `search_cache`, no `search_bike_rating_cache`; `bike` present |
| TC-02 | R1 | P1 | backend on `:8002` started on `qa043.db` | list `qa043.db` tables after startup + a search | the two tables absent |
| TC-03 | R2 | P1 | frontend `:5178` | Filters: Marka `Trek`, Model `Madone SL 6`; submit | ≥1 card "Trek Madone SL 6"; API 200 `bikes` non-empty; `explanation`/`accessories` from stored details (or empty, never from AI) |
| TC-04 | R5 | P1 | TC-03 | click the card | details view: header, `POST /v1/bike/details` 200, `/photos`, `/review`, `/allegro`, `/used/olx`, `/decathlon` all 200; no 5xx; no console errors |
| TC-05 | R5 | P2 | backend | `POST /v1/bike/used/search` FakeBrand/NoSuchModel; same for a known bike | 404 `Bike not found`; known bike → 503 (searcher unavailable), never 500 |
| TC-06 | R3 | P1 | temp SQLite via pytest | `pytest -k save_search_stores_bikes_only` | pass: existing bike matched case-insensitively, new one created with caller's casing, no search tables |
| TC-07 | R4 | P1 | copy of `cache.db` from before the drop | `--dry-run` → `migrate` → `migrate` again | dry-run: tables still there; run: `migrated`, `bike` count equal; again: `already-migrated` |
| TC-08 | R4 | P1 | throwaway PostgreSQL DB `biker_qa043` with `bike` + the two tables (from `pg_dump`) | same three runs with `--url` | same results on PostgreSQL |
| TC-09 | R6 | P2 | repo | grep `backend/app` for the table names / `SEARCH_TTL`; grep docs for the new script | no code references; `migrate_drop_search_tables.py` documented in README, backend/README, CLAUDE.md, DB_MIGRATION.md |
| TC-10 | reg | P2 | frontend `:5178` | open `/` | "Najpopularniejsze rowery" renders 3 cards with ratings (`POST /v1/bike/review` 200) |
| TC-11 | reg | P1 | backend `:8002` | `BIKER_API_URL=http://localhost:8002 python scripts/test_search.py` | 0 failed |

## Results — round 1 (2026-10-01, commit `4c41342`)

**11 passed · 0 failed · 0 blocked · round 1**

| ID | Result | Evidence |
|---|---|---|
| TC-01 | Pass | `init_db()` on an empty SQLite file: search tables `set()`, `bike` present |
| TC-02 | Pass | `qa043.db` after backend startup + a search: no `search%` table, `bike` 674 rows |
| TC-03 | Pass | `POST /v1/bike/search` 200 → `Trek Madone SL 6`, chips `Shimano Ultegra RX RD-RX805` / `ST-R8170` / `Carbon (OCLV Carbon)`; card rendered with rating 8.2 (`tc03_search.png`) |
| TC-04 | Pass | details view: `/details` 200 with components, `/photos` `/review` `/allegro` `/used/olx` `/decathlon` all 200, no 5xx, no console errors (`tc04_details.png`) |
| TC-05 | Pass | unknown bike → 404 `Bike not found`; known bike without searcher → 503 `OLX searcher unavailable` |
| TC-06 | Pass | `test_save_search_stores_bikes_only` + `test_migrate_drop_search_tables` green (pytest suite 81 passed) |
| TC-07 | Pass | SQLite copy (674 bikes, 206 + 47 rows): dry-run leaves both tables, run → `migrated` with `bike` 674 kept, re-run → `already-migrated` |
| TC-08 | Pass | throwaway PostgreSQL `biker_qa043` (723 bikes, 46 + 199 rows): same three outcomes; only `bike` left; DB dropped afterwards |
| TC-09 | Pass | `backend/app`: only the explanatory docstring in `store.py` names the tables; script documented in README, backend/README, CLAUDE.md, DB_MIGRATION.md |
| TC-10 | Pass | home page: "Najpopularniejsze rowery" with 3 cards and 3 expert ratings (`bike_popular` seeded in the QA copy first — the copy of `cache.db` had 0 rows, which hides the section by design) |
| TC-11 | Pass | smoke suite on `:8002`: 14 passed, 0 failed, 4 skipped (searcher down, AI cases) |

Notes: the shared local PostgreSQL `biker-pg` was not usable for QA — another session was refactoring it
(`bike_detail` dropped, components re-keyed) and a main-based backend's `create_all()` had recreated the two
search tables there, empty. The drop must therefore be re-run on `biker-pg` once this branch is on `main`
(idempotent). Cloud SQL: not run (prod access is the user's) — deploy the backend first, then drop through the proxy.
