# TODO-041 — Bike details through the searcher service (same pattern as TODO-031 / 032 / 033 / 035 / 037)

Reference write-ups: `backlog/done/DONE_037_REVIEW_SEARCHER.md` (closest sibling), `DONE_035_PHOTOS_SEARCHER.md`. Branch
`feature/040-details-searcher`. Stays `TODO_` until the PR has merged to `main` (then rename to `DONE_`, move to
`backlog/done/`, update `backlog/done/README.md`). Write-up in Polish at the end: `docs/DETAILS_SEARCHER_MIGRATION.md`.
Searcher concurrency limit is **10** (`SEARCHER_MAX_CONCURRENT`), backend `SEARCHER_MAX_INFLIGHT` 10, shared by every route.

## Goal
Bike details (description + component tree) stop depending on the paid `ANTHROPIC_API_KEY`. Today `POST /v1/bike/details`
runs 8 sequential `web_search` calls (`app/bike_details_finder.py`, prompts `bike_details_{slug}.md`) plus one description
call (`app/bike_description_finder.py`, `bike_description.md`) on every uncached request and keeps the answer in the generic
cache. Move it to the searcher pattern: DB read on the endpoint, on-demand search in `searcher/` (`claude -p`, subscription)
triggered only by **Poproś o dane**. The new `short_description` also lets the search result card stop using query-dependent
AI text.

