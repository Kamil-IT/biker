# TODO-040 test plan (manual QA, ISTQB-style, risk-based)

Scope: expert rating on search result cards, removal of "Dopasowanie"/match_score, new POST /v1/bike/review/cached, column drop migration.
Env: backend http://127.0.0.1:8001, frontend http://localhost:5174, local PostgreSQL biker-pg. Anthropic API has no credits: only DB-hit searches (brand filter) are used.
Rated bikes (generic cache): Cannondale Topstone Carbon 4 7.2, Trek Madone SL 6 8.2, Giant Revolt Advanced Pro 8.4, Ari Nebo Peak 7.9.
Techniques: equivalence partitioning (rated / unrated / rating 0), state transition (pending -> loaded/error), use-case scenarios.

## Traceability
| Req | Requirement | Cases |
|---|---|---|
| R1 | Result card = expert rating numeral + "Ocena eksperta" bar like home page | TC-01 |
| R2 | No cached review -> "?", "Brak oceny", empty bar, no /v1/bike/review call | TC-02 |
| R3 | Order: rating desc, "?" last, backend order kept among them; no jumping before settle | TC-03 |
| R4 | No "Dopasowanie" / "%" on cards and details header | TC-04 |
| R5 | Home page works, "?" instead of "-" after failed rating | TC-05 |
| R6 | search + search-cache bodies have no match_score | TC-06 |
| R7 | review/cached contract (order, found false, 422, no writes) | TC-07 |
| R8 | Migration dry-run / idempotent | TC-08 |
| R9 | Smoke tests green | TC-09 |
| R10 | Exactly one /v1/bike/review/cached POST per search, no AI endpoints | TC-02, TC-10 |
| R11 | Details view opens from a result card | TC-04 |

## Test cases
| ID | Steps | Expected | Prio |
|---|---|---|---|
| TC-01 | Search brand Trek (filters panel). Find Madone SL 6 card | Numeral 8.2, label "Ocena eksperta", bar 82%, aria "ocena eksperta 8.2 na 10", no badge | High |
| TC-02 | Same search, unrated card (e.g. Trek Domane AL 2) ; record network | Numeral "?", label "Brak oceny", bar 0%, aria "brak oceny"; 0 requests to /v1/bike/review; 1 POST /v1/bike/review/cached (x2 under StrictMode allowed) | High |
| TC-03 | Mocked /v1/bike/search (route) returning unrated, 4 rated, unrated in that order | Rated cards first 8.4, 7.9, 7.2... wait 8.4,8.2,7.9,7.2; "?" cards last in original order; rank numbers 1..n | High |
| TC-04 | Search results text + open a card -> details header | No "Dopasowanie" (excluding "Fit & comfort"), no "%" on cards; header has no score block | High |
| TC-05 | Open home; then block /v1/bike/review (route abort) and reload | Popular cards show ratings; with aborted review "?" + "Brak oceny" | Med |
| TC-06 | curl search, search-cache | No match_score key | High |
| TC-07 | curl review/cached: order, unknown, rating 0 placeholder, 0 items (422), 101 items (422), empty strings (422) | per contract; no new cache rows | High |
| TC-08 | migrate_drop_search_rating.py --dry-run on local PG | already migrated / no-op | High |
| TC-09 | scripts/test_search.py | all pass | High |
| TC-10 | Network log over a whole search | No /v1/bike/review, /details, /parse calls | Med |

## Results
(appended below)

### Round 1 (2026-09-30) - all pass
Note: the Vite on :5174 served the MAIN checkout's src (old code, blank page after search: `toFixed` of undefined match_score). Tests ran on a Vite started from this worktree on :5190 (proxy to 8001).
| ID | Result | Evidence |
|---|---|---|
| TC-01 | Pass | tc01_trek_results.png: Madone SL 6 shows 8.2, bar 82%, aria "ocena eksperta 8.2 na 10" |
| TC-02 | Pass | 31 unrated cards "?", "Brak oceny", bar 0%, aria "brak oceny"; after the search click the only requests are POST /v1/bike/search + one POST /v1/bike/review/cached |
| TC-03 | Pass | tc03_before_settle.png / tc03_sorted.png (search response mocked): 8.4, 8.2, 7.9, 7.2, then "?" in backend order; real Trek search also sorted 8.2, 8.0, 6.5, then "?" |
| TC-04 | Pass | no "dopasowanie"/"%" in results or details header (tc04_details_header.png) |
| TC-05 | Pass | tc05_home_review_failed.png: review aborted -> "?" + "brak oceny"; normal home shows 7.2/8.2/8.4 |
| TC-06 | Pass | search and search-cache bodies without match_score |
| TC-07 | Pass | order kept, casing/whitespace normalised, unknown -> found false, 0 / 101 items / empty / 256-char -> 422 |
| TC-08 | Pass | dry-run on local PG: already-migrated (199 rows) |
| TC-09 | Pass | test_search.py 12 passed, 0 failed, 4 skipped (AI/searcher) |
| TC-10 | Pass | no /review, /details, /parse calls from the results list |

### Round 2 (after merge of origin/main, review/cached reads bike_review) - all pass
Servers restarted from the worktree: backend 127.0.0.1:8001, Vite :5174 (serves the worktree src, verified).
| ID | Result | Evidence |
|---|---|---|
| TC-01 | Pass | r2_tc01_trek_results.png: Madone SL 6 8.2 / 82% / aria "ocena eksperta 8.2 na 10"; Madone SL 5 Gen 8 8.0, FX 3 6.5 also rated |
| TC-02/10 | Pass | unrated cards "?", "brak oceny", 0%; after the search click only POST /v1/bike/search + POST /v1/bike/review/cached |
| TC-03 | Pass | r2_tc03_sorted.png (mocked search): 8.4, 8.2, 7.9, 7.2, then "?" in backend order |
| TC-04 | Pass | no "dopasowanie" / "%" on cards or details header |
| TC-05 | Pass | review aborted -> home cards "?" / "brak oceny" (r2_tc05_home_review_failed.png) |
| TC-07 | Pass | Trek/Madone SL 6 found 8.2; "cannondale"/" Topstone Carbon 4 " found 7.2; unknown found:false |
| TC-09 | Pass | test_search.py 14 passed, 0 failed, 4 skipped |
