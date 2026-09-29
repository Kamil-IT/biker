# TODO-036 — Bike discovery queue — test plan and results

Test basis: `backlog/TODO_036_BIKE_DISCOVERY_QUEUE.md`. Tested 2026-09-29 on the worktree
`feature/bike-discovery-queue`, backend `:8003`, frontend `:5176`, local PostgreSQL `biker-pg`.
Anthropic API credits were exhausted, so only DB-served paths were exercised; a search with no DB
match answers 400 from Anthropic, which is the expected fallback and not part of this change.

## Scope

In: scraper upsert, queue processor, parser output as seen through DB-first search,
`GET /v1/bike/details-cache`, and the details view in the browser.
Out: reviews and offers of the parsed bikes, AI search, production Cloud SQL.

## Traceability

| Requirement | Implemented in | Covered by |
|---|---|---|
| One queue row per (source, product), idempotent upsert | `scrape_rowery.py` | unit tests, RUN-01, RUN-02 |
| Re-scrape never touches status / attempts / bike_id | `scrape_rowery.py` | unit tests |
| Page parsed without AI into the backend's component tree | `product_parser.py`, `spec_mapping.py` | unit tests, TC-06 |
| Claim, lease, backoff, 3 attempts | `process_queue.py` | unit tests, RUN-03 |
| Fresh details are skipped, no duplicate `bike` row | `process_queue.py` | unit tests, RUN-03 |
| Parsed bikes found by DB-first search | parser output | TC-01 … TC-05, TC-10 |
| Parsed bikes shown in the details view | `process_queue.py` (generic cache write, `--sync-cache`) | TC-11 … TC-14 |
| Non-local database refused, off-host URL refused | `db.py`, `scrape_rowery.py`, `process_queue.py` | unit tests |

## Runs on local PostgreSQL

| ID | Step | Expected | Result |
|---|---|---|---|
| RUN-01 | `scrape_rowery.py` (69 pages) | about 1300 products inserted | Pass — 2044 listing rows, 1304 inserted |
| RUN-02 | `scrape_rowery.py --max-pages 3` again | 0 inserted | Pass — 0 inserted, 63 updated |
| RUN-03 | `process_queue.py --limit 20`, `--limit 25`, `--limit 5` | at least 18 of 20 done, no duplicates | Pass — 49 done, 1 skipped (Romet Wagant 3 had fresh details), 0 failed, 0 lost; no new duplicate identity in `bike` |
| RUN-04 | `process_queue.py --sync-cache` twice | second run writes 0 | Pass — written 44, then 0 (44 present) |

## Test cases

| ID | Case | Expected | Round 1 | Round 2 |
|---|---|---|---|---|
| TC-01 | Search `Kross` + wheel `28"` | Kross Explorer 5.0 returned, no AI call | Pass | Pass |
| TC-02 | Search `kross` + wheel `29"` | Explorer 5.0 not returned | Pass | Pass |
| TC-03 | Search `Focus` + frame `M` | Whistler 3.6 returned | Pass | Pass |
| TC-04 | Search `Raymon` + electric | HardRay E 4.0 29 returned, UrbanRay 2.0 Gent not | Pass | Pass |
| TC-05 | Search `Raymon` + not electric | UrbanRay 2.0 Gent returned, e-bikes not | Pass | Pass |
| TC-06 | `details-cache` for a trekking, an MTB and an e-bike | description, 1–8 https photos, core categories, `Electric / Powertrain` only on the e-bike | Pass | Pass |
| TC-10 | Browser: filters Marka `Kross`, Rozmiar kół `28"`, submit | result cards of parsed bikes | Pass | Pass |
| TC-11 | Browser: open Explorer 5.0, description | Polish description shown | Fail | Pass |
| TC-12 | Browser: component tree | shop components shown | Fail | Pass |
| TC-13 | Browser: photos | shop photos render | Fail | Pass |
| TC-14 | Browser: `/v1/bike/details` | no failing call | Fail | Pass |

Unit tests: `pytest webscraper/centrumrowerowe/tests` — 140 passed.

## Defect found and fixed

**Details view did not show parsed bikes (round 1, TC-11 … TC-14).** `POST /v1/bike/details` reads only
the generic cache and runs the AI pipeline on a miss; it never reads `bike_detail`. Fix, kept inside
`webscraper/centrumrowerowe`: the processor writes the generic cache entry after a verified save, and
`--sync-cache` fills it for rows processed earlier. An existing entry is never replaced.

## Known limits

- `POST /v1/bike/review` answers 400 for these bikes while the API credits are exhausted; the review
  section then shows its "request data" state. Not part of this change.
- `GET /v1/bike/details-cache` matches brand and model by exact casing (backend behaviour).
- The size selector lists only the sizes the shop shows for the displayed colour.
