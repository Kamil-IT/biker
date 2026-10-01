# Test plan - remove `bike_detail`, details onto `bike` (branch refactor/remove-bike-detail)

Scope: `bike.description` (Text NULL = no details) + `bike.short_description` (Text NOT NULL ''), `bike_detail_component.bike_id` (FK bike.id CASCADE), `save_bike_details` -> bool, migration `backend/scripts/migrate_drop_bike_detail.py`, searcher `init_db()` guard. API shapes and frontend unchanged. Environment: local PostgreSQL `biker-pg`, backend :8011 (`SEARCHER_URL=http://127.0.0.1:1`, so every search route answers 503 - no paid run), Vite :5184.

## Traceability
| Requirement | Where | Status |
|---|---|---|
| bike.description / short_description columns | backend/app/models.py:119-125, searcher/app/models.py:150-153 | Implemented |
| bike_detail model removed | backend/app/models.py, searcher/app/models.py | Implemented |
| bike_detail_component re-keyed to bike_id, FK CASCADE | models.py (both), psql check | Implemented |
| has details = description IS NOT NULL | repository.py get_bike_details / _search_fill / find_bikes_by_details; searcher repository.py _stored_details | Implemented |
| save_bike_details returns bool, webscraper uses it | repository.py:77-152, webscraper/bike_store.py store_details | Implemented |
| popular reads bike.description | popular_repository.py | Implemented |
| searcher save_details writes onto bike | searcher/app/repository.py:365-425 | Implemented |
| searcher init_db refuses unmigrated DB | searcher/app/models.py:119-135 | Implemented |
| idempotent migration script | backend/scripts/migrate_drop_bike_detail.py | Implemented (stray empty bike_detail is repaired, see defects/notes) |
| API shapes unchanged | /v1/bike/details, search, popular, photos, review | Implemented (verified) |
| Migration tests in default pytest run | backend/pytest.ini | Partial -> fixed (test file added to addopts) |

## Test cases
| ID | Pri | Steps | Expected |
|---|---|---|---|
| DB-1 | H | psql: `to_regclass('bike_detail')` | NULL |
| DB-2 | H | `\d bike_detail_component` | bike_id NOT NULL, FK -> bike ON DELETE CASCADE, index, no bike_detail_id |
| DB-3 | H | information_schema for bike columns | description text NULL, short_description text NOT NULL default '' |
| MIG-1 | H | migrate_drop_bike_detail.py --dry-run | already-migrated |
| MIG-2 | M | run for real when an empty stray bike_detail exists | migrated, table dropped, 619 / 32972 unchanged |
| UT-1/2/3 | H | backend / searcher / webscraper pytest | all green |
| API-1 | H | POST /v1/bike/details (bike with data) | same key set as README, components + description |
| API-2 | H | POST /v1/bike/details (no details) | empty response, short_description "" |
| API-3 | H | /v1/bike/search brand only; brand + wheel_size | 200, keys search/bikes[brand,model,accessories,explanation] |
| API-4 | H | /v1/bike/popular, /photos, /review | unchanged shapes |
| API-5 | H | /details/search unknown -> 404; known -> 503 (searcher unreachable) | |
| API-6 | H | scripts/test_search.py (decathlon live case SKIPs) | 0 failed |
| UI-1 | H | home: popular section, blurbs, ratings | 3 cards, blurb, ratings |
| UI-2 | H | popular -> details (Madone): description, components, review | rendered |
| UI-3 | H | search brand Aventon | results, accessory chips |
| UI-4/5 | H | search Canyon / Grizl CF 7 (no details) -> open | card without explanation/chips; Opis, Specyfikacja, photos, review, offers show "Poproś o dane" |
| UI-6 | H | click Opis "Poproś o dane" | POST /missing + /details/search, 503 (safe), no console errors |

## Results - round 1
| ID | Result | Note |
|---|---|---|
| DB-1..3 | Pass (DB-1 after MIG-2: a stray empty `bike_detail` was found - recreated by an old-code backend (PID 3200, another worktree) running create_all) | |
| MIG-1 | Pass after MIG-2 (before: "dry-run, would drop bike_detail") | |
| MIG-2 | Pass | 0 rows moved, bike_detail dropped, verified |
| UT-1 | Pass 80 passed (+8 migration tests, now collected by default: 88) | |
| UT-2 | Pass 73 passed | |
| UT-3 | Pass 187 passed | |
| API-1..5 | Pass | |
| API-6 | Pass 14 passed / 0 failed / 4 skipped (3 need --ai, 1 searcher) - first run failed on leftover `Smoke Fixture` rows from an earlier aborted run, deleted, rerun green | |
| UI-1..6 | Pass | 0 console errors; only 503s are the intended search clicks |

Final: 24 passed - 0 failed - 0 blocked - round 1 (+ the pytest.ini fix).