## Decisions (interview with the user) = the contract
1. **`POST /v1/bike/details` = pure DB read** (`bike_detail` + `bike_detail_component` via `repository.get_bike_details`,
   normalised lookup, caller's casing echoed). `get_cached` / `set_cached` and the Anthropic calls are removed from it.
   Unknown bike / nothing stored → **200** with an empty `BikeDetailsResponse` (`description` = empty `BikeDescription`
   `{text: "", segments: [], citations: []}`, `components: []`, `short_description: ""`) — never an error.
   (`GET /v1/bike/details-cache` keeps its 404 semantics.)
2. **New `POST /v1/bike/details/search`** (backend, never cached): (1) **404** `"Bike not found"` when the bike is not in
   `bike` (`offers_repository.bike_exists`, **before** any searcher call); (2) stored **complete** details → returned with no
   searcher call ("complete" = non-empty components **and** non-empty description text — define once in a helper, e.g.
   `repository.has_complete_details`; details without `short_description` but otherwise complete also count as complete:
   no backfill, see Out of scope); (3) otherwise `searcher_client.search_details` → `POST {SEARCHER_URL}/v1/search/details`
   (`X-Searcher-Key`), same single-flight per `(path, normalised company, normalised model)`, shared in-flight cap, 503 busy /
   not configured / unavailable (fixed strings `"Details searcher is not configured"` / `"Details searcher unavailable"` /
   `"Details searcher is busy — try again in a moment"`), 502 with the searcher's detail, **400** `{detail}` for
   `SearcherLimitReached` (TODO-038 handler already app-wide) — exactly like `search_review`. Returns `BikeDetailsResponse`.
3. **Searcher route `POST /v1/search/details`** `{company, model}` → `{details: BikeDetailsResponse-shaped, bike_id, saved}`
   (same auth, 401/422/502/503/500 mapping and the same semaphore as the other routes; backend unwraps `details`).
   `claude -p` (WebSearch + WebFetch, **no Playwright**) returns structured output with a required `found` boolean:
   `found: false` when the model could not identify the bike (no apology/note/explanation in the output, all fields empty);
   `found: true` when the model found and describes it, and collects **everything** `/v1/bike/details` collects today:
   - the Polish 4–5 sentence `description` (forced Polish, as `bike_description.md`);
   - the component tree of 8 categories — Frame, Drivetrain, Brakes, Wheels, Cockpit, Saddle & Seatpost, Lighting,
     Accessories — `category` / `subcategory` / spec `key` names English and verbatim, element `name` and spec `value` as the
     manufacturer writes them, element `description` Polish (as the `bike_details_*.md` prompts define);
   - **new `short_description`**: a Polish **2-sentence** summary of the description, written by the AI (not the first two
     sentences cut).

   `BikeDescription` (`backend/app/schemas.py`) is `{text, segments: [{text, citations}], citations: [{url, title,
   cited_text}]}`; the CLI has no per-block citations, so the searcher builds it from the model's `sources` (`{url, title}`):
   `text` = description, `segments = [{text, citations: <all sources>}]` (one segment), `citations` = sources with
   `cited_text = ""` (keeps `DescriptionCard`'s source chips working — verify in `BikeDetailsShared.tsx`).
   **When `found: false`**: no further processing, empty details are returned, nothing is stored.
   **Stored only when usable** (non-empty components **or** non-empty description, with `found: true`): bike row created if missing (like the
   offer routes), `bike_detail` row **updated in place** (id stable) and `bike_detail_component` rows replaced, in one
   transaction, photos untouched (they hang off `bike`). An empty result writes nothing and deletes nothing, so stored
   details are never wiped by a bad run; `saved` = 1 when written, else 0; `details` = what is now stored, or the empty one.
   The searcher owns a port of the save logic (`searcher/app/repository.py` `save_details`, mirroring
   `backend/app/repository.save_bike_details` — read it and reuse its casing rule "stored brand/model casing is the display
   casing, a placeholder equal to its normalised form is upgraded", element/spec ordering columns and string-length caps read
   from the models) and a verbatim copy of the tables' DDL in `searcher/app/models.py` (change the backend's first, then the
   copy; add `bike_detail` / `bike_detail_component` to `REQUIRED_TABLES` if not already there, plus the `short_description`
   column check — see decision 4).
4. **New column `bike_detail.short_description`** (`Text`, `nullable=False`, `default=""`, `server_default=""`; model attr on
   `BikeDetails`, table `bike_detail`). `init_db()`'s `create_all()` never ALTERs, so ship an **idempotent migration script**
   `backend/scripts/migrate_short_description.py` (pattern: `migrate_photos_bike_id.py`, but simpler: `ALTER TABLE bike_detail
   ADD COLUMN short_description TEXT NOT NULL DEFAULT ''` only when the column is missing; SQLite and PostgreSQL; `--dry-run`,
   `--db <sqlite file>`, `--url <sqlalchemy url>`; importable `migrate(url_or_path=None, dry_run=False, verbose=True) -> dict`;
   idempotent "already migrated"). Hard prerequisite on any pre-existing database: until it has run the backend's ORM
   reads/writes of `bike_detail` fail. Like the photos migration the **searcher refuses to start** without the column (its
   `init_db()` column check, same mechanism as the `bike_detail_photos.bike_id` check). Deploy order: migration on Cloud SQL →
   backend + searcher together → frontend (the OLD backend keeps working against the migrated DB because the column has a
   server default; the NEW code does not work against an unmigrated DB). `BikeDetailsResponse` gains
   `short_description: str = ""` (`backend/app/schemas.py`, `frontend/src/types.ts`); `save_bike_details` / `get_bike_details`
   read and write it.
5. **`POST /v1/bike/search` result card** (`BikeResult` after TODO-040 is `{brand, model, accessories, explanation}` — there is
   **no `match_score` any more**; shape unchanged by this task): `explanation` = the bike's stored `bike_detail.short_description`
   (`""` when none) and `accessories` = chips computed **without AI at read time** from the bike's stored components: drivetrain,
   brakes, frame material — only those present, values as stored (define the derivation once, e.g.
   `repository.accessory_chips(bike_id)`: Drivetrain → the Rear Derailleur (else Crank) element `name`; Brakes → the Brake Lever
   Front (else Brake Rotor) element `name`; Frame → the Frame element's `Material` spec value; a missing part is skipped; never
   invent). Applies to **every** place that builds a `BikeResult`: the DB-hit path (`repository.find_bikes_by_details`), the
   AI-fallback result and the follow-up reads `GET /v1/bike/search-cache` (`store.py` `_row_to_bike` and its `?query=` / `?brand=`
   readers) — one shared builder, filled from `bike` + `bike_detail` by `bike_id` (for an AI-found bike the DB usually has no
   details yet → `explanation ""`, `accessories []`). The AI bike finder (`bike_finder.find_bikes`, `prompts/bike_search.md`) still
   returns the bike list (`brand`, `model`) but **stops producing query-dependent explanation/accessories**: drop both fields and
   their Polish-language/"name the missed filter" rules from the prompt and the parsing in `bike_finder.py` (the closest-bike
   fallback is kept, min 1, it just no longer explains which filter it missed — accepted). **`search_bike_rating_cache` after
   TODO-040** has only `id`, `search_cache_id`, `bike_id`, `explanation`, `accessories`, `display_order` (the `rating` column was
   dropped by `migrate_drop_search_rating.py`). After this task `explanation` / `accessories` would be dead, so the table carries
   nothing but the search→bike link plus the AI's order — **decision: keep the table and both columns, `store.save_search` writes
   `""` / `"[]"`, no migration** (the columns already have defaults; nothing reads them; dropping them would need another
   prod-ordered migration for no gain). `find_bikes_by_details` stops reading `_latest_ratings` and `_describe_match` /
   `_MATCH_LABELS` ("Pasuje: marka Trek, …", `repository.py` ~l.274–308) are deleted. A DB-hit bike without a stored short
   description has `explanation ""` — the frontend must not render an empty paragraph/chips. **The expert rating on the result card
   (TODO-040: `POST /v1/bike/review/cached`, `frontend/src/ratings.ts`, `hooks/useCachedRatings.ts`, `ResultCard`'s `expertRating`
   prop, result ordering by rating) is NOT touched by this task.**
6. **Frontend**: in `BikeDetailsView` the **Opis** (description) and **Komponenty** (component tree) sections already show
   `RequestDataButton` (`MissingType.Description` / `MissingType.Components`) when empty. Both get `onRequested` = **one
   shared** `searchDetails` (`App.tsx`: `POST /v1/bike/details/search` through the shared `postOnDemandSearch`, throws on
   non-OK, writes the answer into the existing details state → `'loaded'` **without** flipping to `'loading'`, guarded by
   `selectedBikeRef`; one call fills both sections), `pendingLabel="Szukam danych roweru…"`,
   `emptyLabel="Nie znaleziono danych"`. **Only on click, never automatic.** The details view still loads stored details via
   `POST /v1/bike/details` on open (now instant, no AI) — treat the empty response as "no data" (description text empty **and**
   no components), not as an error. The search result card (`ResultCard.tsx`) renders the explanation paragraph and the
   accessory chips **only when non-empty** (a popular-list card already passes `accessories: []`).
7. **Generic cache purge**: delete all `endpoint_req_to_body_cache` rows for endpoint `'/v1/bike/details'` (no copy into the
   tables). Script `backend/scripts/purge_details_cache.py` (`--dry-run`, `--url` / `--db`, prints the row count, SQLite and
   PostgreSQL). **Run locally only; production only on the user's explicit go.** The **webscraper** stops writing that cache:
   remove `cache_details` (`bike_store.py`) and its calls in `process_queue.py` / `copy_to_db.py`, the `--sync-cache` option
   of `process_queue.py` (and its code path), `webscraper/centrumrowerowe/tests/test_process_queue_cache.py`, and every doc
   mention (`webscraper/centrumrowerowe/README.md`, `CLAUDE.md` "Generic cache write" / `--sync-cache` bullets, `README.md`).
   After this the discovery pipeline's `bike_detail` rows are read directly by the new `/v1/bike/details`, which is the point
   (they were invisible to it unless cached).
8. **Out of scope**: free-text bike search (AI in `/v1/bike/search` stays for the bike list), equipment endpoints
   (`/v1/equipment/*` stay on the SDK and the generic cache), Ceneo, photos, the expert rating on result cards (TODO-040 — `review/cached`, `ratings.ts`, `useCachedRatings`, ordering), **backfilling `short_description`
   for bikes that already have details** (they show an empty blurb until re-searched — and a stored complete detail set blocks
   `details/search`; accepted), `GET /v1/bike/popular` (keeps `first_sentences`), any deploy (ask the user first), deleting
   old cache rows in production.
9. **Removed from the backend** (only after `grep` shows nothing else uses them): `app/bike_details_finder.py`,
   `app/bike_description_finder.py`, prompts `bike_details.md`, `bike_details_{slug}.md` (8), `bike_details_fields.md`,
   `bike_details_json_example.md`, `bike_description.md` — **but** check `equipment_details_finder.py` /
   `equipment_description_finder.py` / `equipment_categories.py` for shared imports or prompt files first and keep whatever
   the equipment endpoints still need; `scripts/test_details.py` (drives the removed finders) is replaced by the smoke cases
   below. The searcher takes over the prompt as `searcher/app/prompts/bike_details.md` (draft written during the probe — see
   "Probes").

## Contract — files expected to change (disjoint sets per area)

**Searcher** (`searcher/`)
- `app/prompts/bike_details.md` (new; draft already in the worktree, tune if needed)
- `app/details_finder.py` (new) — `find_bike_details(company, model)`: `run_structured(prompt, "Find the full details for:
  {company} {model}", DETAILS_SCHEMA)` (schema = `description`, `short_description`, `sources[{url,title}]`,
  `components[category→subcategories→elements→specs]`, all required), builds the `BikeDescription` shape (decision 3), keeps
  the 8 category shells, caps string lengths, raises `SearcherError` on `ClaudeCliError` (limit error → the existing 400 path)
- `app/repository.py` — `save_details(...)` (bike row if missing, in-place `bike_detail` update incl. `short_description`,
  component replace, one transaction) + `get_stored_details(...)`
- `app/models.py` — verbatim DDL copy incl. `BikeDetails.short_description`, `REQUIRED_TABLES` / column check;
  `app/schemas.py` — response models; `app/main.py` — route `POST /v1/search/details` (+ busy slot, 401/422)
- `scripts/test_searcher.py` — 401 without key and 422 for a blank model on the new route (free, no CLI run)
- `README.md` — `## Endpoints` gets `### POST /v1/search/details` (request example + Flow: `claude -p` × 1, DB write)

**Backend** (`backend/`)
- `app/schemas.py` (`BikeDetailsResponse.short_description`; `BikeDetailsRequest` `max_length=255` if absent), `app/models.py`
  (`BikeDetails.short_description`), `app/repository.py` (`save_bike_details` / `get_bike_details` with the new field,
  `has_complete_details`, `accessory_chips`, `find_bikes_by_details` + search-result builders, `find_bikes_by_brand` if it
  builds `BikeResult`; `_latest_ratings` / `_describe_match` removed), `app/store.py` (`save_search` writes `""` / `"[]"`;
  `_row_to_bike` and the search-cache readers fill `explanation` / `accessories` from details), `app/bike_finder.py` +
  `app/prompts/bike_search.md` (brand + model only — no explanation/accessories; no `match_score`, already gone), `app/searcher_client.py` (`SEARCH_PATHS["details"] = "/v1/search/details"`, `search_details()`
  → `BikeDetailsResponse`, unwrapping `{details, bike_id, saved}`), `app/main.py` (`/v1/bike/details` DB read,
  `/v1/bike/details/search`, imports cleanup), deletions per decision 9
- `scripts/migrate_short_description.py` (new), `scripts/purge_details_cache.py` (new)
- `scripts/test_search.py` — `case_details` (seeded `bike_detail` + components + `short_description` → `POST /v1/bike/details`
  200 with the stored values, no generic-cache row, < 5 s; unknown bike and a bike without details → fast 200 with the empty
  response), `case_details_search` (unknown bike → 404 only — **no paid run**), search and search-cache cases adjusted to the new
  `explanation` / `accessories` rule (keep TODO-040's `case_review_cached` untouched) (seeded short description + components → chips; bike without details → `""` / `[]`)
- `scripts/test_searcher_client_details.py` (new, pytest via `pytest.ini`; model it on `test_searcher_client_review.py`):
  `search_details` with a mocked httpx transport — request path/header, unwrapping of `{details, …}`, single-flight, busy
  mapping (503 and 429), shared cap, error mapping, limit 400, body validation
- `scripts/test_details.py` removed/replaced (decision 9); any test that imports a removed finder updated

**Frontend** (`frontend/`)
- `src/types.ts` (`BikeDetailsResponse.short_description`), `src/App.tsx` (`searchDetails`, empty-details handling, pass
  `onSearchDetails`), `src/components/BikeDetailsView.tsx` (both buttons' `onRequested` / `pendingLabel` / `emptyLabel`),
  `src/components/ResultCard.tsx` (explanation/chips only when non-empty — leave TODO-040's `expertRating` layout, `ratings.ts`,
  `hooks/useCachedRatings.ts` and the result ordering alone); `RequestDataButton.tsx` only if a label is still
  hard-coded per section

**Webscraper** (`webscraper/centrumrowerowe/`)
- `bike_store.py`, `process_queue.py`, `copy_to_db.py` (remove `cache_details`, `--sync-cache`),
  `tests/test_process_queue_cache.py` (delete), other tests that assert the cache write (adjust), `README.md`

**Docs** (written last; Polish write-up): `CLAUDE.md` (Backend / Searcher / Frontend tables, endpoint sections, Bike discovery
bullets, Backend Setup migration list + deploy order), `README.md`, `backend/README.md` (`## Endpoints`: rewrite
`/v1/bike/details`, add `/v1/bike/details/search`, each with a raw HTTP example and a **Flow** list; migration + purge
scripts), `searcher/README.md`, `frontend/README.md` (Polish label map + API list), `backend/app/DB_MIGRATION.md`,
`docs/DETAILS_SEARCHER_MIGRATION.md`.

## Probes
Probed 2026-09-30 with `claude` 2.1.286, through the searcher's own argv (`claude -p`, `--output-format json`,
`--json-schema`, `--tools WebSearch,WebFetch`, `--allowedTools` the same, `--permission-prompts none`, `--strict-mcp-config`,
`--setting-sources ""`, `--model claude-haiku-4-5-20251001`), system prompt = the draft `searcher/app/prompts/bike_details.md`
(merge of `bike_details.md` + the 8 `bike_details_{slug}.md` + `bike_description.md`), user message `Find the full details
for: <bike>`, schema = `{description, short_description, sources[], components[8 categories]}` (probe runner and schema were
scratchpad files, not committed). **One run each** (2 of the 4 allowed):

| Bike | Wall time | Turns | Cost | Categories | Elements / specs | Element descr. filled | Description | Short description |
|---|---|---|---|---|---|---|---|---|
| KROSS Esker Eco | 53 s | 7 | $0.12 | 8 of 8 | 18 / 15 | 10 of 18 | Polish, 5 sentences | Polish, 2 sentences |
| Trek Marlin 5 | 142 s | 12 | $0.18 | 8 of 8 | 18 / 40 | 17 of 18 | Polish, 4 sentences (Gen 3) | Polish, 2 sentences |

- Elements per category (both bikes): Frame 2–3, Drivetrain 5–6, Brakes 3, Wheels 3, Cockpit 2, Saddle & Seatpost 1,
  **Lighting 0**, Accessories 1. An empty Lighting is expected when no reflector info exists (the old per-category prompt had
  the same gap) — keep the empty category shell; it is not a failure.
- JSON parsed both times via `structured_output`; `sources` returned 2 (KROSS: kross.pl, kross-europe.eu) and 4 (Trek:
  trekbikes.com, nrcbikes, evanscycles, 99spokes) real URLs. Short descriptions are genuine condensations (not the first two
  sentences). KROSS specs are sparse (15) because Polish shop pages give a flat spec list; acceptable, no retry.
- **Verdict: ONE run is enough** (53–142 s, far under the 300 s timeout, $0.12–0.18, no dropped categories) — the split
  (description+short / components) was not needed and was not probed. Keep `SEARCHER_CLI_TIMEOUT` at 300 s.
- Recommended CLI shape: one `run_structured` call, tools `WebSearch,WebFetch` (the defaults in `claude_cli.py`), schema as
  above, prompt budget "about 6 searches / 3 fetches" (already in the draft), no Playwright.
- Caveats for the implementer: (1) the draft ties no citation to a sentence — `BikeDescription` is built from `sources`
  (decision 3); (2) Haiku's Polish has occasional stylistic slips, same as the SDK version; (3) two runs are a small sample —
  re-run the prompt on 1–2 more bikes (an e-bike, a non-Polish brand) in the real-searcher QA and tighten the prompt if
  categories drop; (4) the model sometimes returns a nearby generation (Marlin 5 Gen 3) — acceptable.

## Order of work
This file → probe (done above) → implement: searcher + backend DB/model/migration first (disjoint), then backend API/search
changes, then frontend, webscraper cleanup in parallel → migration and purge scripts on a **copy** of the local DB (SQLite and
local PostgreSQL `biker-pg`) → smoke tests + pytest → `/manual-tester` twice: real stack (real searcher, one paid run) and
fake-searcher stack → PR → **ask the user before deploying** → docs + Polish write-up.
Deploy checklist to record: Cloud SQL on-demand backup → `migrate_short_description.py` on Cloud SQL through the proxy (first)
→ deploy searcher + backend together → frontend; `purge_details_cache.py` on Cloud SQL **only on the user's go**.

## Acceptance criteria
- [ ] `POST /v1/bike/details` returns the stored details (description, components, `short_description`) with no AI call and no
      generic-cache row, in < 5 s; unknown bike / bike without details → 200 with the empty response.
- [ ] `POST /v1/bike/details/search`: unknown bike → 404 before any searcher call; complete stored details → returned with no
      searcher call; not configured / unreachable / busy (incl. Cloud Run 429) → 503 fixed detail; searcher failure → 502 with
      its detail; subscription limit → 400; success returns the stored details; concurrent identical requests share one search.
- [ ] `POST /v1/search/details` stores only a usable result, updates `bike_detail` in place, replaces components, leaves
      photos alone, creates the bike row if missing, writes/deletes nothing on an empty result; `short_description` is 2 Polish
      sentences written by the model; all 8 categories present (possibly empty).
- [ ] `bike_detail.short_description` exists after `migrate_short_description.py` (idempotent, `--dry-run`, SQLite +
      PostgreSQL); the searcher refuses to start without it; `BikeDetailsResponse.short_description` flows backend → frontend.
- [ ] `POST /v1/bike/search` and `GET /v1/bike/search-cache`: `explanation` = stored short description or `""`; `accessories` =
      drivetrain / brakes / frame material chips from stored components, only those present; `search_bike_rating_cache` rows are
      written with `""` / `"[]"` (table and columns kept, no migration); response shape unchanged (no `match_score`).
- [ ] TODO-040 behaviour intact: result cards still show the expert rating from `POST /v1/bike/review/cached` and the same
      ordering; `ratings.ts`, `useCachedRatings.ts` and `review/cached` are not modified.
- [ ] Details view: the Opis and Komponenty buttons run ONE shared search on click only ("Szukam danych roweru…"), the result
      fills both sections, empty result → "Nie znaleziono danych", failure → clickable again, a late result for another bike is
      dropped; the search result card hides an empty explanation and empty chips.
- [ ] `purge_details_cache.py --dry-run` counts and a real run (local only) deletes exactly the `'/v1/bike/details'` rows;
      the webscraper no longer writes the cache and has no `--sync-cache`; its tests pass.
- [ ] Equipment endpoints and the popular-bikes endpoint unchanged; removed backend finders/prompts leave no dangling import.
- [ ] Smoke tests + pytest as listed; at most one paid searcher run in the whole suite; `/manual-tester` green on the real and
      the fake-searcher stack.
- [ ] Docs updated per the Documentation Update Policy and the Polish write-up `docs/DETAILS_SEARCHER_MIGRATION.md`.
