# TODO-037 — Bike expert review through the searcher service (same pattern as TODO-031 / 032 / 033 / 035)

Reference write-ups: `docs/OLX_SEARCHER_MIGRATION.md`, `docs/DECATHLON_SEARCHER_MIGRATION.md`,
`docs/ALLEGRO_SEARCHER_MIGRATION.md`, `docs/PHOTOS_SEARCHER_MIGRATION.md`; this task's own (written last, in Polish):
`docs/REVIEW_SEARCHER_MIGRATION.md`. Branch `feature/036-review-searcher`, based on `feature/photos-searcher` (TODO-035) —
so the searcher concurrency limit here is **10** (raised from 2 by TODO-035), not the 2 quoted in the main `CLAUDE.md`.
Stays `TODO_` until the PR has merged to `main` (then rename to `DONE_`, move to `backlog/done/`, update
`backlog/done/README.md`). Merge TODO-035 first (or rebase onto `main` once it has merged).

## Goal (as the user stated it)
Bike reviews must stop depending on the paid `ANTHROPIC_API_KEY` (no credits left since 2026-09-26). Today
`POST /v1/bike/review` runs one Anthropic SDK `web_search` call (`backend/app/bike_review_finder.py`, prompt
`app/prompts/bike_review.md`) on every uncached request and keeps the answer as a JSON blob in the generic cache. Do to it
what TODO-033 did to Allegro: the endpoint becomes a **pure DB read** of new tables, and the search moves into the existing
`searcher/` service (`claude -p` on the subscription), triggered only by the user clicking **Poproś o dane** in the
"Recenzja eksperta" section.

## Decisions (interview with the user)
1. **Same searcher service** — a new route `POST /v1/search/review` inside `biker-searcher` (same image, secrets, IAM).
2. **`POST /v1/bike/review` = pure DB read** of `bike_review` + `bike_review_source`. No AI, no generic cache, no TTL.
   Response shape unchanged: `{score, explanation, ref, rating, sources_used}`. **No review stored → 200 with the empty
   review `{score: 0, explanation: "", ref: [], rating: 0.0, sources_used: 0}`** (writer's choice, replacing the old
   `"Recenzja niedostępna."` fallback text; unknown bike and DB error behave the same, DB error also logs at ERROR). The
   frontend already treats `ref` empty and `sources_used == 0` as "no data" (`hasReview` in `BikeDetailsView.tsx`), so an
   empty review renders `RequestDataButton`; `usePopularBikes` already reads `rating` 0 as "Brak oceny". **Flag for the
   implementer:** verify no other consumer shows `explanation` unconditionally.
3. **New `POST /v1/bike/review/search`** — 404 `"Bike not found"` for an unknown bike (`offers_repository.bike_exists`,
   **before** any searcher call), then proxy to `POST {SEARCHER_URL}/v1/search/review` with `X-Searcher-Key`. Single-flight
   per bike, shares the process-wide in-flight cap with the other searcher routes (`SEARCHER_MAX_INFLIGHT`, now 10),
   503 (not configured / unreachable / busy — fixed strings naming "Review searcher"), 502 with the searcher's detail.
   Never cached.
4. **Searcher owns all review logic**: it takes over `prompts/bike_review.md` and everything in `bike_review_finder.py` —
   source weights 3/2/1 (`pro_numeric` / `pro_qualitative` / `community`), non-zero rating requires ≥ 1 pro source,
   `DISAGREEMENT_THRESHOLD` 3.0 anchoring to the pro/numeric mean (fallback pro/qualitative) plus the Polish disagreement
   sentence appended to `explanation`, `ref` sorted Tier 1 → 2 → 3, JSON extraction, `<cite>` stripping. The prompt likely
   needs CLI tuning (WebSearch/WebFetch rather than the SDK `web_search` tool, `--json-schema` output) — see "Probe results".
