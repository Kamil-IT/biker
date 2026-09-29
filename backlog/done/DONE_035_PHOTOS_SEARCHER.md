# TODO-035 — Bike photos through the searcher service (same pattern as TODO-031 / 032 / 033)

Reference write-ups: `docs/OLX_SEARCHER_MIGRATION.md`, `docs/DECATHLON_SEARCHER_MIGRATION.md`,
`docs/ALLEGRO_SEARCHER_MIGRATION.md`; this task's own: `docs/PHOTOS_SEARCHER_MIGRATION.md`. Branch
`feature/photos-searcher`. Merged as PR #115 (`main` `1781f00`) and deployed to GCP on 2026-09-29.

## Goal (as the user stated it)
Bike photos should work like the Allegro offers: a fast database read when a bike is opened, and a paid search
(`claude -p` on the subscription plus Playwright) only when the user clicks **Poproś o dane**. Until now `POST /v1/bike/details`
ran the photo finder itself (an Anthropic SDK `web_search` call plus a Playwright scrape) on every uncached details view,
with an API key that has no credits left.

## Decisions (interview, 2026-09-29)
1. **Same searcher service** — a new route `POST /v1/search/photos` inside the existing `biker-searcher`, not a new Cloud Run
   service (same image, same secrets, no new IAM).
2. **Concurrency 2 → 10 everywhere**: searcher `SEARCHER_MAX_CONCURRENT` default, backend `SEARCHER_MAX_INFLIGHT` /
   `DEFAULT_MAX_INFLIGHT`, Cloud Run `--max-instances 10` (still `--concurrency 1`), `.env.example` / compose values.
3. **Photos stay in `bike_detail_photos`**, re-keyed from `bike_detail_id` to `bike_id INTEGER NOT NULL REFERENCES bike(id)
   ON DELETE CASCADE` (indexed). A migration script handles SQLite and PostgreSQL. Photos no longer need a `bike_detail` row.
4. **No TTL on photos, and the 30-day details TTL (`TTL_DETAILS`) is removed from the code** — stored details are returned
   whatever their age. The search TTL is untouched.
5. **A photo is never deleted or replaced.** The searcher writes photos only for a bike that has none; if the bike already
   has photos it returns the stored ones without running a search. A search that finds nothing writes nothing.
6. **The scraper is ported 1:1** from `backend/app/bike_photos_finder.py` (same `_IMG_SRC` / `_SKIP` regexes, max 8, 4 s
   wait, same user agent), **without** the improvements from `docs/bikes/pipeline/photo_extract.py`. Step 1 (find the
   manufacturer product URL) goes through the searcher's `claude -p` runner instead of the Anthropic SDK.
7. **Equipment photos are out of scope** — `/v1/equipment/*` and `equipment_photos_finder.py` are untouched; the backend keeps
   Playwright and `BROWSER_SLOTS` for them.
8. Out of scope: a separate Cloud Run service, photos in search results (`TODO_ISSUE_008`), any deploy, any write to the
   production database.

## Scope
- **Backend**: `POST /v1/bike/photos` (`{company, model}` → `{photos: [url, …]}`, pure DB read, `ORDER BY display_order, id`,
  unknown bike / nothing stored / DB error → 200 `{photos: []}`, no AI, no generic cache, no TTL) and
  `POST /v1/bike/photos/search` (404 `"Bike not found"` before any searcher call, then proxy; 503 `"Photos searcher is not
  configured"` / `"Photos searcher unavailable"` / `"Photos searcher is busy — try again in a moment"`, 502 with the
  searcher's detail; never cached). Validation: non-empty, ≤ 255 chars (422). `BikePhotosRequest` / `BikePhotosResponse`
  in `schemas.py`; new `app/photos_repository.py` (`get_bike_photos`, Python normalisation via `repository._find_bike_id`).
  `BikeDetailsResponse` loses `photos`; `/v1/bike/details` runs two calls in parallel (components + description);
  `/v1/bike/details-cache` returns no photos. `bike_photos_finder.py` and `prompts/bike_photos.md` leave the backend.
- **Searcher**: `POST /v1/search/photos` → `{photos, bike_id, saved}` (`X-Searcher-Key`, shared slots, stored photos answered
  before the busy check, single-flight per bike); `photos_finder.py` + `prompts/bike_photos.md`; `get_stored_photos` /
  `save_photos` (insert-only, under a row lock on the bike).
- **Database**: `backend/scripts/migrate_photos_bike_id.py` — SQLite and PostgreSQL, idempotent, `--dry-run`, row-count and
  row-by-row verification, one transaction. `save_bike_details` stops writing photos; `get_bike_details` stops returning them.
- **Frontend**: on opening the details view fetch `POST /v1/bike/photos`; the gallery renders those URLs in order; empty →
  `RequestDataButton` (`MissingType.photos`, `onRequested`, `pendingLabel="Szukam zdjęć…"`, "Nie znaleziono zdjęć" when the
  search resolves empty, clickable again when it throws); `selectedBikeRef` guard; `photos` removed from the TS
  `BikeDetailsResponse`. UI strings stay Polish; the equipment view is unchanged.
- **Infra**: `scripts/deploy.ps1` `--max-instances 10` for `biker-searcher`; compose and `.env.example` values.
- **Docs**: `CLAUDE.md`, `README.md`, `backend/README.md`, `searcher/README.md`, `frontend/README.md`,
  `backend/app/DB_MIGRATION.md`, `docs/PHOTOS_SEARCHER_MIGRATION.md`.

## Acceptance criteria
- [ ] `POST /v1/bike/photos` returns the stored photos of a bike in `display_order` with no AI call and no generic-cache
      row, in < 5 s; an unknown bike and a bike without photos are a 200 `{photos: []}`.
- [ ] `POST /v1/bike/photos/search`: unknown bike → 404 before any searcher call; searcher not configured / unreachable /
      busy → 503 with the fixed detail; searcher failure → 502; success returns the stored photos.
- [ ] `POST /v1/search/photos` for a bike that already has photos returns them with `saved: 0`, no CLI run, no browser; for a
      bike without photos it stores ≤ 8 photos; a search that finds nothing writes nothing; existing photos are never changed.
- [ ] `POST /v1/bike/details` and `/details-cache` responses have no `photos` key; details no longer expire.
- [ ] `migrate_photos_bike_id.py` migrates a copy of the local database (SQLite and PostgreSQL) with every photo keeping its
      id, url, order and bike; a second run changes nothing; `--dry-run` writes nothing.
- [ ] The searcher refuses to start on an unmigrated database and the backend answers `{photos: []}` with an ERROR log naming
      the script until it has run.
- [ ] Opening a bike shows stored photos without a search; an empty gallery shows the button; a click records `photos` via
      `/v1/bike/missing` and runs the photo search; found photos replace the button; an empty result shows "Nie znaleziono
      zdjęć"; a failure makes the button clickable again; a late result for another bike is dropped.
- [ ] Concurrency is 10 in the searcher, the backend and `deploy.ps1` (`--max-instances 10`, `--concurrency 1`).
- [ ] Equipment details still work unchanged (backend scraper and `BROWSER_SLOTS`).
- [ ] Smoke tests updated (`backend/scripts/test_search.py` `case_photos` / `case_photos_search`, `test_details.py`,
      `searcher/scripts/test_searcher.py`); no new paid searcher run added.
- [ ] Docs updated per the Documentation Update Policy; deploy checklist recorded (migration on Cloud SQL **before** deploying
      the new backend and searcher).
