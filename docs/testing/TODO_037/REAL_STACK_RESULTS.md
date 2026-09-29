# TODO-037 — real-stack manual QA results

Date: 2026-09-29 · Tester: `qa-real` (agent) · Branch `feature/036-review-searcher` (uncommitted worktree)

## Environment

| Piece | Setting |
|---|---|
| Database | scratch SQLite copy of `biker/backend/cache.db` (`qa.db`); `migrate_photos_bike_id.py` → `already-migrated` |
| Backend | worktree `backend/`, uvicorn `:8011`, `DATABASE_URL=sqlite:///<qa.db>`, `SEARCHER_URL=http://127.0.0.1:8111` |
| Searcher | worktree `searcher/` (backend venv), uvicorn `:8111`, same `DATABASE_URL`, real `claude` CLI 2.1.285, model `claude-haiku-4-5-20251001` |
| Frontend | worktree `frontend/`, Vite `:5177`, `BIKER_API_URL=http://localhost:8011` |
| Browser | Playwright Chromium (headless), global python |
| Popular list | `seed_popular_bikes.py --db qa.db --bike` × 4: Trek Madone SL 6, Cannondale Topstone Carbon 4, Giant Revolt Advanced Pro, Trek Marlin 5 (the last one has no review) |

## Summary

**Round 1:** 7 passed · 0 failed · 2 blocked (R3 and R5: the Claude subscription hit its session limit).
**Round 2 (2026-09-30 01:01, after the limit reset):** R3, R4 on the R3 bike and R5 re-run. **Final: 9 passed · 0 failed · 0 blocked.** Paid runs used: 2 of 2 (attempt 1 hit 429 after 613 ms of API time).

| ID | Case | Result |
|---|---|---|
| M1 | `copy_review_cache_to_table.py` dry-run / real / idempotent re-run | PASS |
| R1 | Home page ratings come from `bike_review` | PASS |
| R2 | Details of a bike with a copied review | PASS |
| R3 | Paid review search from the UI | PASS (round 2; round 1 blocked by the subscription limit) |
| R4 | Cost guard (backend + searcher direct) | PASS (Madone SL 6 in round 1, Marlin 5 after R3) |
| R5 | Reload details after R3 | PASS |
| R6 | Unknown bike | PASS |
| R7 | `seed_popular_bikes.py --dry-run` | PASS |
| R8 | Searcher startup guard without review tables | PASS |

## Details

### M1 — migration
- `--dry-run`: `26 cached review rows: would copy 17, skipped_existing 0, skipped_unknown_bike 0, skipped_degenerate 9, unparseable 0, dropped_urls 0`. The dry run did not create the `bike_review*` tables.
- Real run: `copied 17` → 17 `bike_review` rows, 57 `bike_review_source` rows.
- Second run: `copied 0, skipped_existing 17`. Nothing changed.
- Every one of the 17 copied rows was compared against its cached JSON (score, explanation, rating, sources_used, `ref` ordered by `display_order`): 0 mismatches. Spot checks:
  - Ari Bikes Delano Peak: 8 / 8.2 / 5 sources.
  - Ari Bikes La Sal Peak: 8 / 7.9 / 4 sources.
  - The `ref` order is identical to the cached JSON for both.

### R1 — home page
- Cards show 8.2 / 7.2 / 8.4 (the stored ratings). Trek Marlin 5 shows "—" with the aria-label "brak oceny".
- Network: `GET /v1/bike/popular` ×2 (StrictMode) and `POST /v1/bike/review` ×4. No `/v1/bike/review/search`. Screenshot: `r1_home.png`.

### R2 — details with a stored review
- Trek Madone SL 6: the "Recenzja ekspertów" section shows 8/10, the explanation and a Sources table with bikeradar.com, bicyclingaustralia.com.au and bikeforums.net (all `https://`).
- No request button in the review section.
- Network: details, review, allegro, used/olx, decathlon, photos. No `/review/search`.
- The explanation is English. It is legacy cached data from before the Polish prompt, not a regression.

### R3 — paid run

#### Attempt 1 (2026-09-29 22:54) — blocked
Bike: Trek Marlin 5 (id 1, details + 8 photos, no review).

Steps and observations:
1. Opened the bike from the home page. The review section showed "Nie mamy jeszcze tych danych" + **Poproś o dane** as soon as the empty review arrived.
2. Clicked the button. `POST /v1/bike/missing` `{missing_type: "review"}` → 200, and the backend logged `missing request recorded | bike_id=1 type='review' counter=1`. `POST /v1/bike/review/search` was sent at the same time.
3. "Szukam recenzji…" was shown (`r3_pending.png`).
4. After 11.6 s: `502 claude CLI failed: exit 1`. The searcher log shows the CLI result `api_error_status: 429, "You've hit your session limit · resets 1am (Europe/Warsaw)"` (API time 613 ms, 1 turn). The subscription session limit was hit, so no search actually ran.
5. The UI failure path behaved as specified: the pending label disappeared and the **Poproś o dane** button became clickable again (`r3_after.png`).
6. DB: no `bike_review` row was written. A failed run deletes nothing.

