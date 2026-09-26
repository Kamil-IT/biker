"""Backend smoke tests — exactly ONE happy path per endpoint.

Run against a live local server (uvicorn app.main:app --port 8000):

    python scripts/test_search.py          # DB / cache / searcher cases only — no Anthropic API calls
    python scripts/test_search.py --ai     # also the cases that call the Anthropic API (billed)

Every case seeds its own namespaced fixture rows and deletes them afterwards, so
it passes on a cold or aged database. Endpoints covered here:

  no API   /v1/bike/search (DB hit) · /v1/bike/search-cache · /v1/bike/details-cache
           /v1/bike/missing · /v1/bike/used/olx · /v1/bike/used/search (404 only — no paid run)
           /v1/bike/decathlon · /v1/bike/decathlon/search (404 + foreign-brand skip always; the
           live house-brand search — the ONE paid searcher run in the suite — only when the searcher is up)
           /v1/bike/allegro · /v1/bike/allegro/search (404 only — no paid run)
  --ai     /v1/bike/search (free text) · /v1/bike/parse · /v1/bike/ceneo

The other endpoints have their own single-happy-path script: test_details.py
(/details), test_review.py (/review), test_equipment.py (/equipment/details),
test_equipment_review.py (/equipment/review).
Exit code 0 = every selected case passed (skips do not fail); 1 = a failure.
"""
import json
import os
import re
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")  # same DATABASE_URL as the server under test

from sqlalchemy import text  # noqa: E402

from app.models import get_engine  # noqa: E402
from app.schemas import (  # noqa: E402
    BikeCategory, BikeDescription, BikeDetailsResponse, BikeSubcategory, ComponentElement, SpecItem,
)
from app.repository import save_bike_details  # noqa: E402

BASE = os.getenv("BIKER_API_URL", "http://localhost:8000").rstrip("/")
SEARCH_URL = f"{BASE}/v1/bike/search"
SEARCH_CACHE_URL = f"{BASE}/v1/bike/search-cache"
DETAILS_CACHE_URL = f"{BASE}/v1/bike/details-cache"
MISSING_URL = f"{BASE}/v1/bike/missing"
USED_URL = f"{BASE}/v1/bike/used/olx"
USED_SEARCH_URL = f"{BASE}/v1/bike/used/search"
PARSE_URL = f"{BASE}/v1/bike/parse"
CENEO_URL = f"{BASE}/v1/bike/ceneo"
DECATHLON_URL = f"{BASE}/v1/bike/decathlon"
DECATHLON_SEARCH_URL = f"{BASE}/v1/bike/decathlon/search"
ALLEGRO_URL = f"{BASE}/v1/bike/allegro"
ALLEGRO_SEARCH_URL = f"{BASE}/v1/bike/allegro/search"
SEARCHER_URL = os.getenv("SEARCHER_URL", "").strip().rstrip("/")


class Skip(Exception):
    """Raised by a case that cannot run in the current environment."""


# ── DB helper: sqlite3-style connection over the app's engine (SQLite or PostgreSQL) ──
class _Cursor:
    def __init__(self, rows, lastrowid=None):
        self._rows, self.lastrowid = rows, lastrowid

    def fetchone(self):
        return tuple(self._rows[0]) if self._rows else None

    def fetchall(self):
        return [tuple(r) for r in self._rows]


class _DB:
    def __init__(self):
        self._conn = get_engine().connect()

    def execute(self, sql, params=()):
        names = iter(range(len(params)))
        bound = re.sub(r"\?", lambda _: f":p{next(names)}", sql)
        values = {f"p{i}": v for i, v in enumerate(params)}
        insert_with_id = re.match(r"\s*INSERT INTO (bike|search_cache|bike_offer)\b", sql, re.I)
        if insert_with_id:
            bound += " RETURNING id"
        result = self._conn.execute(text(bound), values)
        if insert_with_id:
            return _Cursor([], lastrowid=result.scalar_one())
        return _Cursor(result.fetchall() if result.returns_rows else [])

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm_key(fields: dict) -> str:
    """Mirror cache.py:_normalise() so we can address a generic-cache row."""
    return json.dumps({k: str(v).strip().lower() for k, v in fields.items()}, sort_keys=True, separators=(",", ":"))


