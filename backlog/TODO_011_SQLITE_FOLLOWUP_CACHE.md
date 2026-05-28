# TODO-011 — SQLite Cache for Deeper Follow-up Queries

## Goal
Extend persistence so prior search + component-detail results can power deeper follow-up queries without re-fetching from Claude / the web.

## Current state
- A generic response cache already exists: `app/cache.py` — a single `cache(endpoint, request, response, time_stored)` table keyed by endpoint + normalised request. It de-dupes identical endpoint calls but is **not** queryable by bike attributes and does not model "follow-up" relations.

## Behaviour
- Add dedicated, queryable tables:
  - `search_cache` — keyed by query / enriched query; stores the returned bikes.
  - `bike_details_cache` — keyed by (company + model); stores components / description / photos.
- Enable follow-up queries that read from these tables (e.g. "compare components of bikes from my last search", "show a cheaper alternative in the same category") without new web/Claude calls when the data is already present.
- Keep the existing generic cache; this is an additive, semantically-richer layer.

## Scope
### Backend
- `app/cache.py` (or new `app/store.py`) — new tables + typed read/write helpers + lookup-by-attribute.
- `app/main.py` — write to these tables on search/details happy paths; add follow-up read path(s).
- `backend/scripts/test_search.py` — smoke test: follow-up read returns cached data fast.
- `backend/README.md` — document the tables + any new follow-up endpoint.

## Open questions / Notes
- Which concrete follow-up queries should v1 support? (pick 1–2 to scope it)
- New endpoint for follow-up, or extend existing search with a "from cache" mode?
- TTL / staleness policy for these tables?

## Acceptance criteria
- [ ] `search_cache` + `bike_details_cache` tables created on startup.
- [ ] Search/details results persisted to them on the happy path.
- [ ] At least one follow-up query served purely from cache (no web/Claude call).
- [ ] Smoke test + README updated.
