# TODO-034 — Popular bikes on the home page

**Branch:** `feature/popular-bikes` · **Worktree:** `biker-wt/feature-popular-bikes` (backend 8001, frontend 5174)

## Confirmed intent (interview 2026-09-28)

- **Outcome:** before the first search the home page shows, under the search form, a section
  "Najpopularniejsze rowery" with 3 cards that look like search results; a click opens the details
  view. The section is hidden while a search runs and while results are shown; it comes back after
  "Nowe wyszukiwanie" / reset.
- **Data:** new table `bike_popular` (`bike_id` FK → `bike.id`, unique; `position`), created by
  `init_db()` like `bike_missing_request`. New `GET /v1/bike/popular` returns the list ordered by
  `position` with `brand`, `model` and a short description taken from `bike_detail`. Pure DB read,
  no AI, no generic cache.
- **Card:** in place of the match score the card shows the **expert rating in points**, e.g.
  "8.4 / 10", from the `rating` field of `POST /v1/bike/review`, which the UI calls separately for
  each of the 3 bikes. A dash while the call is pending, "brak oceny" on error or rating 0. Under the
  points the first 1–2 sentences of the description.
- **Seed:** `backend/scripts/seed_popular_bikes.py` inserts 3 bikes that have complete data in the
  local PostgreSQL (`biker-pg`): details, photos, and a review already in the generic cache with a
  real `rating`. Prod gets the same only after the user decides to deploy.
- **Success:** `/manual-tester` green — endpoint 200 with 3 bikes, 3 cards with points on the home
  page, gone after a search, click opens details. Smoke test in `backend/scripts/test_search.py`.
- **Out of scope:** computing popularity from data (clicks, searches), an admin panel for the list,
  photos on the cards, changes to the details view, deployment.

## Contract

### Table `bike_popular` (`backend/app/models.py` `BikePopular`)

| column | type | notes |
|---|---|---|
| `id` | int PK | |
| `bike_id` | int FK → `bike.id` ON DELETE CASCADE | unique — a bike is listed at most once |
| `position` | int, not null, default 0 | display order, 1 = first; not unique on purpose |
| `created_at` | datetime | |

### `GET /v1/bike/popular`

- No parameters. Response `PopularBikesResponse`:

```json
{ "bikes": [ { "brand": "Giant", "model": "Revolt Advanced Pro", "description": "First one or two sentences of the stored description." } ] }
```

- Rows ordered by `position`, then `id`. `brand` / `model` are the `bike` row's (display casing).
- `description` = the `text` of the bike's stored `BikeDescription` JSON (`bike_detail.description`)
  cut to its first two sentences; `""` when the bike has no details row.
- Empty table → `200 { "bikes": [] }`. A DB error → `200 { "bikes": [] }` + ERROR log, never a 500.
- No AI call, no generic cache, no TTL.

### Frontend

- On app load `GET /v1/bike/popular` once (kept in App state, so coming back from the details view
  does not refetch). For every bike `POST /v1/bike/review { company: brand, model }` → `rating`.
- Section visible in the search view only when no search is running and no results are shown
  (`appState` idle or error). Cards reuse `ResultCard`'s look: the numeral slot shows the expert
  `rating` ("8.4" over "/ 10"), the bar label reads "Ocena eksperta", no "Najlepsze dopasowanie"
  badge; pending → "—", error / rating 0 → "brak oceny". The explanation slot shows `description`.
- Click → the same `handleBikeSelect` as a search result.

## Files

- backend: `app/models.py` (done), `app/schemas.py`, `app/popular_repository.py`, `app/main.py`,
  `scripts/seed_popular_bikes.py`, `scripts/test_search.py` (`case_popular`), `backend/README.md`
- frontend: `src/types.ts`, `src/App.tsx`, `src/components/PopularBikesSection.tsx`,
  `src/components/ResultCard.tsx`, `frontend/README.md`
- docs: `CLAUDE.md`, `README.md`