def _cache_row_exists(endpoint: str, request_key: str) -> bool:
    conn = _DB()
    try:
        return conn.execute(
            "SELECT 1 FROM endpoint_req_to_body_cache WHERE endpoint = ? AND request = ?", (endpoint, request_key)
        ).fetchone() is not None
    finally:
        conn.close()


def _cache_row_delete(endpoint: str, request_key: str) -> None:
    conn = _DB()
    try:
        conn.execute("DELETE FROM endpoint_req_to_body_cache WHERE endpoint = ? AND request = ?", (endpoint, request_key))
        conn.commit()
    finally:
        conn.close()


def _delete_bike(brand: str, model: str) -> None:
    """Remove a fixture bike and every row hanging off it (explicit, no reliance on ON DELETE CASCADE)."""
    conn = _DB()
    try:
        ids = "(SELECT id FROM bike WHERE brand = ? AND model = ?)"
        p = (brand, model)
        for sql in (
            f"DELETE FROM bike_offer_photos WHERE bike_offer_id IN (SELECT id FROM bike_offer WHERE bike_id IN {ids})",
            f"DELETE FROM bike_offer WHERE bike_id IN {ids}",
            f"DELETE FROM bike_missing_request WHERE bike_id IN {ids}",
            f"DELETE FROM search_bike_rating_cache WHERE bike_id IN {ids}",
            f"DELETE FROM bike_detail_photos WHERE bike_detail_id IN (SELECT id FROM bike_detail WHERE bike_id IN {ids})",
            f"DELETE FROM bike_detail_component WHERE bike_detail_id IN (SELECT id FROM bike_detail WHERE bike_id IN {ids})",
            f"DELETE FROM bike_detail WHERE bike_id IN {ids}",
            "DELETE FROM bike WHERE brand = ? AND model = ?",
        ):
            conn.execute(sql, p)
        conn.commit()
    finally:
        conn.close()


def _insert_bike(brand: str, model: str) -> int:
    conn = _DB()
    try:
        bike_id = conn.execute(
            "INSERT INTO bike (brand, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (brand, model, _now(), _now()),
        ).lastrowid
        conn.commit()
        return bike_id
    finally:
        conn.close()


def _seed_search_row(query: str, brand: str, model: str) -> None:
    """A fresh search_cache row (+ its bike and rating row) owned by this suite."""
    conn = _DB()
    try:
        conn.execute("DELETE FROM search_cache WHERE query = ?", (query,))
        search_id = conn.execute(
            "INSERT INTO search_cache (query, time_stored) VALUES (?, ?)", (query, _now())
        ).lastrowid
        hit = conn.execute("SELECT id FROM bike WHERE brand = ? AND model = ?", (brand, model)).fetchone()
        bike_id = hit[0] if hit else conn.execute(
            "INSERT INTO bike (brand, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (brand, model, _now(), _now()),
        ).lastrowid
        conn.execute(
            "INSERT INTO search_bike_rating_cache "
            "(search_cache_id, bike_id, rating, explanation, accessories, display_order) VALUES (?, ?, ?, ?, ?, ?)",
            (search_id, bike_id, 8.5, "Smoke fixture.", json.dumps(["fixture"]), 0),
        )
        conn.commit()
    finally:
        conn.close()


def _drop_search_row(query: str) -> None:
    conn = _DB()
    try:
        conn.execute("DELETE FROM search_cache WHERE query = ?", (query,))
        conn.commit()
    finally:
        conn.close()


