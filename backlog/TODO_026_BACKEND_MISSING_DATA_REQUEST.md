# TODO-026 — Backend: record user requests for missing bike data

## Goal
When a section of the bike details view has no data (slow or empty), the user can click "Request data". The backend
stores that request per bike and per missing section, with a counter. This shows which data for which bikes users want
most, so we know what to fill in first. Frontend part: TODO-027.

## Decisions (agreed 2026-09-24)
1. **Endpoint** `POST /v1/bike/missing`, body `{company, model, missing_type}`, returns
   `200 {bike_id, missing_type, counter}`. No AI call, no cache (`get_cached`/`set_cached` are not used).
2. **New table** (e.g. `bike_missing_request`): `id`, `bike_id` (FK → `bike.id`), `missing_type` (string), `counter` (int),
   with `UNIQUE(bike_id, missing_type)`.
3. **Upsert**: the first request for `(bike_id, missing_type)` creates a row with `counter = 1`. Every later request adds 1.
4. **Bike lookup** by `company` + `model` in the existing `bike` table. **No** get-or-create. The bike is always saved at
   search time (`save_search` → `_get_or_create_bike`), before the user can open details.
5. **Bike not found** (only after a swallowed `save_search` failure, e.g. locked SQLite or a missing migration): log at
   **ERROR** and return `200 {bike_id: null, missing_type, counter: 0}`. Nothing is written.
6. **`missing_type` is a free string** chosen by the frontend. The enum (`photos | description | components | review |
   offers_new | offers_used`) lives in the frontend (TODO-027). The backend only validates: trimmed, not empty,
   max 64 characters. Anything else → 422.
7. **No spam protection**: every call adds 1. The frontend stops repeat clicks.

## Scope
**Backend**
- `backend/app/models.py`: new model + `UNIQUE(bike_id, missing_type)`.
- `backend/app/schemas.py`: `MissingDataRequest` (`company`, `model`, `missing_type` + validation) and
  `MissingDataResponse` (`bike_id: int | None`, `missing_type`, `counter`).
- `backend/app/repository.py`: `record_missing_request(company, model, missing_type)`: look up the bike, upsert,
  return the counter. Look the bike up the same way the rest of `repository` does (consistent casing and normalisation).
- `backend/app/main.py`: route `POST /v1/bike/missing`.
- Make sure the table is created on an existing `cache.db` (`create_all` creates new tables; check whether
  `scripts/migrate_bike_details.py` / `DB_MIGRATION.md` needs a note).
- Smoke test in `backend/scripts/test_search.py`: call twice for a bike that exists → HTTP 200, `counter` goes up by 1.
  Call for a bike that does not exist → 200, `bike_id: null`, `counter: 0`.

**Docs**: `backend/README.md` (`## Endpoints`: raw HTTP example + Flow, which has no outbound HTTP calls), `README.md`,
`CLAUDE.md` (endpoint list, schemas, repository).

## Out of scope
- Rate limiting and user/session identification
- An endpoint to read or list requests (admin panel)
- Timestamps (`created_at` / `updated_at`)
- Starting the AI pipeline automatically after a request
- All frontend work (TODO-027)

## Acceptance criteria
- [ ] First `POST /v1/bike/missing` for a bike + type → 200, `counter: 1`. Second → `counter: 2`, still one DB row.
- [ ] Different `missing_type` for the same bike → a separate row with its own counter.
- [ ] Bike not in `bike` → 200, `bike_id: null`, `counter: 0`, an ERROR line in the log, nothing written.
- [ ] Empty or whitespace-only `missing_type`, or one longer than 64 characters → 422.
- [ ] No Anthropic API call and no `cache` table write for this route.
- [ ] Works on an existing `cache.db` (the table is created at startup or by the migration).
- [ ] Smoke test added to `backend/scripts/test_search.py` and passing.
- [ ] Docs updated (see Scope).
