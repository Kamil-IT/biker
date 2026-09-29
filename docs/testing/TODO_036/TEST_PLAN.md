# TODO-036 — Bike discovery queue — test plan and results

Test basis: `backlog/done/DONE_036_BIKE_DISCOVERY_QUEUE.md`. Rounds 1 and 2 tested 2026-09-29, round 3
2026-09-30 (after the merge of PR #115), on the worktree `feature/bike-discovery-queue`, backend
`:8003`, frontend `:5176`, local PostgreSQL `biker-pg`. Anthropic API credits were exhausted, so only
DB-served paths were exercised; a search with no DB match answers 400 from Anthropic, which is the
expected fallback and not part of this change.

## Scope

In: scraper upsert, queue processor, parser output as seen through DB-first search,
`GET /v1/bike/details-cache`, the details view in the browser (description, components, photos via
`POST /v1/bike/photos`), and `copy_to_db.py`.
Out: reviews and offers of the parsed bikes, AI search.

## Traceability

| Requirement | Implemented in | Covered by |
|---|---|---|
| One queue row per (source, product), idempotent upsert | `scrape_rowery.py` | unit tests, RUN-01, RUN-02 |
| Re-scrape never touches status / attempts / bike_id | `scrape_rowery.py` | unit tests |
| Page parsed without AI into the backend's component tree | `product_parser.py`, `spec_mapping.py` | unit tests, TC-06 |
| Claim, lease, backoff, 3 attempts | `process_queue.py` | unit tests, RUN-03 |
| A bike that already has details is skipped, no duplicate `bike` row | `bike_store.py`, `process_queue.py` | unit tests, RUN-03 |
| Parsed bikes found by DB-first search | parser output | TC-01 … TC-05, TC-10 |
| Parsed bikes shown in the details view | `bike_store.py` (generic cache write), `process_queue.py --sync-cache` | TC-11 … TC-14 |
| Shop photos stored per bike, read through `POST /v1/bike/photos` | `bike_store.store_photos` → `photos_repository.save_bike_photos` | unit tests, TC-06, TC-13 |
| Non-local database refused, off-host URL refused | `db.py`, `scrape_rowery.py`, `process_queue.py`, `copy_to_db.py` | unit tests |
| Copy to another database: never downgrades, idempotent, no re-fetch | `copy_to_db.py` | unit tests, RUN-05, RUN-06 |

## Runs on local PostgreSQL

| ID | Step | Expected | Result |
|---|---|---|---|
| RUN-01 | `scrape_rowery.py` (69 pages) | about 1300 products inserted | Pass — 2044 listing rows, 1304 inserted |
| RUN-02 | `scrape_rowery.py --max-pages 3` again | 0 inserted | Pass — 0 inserted, 63 updated |
| RUN-03 | `process_queue.py --limit 20`, `--limit 25`, `--limit 5` | at least 18 of 20 done, no duplicates | Pass — 49 done, 1 skipped (Romet Wagant 3 already had details), 0 failed, 0 lost; no new duplicate identity in `bike` |
| RUN-04 | `process_queue.py --sync-cache` twice | second run writes 0 | Pass — written 44, then 0 (44 present) |
| RUN-05 | `copy_to_db.py --target-url <GCP Cloud SQL via the proxy on 6543> --allow-remote --dry-run` | reports rows / bikes to write, writes nothing to the target | Pass — 2026-09-30, target unchanged |
| RUN-06 | `copy_to_db.py` (same target), then the same command again | first run copies the queue and the parsed bikes, second run changes nothing | Pass — 1304 queue rows inserted, 49 bikes written, 1 kept, 49 cache entries, 49 photo sets, 0 failures; second run wrote nothing (rows unchanged, details kept, cache and photos present) |

RUN-05 and RUN-06 wrote to production Cloud SQL only because the user asked for the copy explicitly
(2026-09-30); the guard (`--allow-remote`, password from `PGPASSFILE`) was in force. GCP now holds a copy
of the queue: 49 `done`, 1 `skipped`, 1254 `pending`; nothing runs there by itself.

## Test cases

| ID | Case | Expected | Round 1 | Round 2 | Round 3 |
|---|---|---|---|---|---|
| TC-01 | Search `Kross` + wheel `28"` | Kross Explorer 5.0 returned, no AI call | Pass | Pass | Pass |
| TC-02 | Search `kross` + wheel `29"` | Explorer 5.0 not returned | Pass | Pass | Pass |
| TC-03 | Search `Focus` + frame `M` | Whistler 3.6 returned | Pass | Pass | Pass |
| TC-04 | Search `Raymon` + electric | HardRay E 4.0 29 returned, UrbanRay 2.0 Gent not | Pass | Pass | Pass |
| TC-05 | Search `Raymon` + not electric | UrbanRay 2.0 Gent returned, e-bikes not | Pass | Pass | Pass |
| TC-06 | `details-cache` for a trekking, an MTB and an e-bike; `POST /v1/bike/photos` for the same | description, core categories, `Electric / Powertrain` only on the e-bike; 1–8 https photos from `/v1/bike/photos` | Pass | Pass | Pass (photos asserted through `/v1/bike/photos`) |
| TC-10 | Browser: filters Marka `Kross`, Rozmiar kół `28"`, submit | result cards of parsed bikes | Pass | Pass | Pass |
| TC-11 | Browser: open Explorer 5.0, description | Polish description shown | Fail | Pass | Pass |
| TC-12 | Browser: component tree | shop components shown | Fail | Pass | Pass |
| TC-13 | Browser: photos | shop photos render (served by `/v1/bike/photos`) | Fail | Pass | Pass |
| TC-14 | Browser: `/v1/bike/details` and `/v1/bike/photos` | no failing call | Fail | Pass | Pass |

Round 3: 13 of 13 pass. Unit tests: `pytest webscraper/centrumrowerowe/tests` — 160 passed
(140 before the photos / copy work).

## Defects found and fixed

**1. Details view did not show parsed bikes (round 1, TC-11 … TC-14).** `POST /v1/bike/details` reads only
the generic cache and runs the AI pipeline on a miss; it never reads `bike_detail`. Fix, kept inside
`webscraper/centrumrowerowe`: the processor writes the generic cache entry after a verified save, and
`--sync-cache` fills it for rows processed earlier. An existing entry is never replaced.

**2. Schema changed upstream mid-task (`bike_detail_photos.bike_id`, PR #115).** While the task was in
review, `main` moved photos out of the details: `BikeDetailsResponse` lost `photos`, `bike_detail_photos`
is now keyed by `bike_id`, and the 30-day details TTL was removed. The processor's photo handling and its
"fresh details" skip rule no longer matched the backend. Fix: the store logic moved into the shared
`bike_store.py` — photos are written through the backend's `photos_repository.save_bike_photos` only when
the bike has none (a failure is a WARNING, the row stays `done`), and a bike with any `bike_detail` row is
skipped and kept whatever its age. Re-verified in round 3 (TC-06, TC-13 through `/v1/bike/photos`).

## Known limits

- `POST /v1/bike/review` answers 400 for these bikes while the API credits are exhausted; the review
  section then shows its "request data" state. Not part of this change.
- `GET /v1/bike/details-cache` (`repository.get_bike_details`) still matches brand and model by exact
  casing (`filter_by(brand=…, model=…)`); the TTL is gone, the casing rule is unchanged.
- The size selector lists only the sizes the shop shows for the displayed colour.
- The 1254 queue rows on GCP are still `pending`; processing them there is a separate, explicit decision.