def _post(url: str, body: dict, timeout: float = 30) -> httpx.Response:
    print(f"  POST {url}  {json.dumps(body, ensure_ascii=False)}")
    return httpx.post(url, json=body, timeout=timeout)


def _assert_offers(offers: list[dict], source: str) -> None:
    assert offers, "expected at least 1 offer"
    for o in offers:
        assert o["brand"] and o["model"] and o["price"] and o["url"], f"incomplete offer: {o}"
        assert isinstance(o["is_new"], bool) and isinstance(o["photos"], list), f"bad offer types: {o}"
        assert o["source"] == source, f"expected source {source!r}, got {o['source']!r}"


# ── Cases without any Anthropic API call ───────────────────────────────────

FIX_SEARCH_QUERY = "smoke fixture: search happy path"
FIX_SEARCH_BRAND, FIX_SEARCH_MODEL = "Smoke Fixture", "Search Bike"


def case_search_db_hit_and_search_cache():
    """/v1/bike/search served from the DB (zero AI) + /v1/bike/search-cache on the same stored search."""
    _seed_search_row(FIX_SEARCH_QUERY, FIX_SEARCH_BRAND, FIX_SEARCH_MODEL)
    body = {"brand": FIX_SEARCH_BRAND, "model": FIX_SEARCH_MODEL}
    key = _norm_key(body)
    try:
        _cache_row_delete("/v1/bike/search", key)
        t0 = time.perf_counter()
        resp = _post(SEARCH_URL, body, timeout=60)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        bikes = resp.json()["bikes"]
        assert bikes and all(b["brand"] == FIX_SEARCH_BRAND and b["model"] == FIX_SEARCH_MODEL for b in bikes), bikes
        assert isinstance(bikes[0]["accessories"], list) and 0 <= bikes[0]["match_score"] <= 10, bikes[0]
        assert bikes[0]["explanation"], "explanation must be non-empty"
        assert elapsed < 5.0, f"DB hit took {elapsed:.2f}s — expected < 5s (AI ran?)"
        assert not _cache_row_exists("/v1/bike/search", key), "DB-hit path must not write a generic-cache row"

        cached = httpx.get(SEARCH_CACHE_URL, params={"query": FIX_SEARCH_QUERY}, timeout=10)
        assert cached.status_code == 200, f"search-cache: expected 200, got {cached.status_code}: {cached.text[:200]}"
        assert cached.json()["cached"] is True and cached.json()["bikes"], cached.json()
    finally:
        _drop_search_row(FIX_SEARCH_QUERY)
        _delete_bike(FIX_SEARCH_BRAND, FIX_SEARCH_MODEL)


FIX_DETAILS_BRAND, FIX_DETAILS_MODEL = "Smoke Fixture", "Details Bike"


def case_details_cache():
    """/v1/bike/details-cache returns a stored details row (no web/Claude call)."""
    _delete_bike(FIX_DETAILS_BRAND, FIX_DETAILS_MODEL)
    save_bike_details(FIX_DETAILS_BRAND, FIX_DETAILS_MODEL, BikeDetailsResponse(
        company=FIX_DETAILS_BRAND, model=FIX_DETAILS_MODEL,
        description=BikeDescription(text="Smoke fixture.", segments=[], citations=[]),
        components=[BikeCategory(category="Frame", subcategories=[BikeSubcategory(
            subcategory="Frame", elements=[ComponentElement(name="Frame", specs=[SpecItem(key="Material", value="Alloy")])],
        )])],
        photos=["https://example.com/smoke.jpg"],
    ))
    try:
        t0 = time.perf_counter()
        resp = httpx.get(DETAILS_CACHE_URL, params={"company": FIX_DETAILS_BRAND, "model": FIX_DETAILS_MODEL}, timeout=10)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        assert data["company"] == FIX_DETAILS_BRAND and data["model"] == FIX_DETAILS_MODEL, data
        assert data["components"][0]["category"] == "Frame", data["components"]
        assert data["photos"] == ["https://example.com/smoke.jpg"], data["photos"]
        assert elapsed < 5.0, f"cache read took {elapsed:.2f}s"
    finally:
        _delete_bike(FIX_DETAILS_BRAND, FIX_DETAILS_MODEL)


