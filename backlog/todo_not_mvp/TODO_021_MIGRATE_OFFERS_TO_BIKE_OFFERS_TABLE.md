# TODO-021 — Migrate Offer Persistence from the Blob Cache into `bike_offers`

## Goal
Make the four offer endpoints persist their results as **rows in `bike_offers` +
`bike_offer_photos`** (joined to the shared `bikes` identity) instead of opaque JSON blobs in the
generic `cache` table, backfill the 25 existing cached offer responses, and repoint
`store.find_offer_prices` at the new table — proving parity before the blob path is removed.

Scope is **offers only**. `search_cache` and `bike_details_cache` are untouched (details are
TODO-019's job).

## Why — what the investigation found

**`bike_offers` is empty because nothing has ever written to it.** It is dead schema, not a broken
write path:

- `BikeOffer` / `BikeOfferPhoto` are defined at `app/models.py:131-164` and the tables *are* created
  at startup — `main.py:43,57` calls `init_db()` → `Base.metadata.create_all()` (`models.py:45-48`)
  against the same `backend/cache.db` the legacy layer uses (`models.py:29-34`).
- The only ORM reference to them is a **dead import** at `app/repository.py:15-16`. Neither name
  appears again in that file; `repository.py` defines exactly five functions (`save_search`,
  `get_search_by_query`, `find_bikes_by_brand`, `save_bike_details`, `get_bike_details`) — none of
  them offer-related, and `main.py:38-42` imports its helpers from `.store` anyway.
- Everything named `BikeOffer` in the finders (`bike_offer_finder.py`, `bike_offer_ceneo_finder.py`,
  `bike_offer_decathlon_finder.py`, `bike_used_finder.py`, `allegro_image_fetcher.py`,
  `olx_image_fetcher.py`) is the **Pydantic** `schemas.BikeOffer` (`schemas.py:238`) — a name
  collision with the ORM class, no persistence involved.
- `app/DB_MIGRATION.md:184` still lists "Add new Offer endpoints to populate `bike_offers`" as a
  *next step*. The endpoints were then written (`main.py:257-322`) against `app/cache.py`, per the
  `CLAUDE.md` rule that every Anthropic-API endpoint must use the SQLite cache. That rule and the
  ORM design conflicted, and `cache.py` won.

**Where the offer data actually lives.** All four endpoints follow the identical
`get_cached` → call finder → `set_cached` shape (`main.py:261/270`, `278/287`, `295/304`,
`312/321`), keyed on `_fields = {"company", "model"}` and gated on `if result.offers:`. Current
contents of `backend/cache.db`:

| Endpoint | `cache` rows | Offers inside them |
|---|---|---|
| `/v1/bike/offer` (allegro.pl) | 7 | 7 |
| `/v1/bike/ceneo` | 7 | 7 |
| `/v1/bike/decathlon` | 4 | 4 |
| `/v1/bike/used` (olx.pl) | 7 | 24 |
| **total** | **25** | **42** |

`bike_offers` = 0 rows. `bike_offer_photos` = 0 rows. (`cache` holds 163 rows overall; the other
138 are search/details/review/equipment/parse responses and stay where they are.)

**The blob shape is actively costing us.** Every offer field the endpoints return is already a known,
typed column on `models.BikeOffer` — `price`, `is_new`, `url`, `source`, `city`, `photos` — so the
JSON blob buys nothing and loses:

1. **No queryability.** `store.find_offer_prices` (`store.py:173-198`) has to `SELECT response FROM
   cache WHERE endpoint IN (?,?,?,?) AND request = ?`, then `json.loads` every row and re-parse every
   price string through `price_parse.parse_price` — at request time, on the TODO-009 DB-first search
   path. With rows it is one indexed `SELECT MIN(price)`.
2. **No cross-bike queries at all.** "cheapest offer per source", "all offers under X", "offers seen
   in the last week" are impossible against a blob keyed by `{company, model}`.
3. **No refresh, ever.** `cache.py:90` writes with `INSERT OR IGNORE` and `get_cached`
   (`cache.py:73-84`) applies **no TTL** — the `cache` table has a `time_stored` column that nothing
   reads. A price scraped once is pinned forever and can never be updated. Offers are the one kind of
   data in this app that genuinely goes stale.
4. **No identity join.** Offers, search results, and details for the same bike share nothing, even
   though `Bike.offers` (`models.py:65`) exists precisely for that.

## Behaviour after this task
- The four offer endpoints read and write `bike_offers` + `bike_offer_photos` via a new
  `repository` offer API, keyed through the shared `bikes` row.
- Offers carry a real TTL and can be **refreshed** — a re-fetch replaces the stored offers for that
  `(bike, source)` instead of being silently ignored.
- `store.find_offer_prices` returns `list[float]` from a numeric column, not from JSON re-parsing.
- The 25 existing cached responses (42 offers) are backfilled, keeping their original age.
- The four `cache` endpoint keys are deleted; response payloads are unchanged and the frontend is
  untouched.

## Known problems to resolve before cutover

These are real, found in the code — each needs a decision, not a hypothesis:

1. **`price` is `String(100)`** (`models.py:138`). `DB_MIGRATION.md:171` advertises
   `order_by(BikeOffer.price)`, which sorts lexicographically — `"1199 zł"` before `"999 zł"`. Add a
   numeric `price_value = Column(Float, nullable=True)` populated via `price_parse.parse_price`, and
   keep the raw string for display. `parse_price` returning `None` must stay non-fatal (the
   `price_max` gate treats it leniently today).
2. **`url` is globally `unique=True`** (`models.py:140`) *and* covered by
   `UniqueConstraint("bike_id", "url")` (`models.py:150`). The global uniqueness is strictly stronger
   and wrong: the same marketplace URL can legitimately be reached from two bike identities (e.g. a
   Decathlon listing found under both `Rockrider`/`ST 100` and a family query). Drop the global
   `unique=True`, keep the composite constraint. This is a schema change — fold it into the
   migration script.
3. **Key normalisation.** `cache._normalise` (`cache.py:62`) and `store._norm` lower-case the
   `{company, model}` key, while `bikes` has a **case-sensitive** `UNIQUE(brand, model)`
   (`models.py:67`) and already holds title-case test rows (`Trek`/`Marlin 5`, `Canyon`/`Grizl CF 7`,
   `Canyon`/`Grizl`) from `scripts/test_db_models.py` and `scripts/demo_cache_persistence.py`. A
   naive backfill creates two identities per bike. Resolve exactly as TODO-019 resolves it for
   details, and share the helper — do not invent a second scheme. Responses must keep echoing the
   caller's casing.
4. **No TTL column on `BikeOffer`** (unlike `BikeDetails.ttl_seconds`, `models.py:110`). Add one and
   pick the value deliberately — offers are the most volatile data in the app; 30 days (the details
   TTL) is wrong for a price. Suggest 24 h–7 d, stated in the task PR.
5. **`city` is OLX-only** (`schemas.py:238` block; only `bike_used_finder.py:79` sets it). It is
   already nullable (`models.py:142`) — assert it round-trips as `None` for the other three sources,
   not `""`.
6. **`created_at_list`** (`models.py:144`) has no source in any finder — no scraper extracts the
   marketplace listing date. Either populate it or leave it explicitly `NULL` and say so; do not
   leave a column that looks populated.
7. **Empty-result semantics.** Today `if result.offers:` means an empty result is never cached and is
   re-fetched every time. Rows preserve that by simply having no rows — but the read path must then
   distinguish "no offers stored" from "never looked", or the refresh behaviour silently changes.
   Decide and encode it (a `bike_offer_fetches` marker row, or accept the re-fetch).

## Scope

### Backend
- `app/models.py` — add `price_value` (Float, nullable) and `ttl_seconds` to `BikeOffer`; drop the
  global `unique=True` on `url` (items 1, 2, 4).
- `app/repository.py` — new `save_offers(company, model, source, response)` and
  `get_offers(company, model, source)` mirroring the `save_bike_details` / `get_bike_details`
  signatures so `main.py` can swap by import; plus `find_offer_prices(brand, model)` over the new
  columns. Delete the dead `BikeOffer`/`BikeOfferPhoto` import if it is still unused after this.
- `app/main.py` — the four endpoints (`main.py:257-322`) call the repository helpers instead of
  `get_cached` / `set_cached`. Keep the exact response models and the log lines.
- `app/store.py` — `find_offer_prices` (`store.py:173-198`) delegates to the repository; the
  `_OFFER_ENDPOINTS` blob scan (`store.py:170`) is removed once parity is green.
- `scripts/migrate_offers.py` (new, one-off, idempotent) — read the 25 offer rows out of `cache`,
  create/attach `bikes` rows, insert `bike_offers` + `bike_offer_photos` (photo array index →
  `display_order`), map `time_stored` → `created_at`, parse `price` → `price_value`, then
  `DELETE FROM cache WHERE endpoint IN (the four)`. Runs the schema change from items 1–2.
- `CLAUDE.md` — update the `app/cache.py`, `app/store.py` and offer-endpoint sections; the
  "must use the SQLite cache in `app/cache.py`" rule now has a documented exception for offers.
- `backend/README.md` — update the four offer endpoints' cache notes; the `## Endpoints` section and
  its per-endpoint **Flow** lists must stay accurate.
- `app/DB_MIGRATION.md` — mark the offers half done; strike the stale "next step" at line 184.

### Parity assertion (the point of this task)
- `scripts/test_offers_parity.py` (new pytest) — for each of the 25 cached `(company, model,
  endpoint)` triples, read the same bike through the blob path and the repository path and assert the
  two response objects are **equal field for field**: `offers[]` in the same order, each with
  identical `brand`, `model`, `price` (raw string), `is_new`, `url`, `source`, `city`, and `photos`
  in the same order; plus `info`. Include the OLX bike with the most listings (24 offers across 7
  rows) and at least one offer with `photos: []`. Assert `find_offer_prices` returns the **same
  float multiset** from both paths for every bike. Run against a copy of `cache.db` in the scratchpad.
  This test is deleted with the blob path once green — it exists to gate the cutover.
- `scripts/test_search.py` — add the smoke test CLAUDE.md requires: `POST /v1/bike/offer` twice for
  the same bike, HTTP 200 both times, byte-identical JSON on the second (stored-result) call. Same
  for `/v1/bike/used`.

### Frontend
None. `BikeOffer` payload shape is unchanged.

## Out of scope
- **`search_cache` → `bike_results`.** `BikeResult` has no `query` column and
  `repository.get_search_by_query` (`repository.py:70-72`) has an **empty `.filter()`** — it returns
  every row regardless of query. Its own task.
- **`bike_details_cache` → `bike_details`.** That is TODO-019. If it lands first, reuse its
  identity-normalisation helper rather than writing a second one; if this task lands first, TODO-019
  reuses ours. Neither blocks the other.
- The remaining 138 non-offer rows in `cache` (search, details, review, equipment, parse) stay on
  `cache.py`.
- Equipment offers — there are none, by design.

## Acceptance criteria
- [ ] `bike_offers` holds 42 rows after `scripts/migrate_offers.py`; `bike_offer_photos` holds every
      photo in its original order; re-running the script changes nothing.
- [ ] No `cache` rows remain for the four offer endpoints; the other 138 rows are untouched.
- [ ] `scripts/test_offers_parity.py` passes for all 25 responses, including the 24-offer OLX bike
      and an offer with `photos: []`.
- [ ] `find_offer_prices` returns identical float multisets before and after, and no longer reads the
      `cache` table.
- [ ] Re-fetching an offer for a bike **replaces** its stored offers rather than being ignored, and a
      row past its TTL is treated as a miss.
- [ ] `city` is `None` for allegro/ceneo/decathlon rows and populated for OLX rows.
- [ ] The four endpoints return byte-identical JSON to the pre-migration responses.
- [ ] `scripts/test_search.py` offer + used smoke tests return HTTP 200 twice with identical JSON.
- [ ] `CLAUDE.md`, `backend/README.md`, `app/DB_MIGRATION.md` updated.