Not verified yet: a found review rendering (Polish explanation, http-only Sources, no banned domains), the `bike_review` / `bike_review_source` writes, and the wall time. A retry would need the session limit to have reset.

Observation: a CLI 429 / session-limit result surfaces as 502 `claude CLI failed: exit 1` (`searcher/app/claude_cli.py:147-152` → `searcher/app/main.py:344`). A 503 or a clearer detail would tell the user to retry later.

#### Attempt 2 (2026-09-30 01:01) — PASS
- Same bike and the same Playwright script.
  - The button appeared as soon as the empty review arrived.
  - The click sent `/v1/bike/missing` (the `review` counter went from 1 to 2) and `/v1/bike/review/search`.
  - "Szukam recenzji…" was shown.
  - The review rendered **105 s** after the click (`r3_after.png`).
- Searcher log:
  - `claude CLI done | elapsed=104.11s subtype=success num_turns=10 … total_cost_usd=0.2001613`
  - `review search done | per_source=2 ref=2 rating=6.7 sources_used=2`
  - `review stored | bike_id=1 review_id=18 rating=6.7 sources=2`
  - `saved=1`
- UI:
  - Score 6/10 with a Polish explanation (Haiku's usual small grammar slips, e.g. "solidna rower").
  - A Sources table with 2 rows: mtbinsider.com and mtbr.com, both `https://`. The page has no non-http links.
- DB:
  - `bike_review` row 18: score 6, rating 6.7, sources_used 2.
  - `bike_review_source` has display_order 0 = mtbinsider (a professional review, listed first), 1 = mtbr thread (community).
  - A query over the whole `bike_review_source` table for escapecollective, velominati or a non-http(s) URL returns **no rows**.
  - `bike_missing_request` (bike 1, `review`) counter = 2 (1 per click).

### R4 — cost guard (bike with a stored review: Trek Madone SL 6, sent lower-case `trek` / `madone sl 6`)
- Backend `POST /v1/bike/review/search`:
  - Answered 200 in 0.016 s with the stored review.
  - Logged `review search skipped: review already stored`.
  - Made no searcher call.
- Searcher `POST /v1/search/review` with `X-Searcher-Key`:
  - Answered 200 in 0.026 s with `saved: 0`, `bike_id: 651` and the stored rating 8.2 with 3 refs.
  - Logged `review already stored — no search`.
- The number of `claude CLI start` log lines was unchanged (1 before, 1 after).
- Without the key: 401.

### R4 (repeat on the R3 bike, Trek Marlin 5)
- Backend `/v1/bike/review/search`: 200 in 0.012 s with the stored review (rating 6.7, 2 refs).
- Searcher `/v1/search/review` with the key: 200 in 0.013 s, `saved: 0`, `bike_id: 1`.
- The number of `claude CLI start` log lines stayed at 3 (no new run).

### R5 — reload after R3
- Home page: the Marlin 5 card now reads "ocena eksperta 6.7 na 10" (it was "brak oceny"). Screenshot: `r5_home.png`.
- Details view: the stored review and 2 Sources rows render. The review section has no request button and no pending label; the only 2 "Poproś o dane" buttons on the page belong to the offer cards.
- Network: only `/v1/bike/review` (plus details, offers and photos). No `/v1/bike/review/search`. Screenshot: `r5_details.png`.

### R6 — unknown bike (`Nonexistentbrand` / `QA Ghost 9000`)
- `/v1/bike/review/search` → 404 `Bike not found` in 0.012 s. The searcher log has no request, and no `bike` row was created.
- `/v1/bike/review` → 200 `{score: 0, explanation: "", ref: [], rating: 0.0, sources_used: 0}`.
- Validation: blank `model` → 422; 256-char `model` → 422 (`max_length` 255).

### R7 — seed dry-run
`bikes: 674 in bike, 11 qualify (>= 1 photo, >= 20 component rows, stored review with rating > 0)`. Picks were Madone SL 6 (8.2), Topstone Carbon 4 (7.2) and Revolt Advanced Pro (8.4), followed by `dry run — bike_popular unchanged`.

### R8 — startup guard
- Setup: a searcher on a fresh copy (`r8.db`), photos migrated, never opened by the backend.
- Startup failed with `RuntimeError: tables ['bike_review', 'bike_review_source'] are missing in the database — start the backend first (its init_db() creates the schema), or set SEARCHER_CREATE_TABLES=true for a standalone database`, then `Application startup failed. Exiting.` (exit 3).
- No tables were created.

## Artifacts
Screenshots and logs are in the session scratchpad `qa-real/`: `r1_home.png`, `r2_details.png`, `r3_before/pending/after.png`, `r5_home.png`, `r5_details.png`, `searcher.log`, `backend.log`, `m1_*.log`, `r7_dry.log`, `r8.log`. All servers were stopped after the run.