FIX_MISSING_BRAND, FIX_MISSING_MODEL = "Smoke Fixture", "Missing Bike"


def case_missing():
    """/v1/bike/missing counts a "Request data" click on an existing bike."""
    _delete_bike(FIX_MISSING_BRAND, FIX_MISSING_MODEL)
    bike_id = _insert_bike(FIX_MISSING_BRAND, FIX_MISSING_MODEL)
    try:
        body = {"company": FIX_MISSING_BRAND, "model": FIX_MISSING_MODEL, "missing_type": "photos"}
        resp = _post(MISSING_URL, body, timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        assert resp.json() == {"bike_id": bike_id, "missing_type": "photos", "counter": 1}, resp.json()
    finally:
        _delete_bike(FIX_MISSING_BRAND, FIX_MISSING_MODEL)


FIX_USED_BRAND, FIX_USED_MODEL = "Smoke Fixture", "Used Bike"


def case_used():
    """/v1/bike/used/olx serves stored OLX offers from bike_offer (no AI, no cache)."""
    _delete_bike(FIX_USED_BRAND, FIX_USED_MODEL)
    url = "https://www.olx.pl/d/oferta/smoke-fixture-used-ID1.html"
    photo = "https://ireland.apollo.olxcdn.com/smoke/one.jpg"
    conn = _DB()
    try:
        bike_id = conn.execute(
            "INSERT INTO bike (brand, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (FIX_USED_BRAND, FIX_USED_MODEL, _now(), _now()),
        ).lastrowid
        offer_id = conn.execute(
            "INSERT INTO bike_offer (bike_id, price, is_new, url, source, city, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bike_id, "1 234 zł", False, url, "olx.pl", "Wrocław", _now()),
        ).lastrowid
        conn.execute("INSERT INTO bike_offer_photos (bike_offer_id, url, display_order) VALUES (?, ?, ?)", (offer_id, photo, 0))
        conn.commit()
    finally:
        conn.close()
    try:
        resp = _post(USED_URL, {"company": FIX_USED_BRAND, "model": FIX_USED_MODEL}, timeout=10)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        assert data["info"] == "" and len(data["offers"]) == 1, data
        offer = data["offers"][0]
        assert (offer["url"], offer["price"], offer["city"], offer["photos"]) == (url, "1 234 zł", "Wrocław", [photo]), offer
        assert offer["is_new"] is False and offer["source"] == "olx.pl", offer
    finally:
        _delete_bike(FIX_USED_BRAND, FIX_USED_MODEL)


def _require_searcher() -> None:
    try:
        up = bool(SEARCHER_URL) and httpx.get(f"{SEARCHER_URL}/health", timeout=3).json().get("status") == "ok"
    except Exception:  # noqa: BLE001 — not running / refused / timed out
        up = False
    if not up:
        raise Skip(f"searcher not reachable (SEARCHER_URL={SEARCHER_URL or 'unset'})")


def case_used_search():
    """/v1/bike/used/search refuses an unknown bike with 404 before touching the searcher.

    Deliberately no live OLX run here: every searcher run is a paid subscription
    search (~1–2 min), and the one live run this suite keeps is case_decathlon_search,
    which exercises the same proxy code path (searcher_client._search)."""
    resp = _post(USED_SEARCH_URL, {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=30)
    assert resp.status_code == 404, f"Expected 404 for an unknown bike, got {resp.status_code}: {resp.text[:200]}"


FIX_DEC_BRAND, FIX_DEC_MODEL = "Smoke Fixture", "Decathlon Bike"


def case_decathlon():
    """/v1/bike/decathlon serves a stored decathlon.pl offer from bike_offer (no AI, no cache; TODO-032)."""
    _delete_bike(FIX_DEC_BRAND, FIX_DEC_MODEL)
    url = "https://www.decathlon.pl/p/smoke-fixture/_/R-p-000032"
    conn = _DB()
    try:
        bike_id = conn.execute(
            "INSERT INTO bike (brand, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (FIX_DEC_BRAND, FIX_DEC_MODEL, _now(), _now()),
        ).lastrowid
        conn.execute(
            "INSERT INTO bike_offer (bike_id, price, is_new, url, source, city, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bike_id, "1 249 zł", True, url, "decathlon.pl", None, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    body = {"company": FIX_DEC_BRAND, "model": FIX_DEC_MODEL}
    key = _norm_key(body)
    try:
        _cache_row_delete("/v1/bike/decathlon", key)
        t0 = time.perf_counter()
        resp = _post(DECATHLON_URL, body, timeout=10)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        assert data["info"] == "" and len(data["offers"]) == 1, data
        offer = data["offers"][0]
        assert (offer["url"], offer["price"], offer["city"], offer["photos"]) == (url, "1 249 zł", None, []), offer
        assert offer["is_new"] is True and offer["source"] == "decathlon.pl", offer  # is_new comes from the row
        assert offer["brand"] == FIX_DEC_BRAND and offer["model"] == FIX_DEC_MODEL, offer
        assert elapsed < 5.0, f"DB read took {elapsed:.2f}s — expected < 5s (AI ran?)"
        assert not _cache_row_exists("/v1/bike/decathlon", key), "/v1/bike/decathlon must not write a generic-cache row"
        # An unknown bike is a fast, empty 200 — never an error.
        resp = _post(DECATHLON_URL, {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=10)
        assert resp.status_code == 200 and resp.json() == {"offers": [], "info": ""}, resp.text[:200]
    finally:
        _delete_bike(FIX_DEC_BRAND, FIX_DEC_MODEL)


FIX_FOREIGN_BRAND, FIX_FOREIGN_MODEL = "Smoke Fixture", "Foreign Brand Bike"
LIVE_DEC_BRAND, LIVE_DEC_MODEL = "Decathlon", "Rockrider ST 100"


def case_decathlon_search():
    """/v1/bike/decathlon/search: 404 for an unknown bike, an instant empty 200 for a non-Decathlon
    brand (no searcher run — TODO_ISSUE_010), and the live house-brand search when the searcher is up."""
    resp = _post(DECATHLON_SEARCH_URL, {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=30)
    assert resp.status_code == 404, f"Expected 404 for an unknown bike, got {resp.status_code}: {resp.text[:200]}"

    _delete_bike(FIX_FOREIGN_BRAND, FIX_FOREIGN_MODEL)
    _insert_bike(FIX_FOREIGN_BRAND, FIX_FOREIGN_MODEL)
    body = {"company": FIX_FOREIGN_BRAND, "model": FIX_FOREIGN_MODEL}
    try:
        t0 = time.perf_counter()
        resp = _post(DECATHLON_SEARCH_URL, body, timeout=30)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        assert data["offers"] == [] and "Decathlon" in data["info"], data
        assert elapsed < 5.0, f"foreign-brand skip took {elapsed:.2f}s — expected < 5s (searcher ran?)"
        assert not _cache_row_exists("/v1/bike/decathlon/search", _norm_key(body)), "must never write a generic-cache row"
    finally:
        _delete_bike(FIX_FOREIGN_BRAND, FIX_FOREIGN_MODEL)

    _require_searcher()
    # A real Decathlon house brand goes to the searcher. The identity is the one the
    # DB-first search already carries for this bike (`Decathlon` / `Rockrider ST 100`,
    # the way the frontend sends it), not a fresh `Rockrider` / `ST 100` row: a
    # decathlon.pl product URL is globally unique in bike_offer, so a duplicate
    # identity would capture it and starve the bike the UI opens. Created only when
    # missing and kept — it is a real bike.
    conn = _DB()
    try:
        hit = conn.execute(
            "SELECT id FROM bike WHERE LOWER(brand) = ? AND LOWER(model) = ?",
            (LIVE_DEC_BRAND.lower(), LIVE_DEC_MODEL.lower()),
        ).fetchone()
    finally:
        conn.close()
    if hit is None:
        _insert_bike(LIVE_DEC_BRAND, LIVE_DEC_MODEL)
    body = {"company": LIVE_DEC_BRAND, "model": LIVE_DEC_MODEL}
    resp = _post(DECATHLON_SEARCH_URL, body, timeout=600)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
    data = resp.json()
    assert set(data) == {"offers", "info"} and isinstance(data["offers"], list), data
    for o in data["offers"]:
        assert o["url"].startswith("https://www.decathlon.pl/") and o["source"] == "decathlon.pl", o
        assert o["photos"] == [], o
    assert not _cache_row_exists("/v1/bike/decathlon/search", _norm_key(body)), "must never write a generic-cache row"
    # Round-trip: what the searcher stored is what /v1/bike/decathlon now reads back
    # (checked only when something came back — an empty run keeps the older rows).
    if data["offers"]:
        back = _post(DECATHLON_URL, body, timeout=10).json()
        assert {(o["url"], o["price"]) for o in back["offers"]} == {(o["url"], o["price"]) for o in data["offers"]}, back
    else:
        print("  WARNING: the live Decathlon search returned 0 offers — the store/read-back path was not exercised")


FIX_ALLEGRO_BRAND, FIX_ALLEGRO_MODEL = "Smoke Fixture", "Allegro Bike"
# Both keys the old web_search finder ever cached under: the route's own name and
# the pre-rename /v1/bike/offer it kept using. Neither may be read or written now.
ALLEGRO_CACHE_KEYS = ("/v1/bike/offer", "/v1/bike/allegro")


def case_allegro():
    """/v1/bike/allegro serves a stored allegro.pl offer + its photo from bike_offer (no AI, no cache; TODO-033)."""
    _delete_bike(FIX_ALLEGRO_BRAND, FIX_ALLEGRO_MODEL)
    url = "https://allegro.pl/oferta/smoke-fixture-allegro-ID1"
    photo = "https://a.allegroimg.com/original/smoke-fixture-one"
    conn = _DB()
    try:
        bike_id = conn.execute(
            "INSERT INTO bike (brand, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (FIX_ALLEGRO_BRAND, FIX_ALLEGRO_MODEL, _now(), _now()),
        ).lastrowid
        offer_id = conn.execute(
            "INSERT INTO bike_offer (bike_id, price, is_new, url, source, city, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bike_id, "2 319 zł", True, url, "allegro.pl", None, _now()),
        ).lastrowid
        conn.execute("INSERT INTO bike_offer_photos (bike_offer_id, url, display_order) VALUES (?, ?, ?)", (offer_id, photo, 0))
        conn.commit()
    finally:
        conn.close()
    body = {"company": FIX_ALLEGRO_BRAND, "model": FIX_ALLEGRO_MODEL}
    key = _norm_key(body)
    try:
        for endpoint in ALLEGRO_CACHE_KEYS:
            _cache_row_delete(endpoint, key)
        t0 = time.perf_counter()
        resp = _post(ALLEGRO_URL, body, timeout=10)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        assert data["info"] == "" and len(data["offers"]) == 1, data
        offer = data["offers"][0]
        assert (offer["url"], offer["price"], offer["city"], offer["photos"]) == (url, "2 319 zł", None, [photo]), offer
        assert offer["is_new"] is True and offer["source"] == "allegro.pl", offer  # is_new comes from the row
        assert offer["brand"] == FIX_ALLEGRO_BRAND and offer["model"] == FIX_ALLEGRO_MODEL, offer
        assert elapsed < 5.0, f"DB read took {elapsed:.2f}s — expected < 5s (AI ran?)"
        for endpoint in ALLEGRO_CACHE_KEYS:
            assert not _cache_row_exists(endpoint, key), f"/v1/bike/allegro must not write a generic-cache row ({endpoint})"
        # An unknown bike is a fast, empty 200 — never an error.
        resp = _post(ALLEGRO_URL, {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=10)
        assert resp.status_code == 200 and resp.json() == {"offers": [], "info": ""}, resp.text[:200]
    finally:
        _delete_bike(FIX_ALLEGRO_BRAND, FIX_ALLEGRO_MODEL)


def case_allegro_search():
    """/v1/bike/allegro/search refuses an unknown bike with 404 before touching the searcher.

    Deliberately no live Allegro run here: every searcher run is a paid subscription
    search (minutes of CLI time plus a Playwright pass per offer), and the one live
    run this suite keeps is case_decathlon_search, which exercises the same proxy
    code path (searcher_client._search)."""
    resp = _post(ALLEGRO_SEARCH_URL, {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=30)
    assert resp.status_code == 404, f"Expected 404 for an unknown bike, got {resp.status_code}: {resp.text[:200]}"


# ── Cases that call the Anthropic API (--ai) ────────────────────────────────

def case_search_free_text():
    """/v1/bike/search with free text — one Claude call on a cold cache."""
    resp = _post(SEARCH_URL, {"search": "comfortable bike for daily 10 km city commute, mostly paved roads"}, timeout=180)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    bikes = resp.json()["bikes"]
    assert len(bikes) >= 1, "expected at least 1 bike"
    first = bikes[0]
    assert first["brand"] and first["model"] and first["explanation"], first
    assert isinstance(first["accessories"], list) and 0 <= first["match_score"] <= 10, first


def case_parse():
    """/v1/bike/parse extracts structured fields from free text — one Claude call."""
    resp = _post(PARSE_URL, {"text": "Looking for Trek Marlin 7 2022, 29 inch wheels, non-electric"}, timeout=60)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert data.get("brand") == "Trek" and data.get("year") == 2022 and data.get("is_electric") is False, data


def case_ceneo():
    """/v1/bike/ceneo finds an offer on ceneo.pl — one web_search call."""
    resp = _post(CENEO_URL, {"company": "INDIANA", "model": "Rock Jr 24"}, timeout=180)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    _assert_offers(resp.json()["offers"], "ceneo.pl")


CASES = [
    (case_search_db_hit_and_search_cache, False),
    (case_details_cache, False),
    (case_missing, False),
    (case_used, False),
    (case_used_search, False),
    (case_decathlon, False),
    (case_decathlon_search, False),
    (case_allegro, False),
    (case_allegro_search, False),
    (case_search_free_text, True),
    (case_parse, True),
    (case_ceneo, True),
]


def main() -> int:
    with_ai = "--ai" in sys.argv[1:]
    passed = failed = skipped = 0
    for fn, needs_ai in CASES:
        label = f"{fn.__name__[5:]}{'  [API]' if needs_ai else ''}"
        if needs_ai and not with_ai:
            print(f"SKIP  {label} — calls the Anthropic API (run with --ai)")
            skipped += 1
            continue
        print(f"RUN   {label}")
        t0 = time.perf_counter()
        try:
            fn()
        except Skip as why:
            print(f"SKIP  {label} — {why}")
            skipped += 1
        except Exception:  # noqa: BLE001 — report every failure, keep going
            print(f"FAIL  {label}")
            traceback.print_exc()
            failed += 1
        else:
            print(f"PASS  {label} ({time.perf_counter() - t0:.1f}s)")
            passed += 1
    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