5. **Persistence**: the searcher saves (upsert — replaces that bike's review row and its sources) **only when `ref` is
   non-empty AND `sources_used >= 1`**; an empty or degenerate result writes and deletes nothing, so a stored review is
   never wiped by a bad run. It creates the `bike` row if missing (like the offer routes), when called directly.
6. **Tables** (no TTL):
   - `bike_review` — `id`, `bike_id` INTEGER NOT NULL UNIQUE FK → `bike.id` ON DELETE CASCADE, `score` int, `explanation`
     text, `rating` float, `sources_used` int, `created_at`, `updated_at`.
   - `bike_review_source` — `id`, `review_id` FK → `bike_review.id` ON DELETE CASCADE (indexed), `url` String(2048),
     `display_order` int (preserves the tier-sorted `ref` order; read `ORDER BY display_order, id`).
   Created by the backend's `init_db()` at startup; the searcher carries a **verbatim DDL copy** in `searcher/app/models.py`
   (change the backend's first, then the copy) and adds both tables to `REQUIRED_TABLES`.
7. **Frontend**: the "Recenzja eksperta" section gets `RequestDataButton` (`MissingType.Review`) with
   `onRequested` = the review search and `pendingLabel="Szukam recenzji…"`, exactly like the offer cards; the returned
   review replaces the button; empty result → "Nie znaleziono recenzji" (disabled); a failure → clickable again. The home
   page (`usePopularBikes`) still calls `POST /v1/bike/review`, now answered from the DB instantly; rating 0 still reads
   "Brak oceny". No home-page change is expected.
8. **Migration of existing data**: one-off `backend/scripts/copy_review_cache_to_table.py` copying the `'/v1/bike/review'`
   rows of `endpoint_req_to_body_cache` into the new tables. SQLite **and** PostgreSQL, `--dry-run`, idempotent, only rows
   with `ref` non-empty and `sources_used >= 1`, bike looked up by Python-normalised brand/model, rows for bikes not in
   `bike` skipped and listed. Run locally and on Cloud SQL (the Cloud SQL run only after the user's go-ahead). The old
   generic-cache rows stay in place as dead rows (nothing reads them).
9. **`seed_popular_bikes.py`** reads the review rating from `bike_review` instead of the generic cache (its
   `REVIEW_ENDPOINT` / `load_ratings` / `_normalise` cache-key logic goes; the "cached review with a rating > 0" reason
   becomes "stored review with rating > 0").
10. **Removed from the backend**: `app/bike_review_finder.py` and `app/prompts/bike_review.md` (moved to the searcher; also
    drop the `find_bike_review` import in `main.py` and any dev script or prompt test that only drove them, e.g.
    `scripts/test_review.py` — replaced by the smoke cases below).
11. **Out of scope**: `/v1/equipment/review` (stays on the SDK and the generic cache), the expert rating inside search
    results (separate task), any deploy (ask the user first), deleting the old cache rows, TTL/refresh of stored reviews.

## Contract

**Searcher** (`searcher/`)
- `POST /v1/search/review` `{company, model}` + `X-Searcher-Key` → `{review: {score, explanation, ref, rating,
  sources_used}, bike_id, saved}` — same auth, same 401/422/502/503/500 mapping and the **same semaphore** as the other
  routes (`SEARCHER_MAX_CONCURRENT` default 10, counted across all routes). `review` = the review now stored for the bike,
  or the empty review when nothing was found/stored; `saved` = 1 when a review was written, else 0.
- `app/review_finder.py` (new) — `find_bike_review(company, model)` via `run_structured` (`claude -p --json-schema`) with
  `prompts/bike_review.md`; the aggregation helpers ported from `bike_review_finder.py`; raises `SearcherError` when the CLI
  fails. No Playwright.
- `app/repository.py` — `save_review(...)` (upsert of `bike_review` + replace of its `bike_review_source` rows, one
  transaction, bike row created if missing) and `get_stored_review(...)`.
- `app/models.py` — the two tables (verbatim copy), `REQUIRED_TABLES` extended.
- `scripts/test_searcher.py` — 401 without key on `/v1/search/review`, 422 for a blank model (free, no CLI run);
  at most one paid run in the whole suite.
- `README.md` — `## Endpoints` gets `### POST /v1/search/review` (request example + Flow: `claude -p` × 1, DB write);
  `.env.example` unchanged.

**Backend** (`backend/`)
- `app/models.py` — `BikeReview`, `BikeReviewSource` ORM classes (created by `init_db()`, no migration step).
- `app/reviews_repository.py` (new) — `get_bike_review(company, model) -> BikeReviewResponse` via
  `repository._find_bike_id` (Python normalisation, never SQL `lower()`); empty review on unknown bike / nothing stored /
  DB error.
- `app/searcher_client.py` — `SEARCH_PATHS["review"] = "/v1/search/review"`, `search_review()` returning
  `BikeReviewResponse` (the searcher's `bike_id`/`saved` dropped).
- `app/main.py` — `/v1/bike/review` → `get_bike_review` (no `get_cached`/`set_cached`); new `POST /v1/bike/review/search`
  per decision 3. `BikeReviewRequest` keeps its validation (non-empty, ≤ 255 chars → 422; add `max_length=255` if absent).
- `scripts/copy_review_cache_to_table.py` (new) per decision 8; `scripts/seed_popular_bikes.py` per decision 9.
- `scripts/test_search.py` — `case_review` (seeded review rows → `POST /v1/bike/review` 200 with the stored values and
  the `ref` order, no generic-cache row, < 5 s; unknown bike / bike without review → 200 with the empty review),
  `case_review_search` (unknown bike → 404 only — no paid run).
- `README.md` — `## Endpoints`: rewrite `/v1/bike/review`, add `/v1/bike/review/search`, each with a raw HTTP example and a
  **Flow** list; `app/DB_MIGRATION.md` gets the two tables and the copy script.

**Frontend** (`frontend/`)
- `src/App.tsx` — `searchReview(bike)` → `POST /v1/bike/review/search`, throws on non-OK, writes the result into `review`
  (`reviewState` → `'loaded'`) **without** flipping to `'loading'`; guarded by `selectedBikeRef` so a late result for another
  bike is dropped; passed to `BikeDetailsView` as `onSearchReview`.
- `src/components/BikeDetailsView.tsx` — the Review branch's `RequestDataButton` gets `onRequested={onSearchReview}` and
  `pendingLabel="Szukam recenzji…"`; the not-found message ("Nie znaleziono recenzji") follows the existing button
  behaviour when the search resolves with the button still mounted. `RequestDataButton.tsx` needs no new props (check the
  hard-coded "Nie znaleziono ofert" text and make it per-section if it is offers-specific).
- `src/hooks/usePopularBikes.ts` — no change expected; verify the `rating` 0 → "Brak oceny" path against the empty review.
- `frontend/README.md` — Polish label map and API list updated. UI strings stay Polish; the equipment view is unchanged.

## Probe results
Probed 2026-09-29 with `Trek Marlin 5` and `Kross Level 3.0`, through the searcher's own argv (`claude -p`,
`claude-haiku-4-5`, WebSearch + WebFetch, `--json-schema`).

**Untuned prompt (byte copy of the SDK prompt)** — works technically, fails on quality:
- Marlin 5: 155 s, 42 turns, $0.85, valid JSON, rating 7.8 / sources_used 4. But it cited the banned
  `escapecollective.com`, tagged an affiliate blog (bestbikeselect) as `pro_numeric`, and cited an mtbr thread whose
  WebFetch had redirected.
- Kross Level 3.0: 71 s, 23 turns, $0.51, rating 6.2 / 3.

**Reachability** (WebFetch): bike-test, bikeradar, bikexchange, escapecollective, singletracks, cyclistshub and Polish
forums fetch fine; `mtbr.com` redirects (search snippets only). Nothing is 403-blocked the way allegro.pl is, so no
Playwright and no snippet-only fallback is needed.

**Tuned draft v1** (8 WebSearch / 4 WebFetch, cite only fetched pages): 199.5 s, 14 turns, $0.32, one source
(yescycling), rating 8.0 → rejected (too strict, too few sources).

**Final tuned prompt** (`searcher/app/prompts/bike_review.md`, no longer byte-identical to the SDK prompt): 6 WebSearch /
3 WebFetch; aim for 2–4 sources; a search-result URL is citable when its title + snippet clearly show a review of this
exact model; never cite a redirected or errored fetch; `pro_numeric` only for the listed outlets; affiliate/SEO blogs
at most `pro_qualitative`; sibling models do not count; banned domains. Result for Marlin 5: 70.2 s, 12 turns, $0.24,
rating 7.4 / 3 sources (mtbinsider `pro_qualitative` 8, cyclistshub `pro_qualitative` 7, mtbr thread `community` 7).

**Consequences for the implementation**
- Code-side guard `BANNED_REVIEW_DOMAINS` = {escapecollective.com, velominati.com}: such sources are dropped before
  aggregation.
- The SDK repair pass is dropped: `--json-schema` returns a validated object or the CLI fails (→ 502).
- Keep `SEARCHER_CLI_TIMEOUT` at 300 s (wall time varies 70–200 s per run).
- Haiku's Polish has occasional typos (same as the SDK version).

## Order of work
This file → probe (fill the section above) → implement (searcher, then backend, then frontend) → migration script on a
copy of the local DB → smoke tests → `/manual-tester` twice: real stack (local Postgres `biker-pg`, real searcher) and
fake-searcher stack → PR → **ask the user before deploying** → docs (`backend/README.md`, `searcher/README.md`,
`frontend/README.md`, `README.md`, `CLAUDE.md`) and the Polish `docs/REVIEW_SEARCHER_MIGRATION.md` at the end.
Deploy checklist to record there: `scripts/deploy.ps1` deploys the searcher first and the new searcher refuses to start until
the tables exist, so **before any deploy** run `copy_review_cache_to_table.py` against Cloud SQL through the proxy (it creates the
tables via `init_db()` and copies the reviews), or deploy `-Only backend` first → deploy searcher and backend → frontend.

## Acceptance criteria
- [ ] `POST /v1/bike/review` returns the stored review (score, explanation, `ref` in stored order, rating, sources_used)
      with no AI call and no generic-cache row, in < 5 s; unknown bike and a bike without a review are a 200 with the
      empty review.
- [ ] `POST /v1/bike/review/search`: unknown bike → 404 before any searcher call; searcher not configured / unreachable /
      busy (incl. Cloud Run 429) → 503 with the fixed detail; searcher failure → 502 with its detail; success returns
      the stored review. Identical concurrent requests share one search.
- [ ] `POST /v1/search/review` stores a review only when `ref` is non-empty and `sources_used >= 1`, replaces that bike's
      previous review and sources on success, and deletes nothing on an empty/degenerate result; rating logic
      (weights, disagreement anchoring and Polish sentence, `ref` ordering, `<cite>` stripping) matches the old
      `bike_review_finder.py` on the same per-source input.
- [ ] `bike_review` / `bike_review_source` are created by the backend `init_db()`; the searcher carries an identical DDL
      copy and refuses to start when they are missing.
- [ ] `copy_review_cache_to_table.py` copies eligible rows of a copy of the local database (SQLite and PostgreSQL) with
      score, explanation, rating, sources_used and `ref` order preserved; a second run changes nothing; `--dry-run` writes
      nothing; rows for unknown bikes are skipped and listed.
- [ ] Opening a bike shows a stored review without a search; with none, the section shows `RequestDataButton` after the
      loading grace; a click records `review` via `/v1/bike/missing` and runs the review search; a found review replaces
      the button; an empty result shows "Nie znaleziono recenzji"; a failure makes the button clickable again; a late
      result for another bike is dropped.
- [ ] The home page's popular cards still show expert ratings from the DB instantly; a bike without a review shows
      "Brak oceny". `seed_popular_bikes.py` picks bikes by their stored review.
- [ ] `bike_review_finder.py` and `prompts/bike_review.md` are gone from the backend; `/v1/equipment/review` still works
      unchanged.
- [ ] Smoke tests updated (`backend/scripts/test_search.py` `case_review` / `case_review_search`, `searcher/scripts/
      test_searcher.py`); at most one paid searcher run in the whole suite; `/manual-tester` green on the real and the
      fake-searcher stack.
- [ ] Docs updated per the Documentation Update Policy (`backend/README.md` Endpoints with Flow lists,
      `searcher/README.md`, `frontend/README.md`, `README.md`, `CLAUDE.md`, `backend/app/DB_MIGRATION.md`) and
      `docs/REVIEW_SEARCHER_MIGRATION.md` written in Polish; deploy checklist recorded.
