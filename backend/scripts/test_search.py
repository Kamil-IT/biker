"""Backend smoke tests — exactly ONE happy path per endpoint.

Run against a live local server (uvicorn app.main:app --port 8000):

    python scripts/test_search.py          # DB / cache / searcher cases only — no Anthropic API calls
    python scripts/test_search.py --ai     # also the cases that call the Anthropic API (billed)

Every case seeds its own namespaced fixture rows and deletes them afterwards, so
it passes on a cold or aged database. Endpoints covered here:

  no API   /v1/bike/search (DB hit) · /v1/bike/details
           /v1/bike/details/search (404 only — no paid run)
           /v1/bike/missing · /v1/bike/popular · /v1/bike/used/olx · /v1/bike/used/search (404 only — no paid run)
           /v1/bike/decathlon · /v1/bike/decathlon/search (404 + foreign-brand skip always; the
           live house-brand search — the ONE paid searcher run in the suite — only when the searcher is up)
           /v1/bike/allegro · /v1/bike/allegro/search (404 only — no paid run)
           /v1/bike/photos · /v1/bike/photos/search (404 only — no paid run)
           /v1/bike/review · /v1/bike/review/search (404 only — no paid run)
           /v1/equipment/details · /v1/equipment/photos (by id and by name)
           /v1/equipment/details/search · /v1/equipment/photos/search (404 only — no paid run)
  --ai     /v1/bike/search (free text) · /v1/bike/parse · /v1/bike/ceneo

/v1/equipment/review (Anthropic API, generic cache) has its own focused script,
test_equipment_review.py; the old test_equipment.py left with the in-backend
equipment finders (TODO-042).
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
from app.schemas import EquipmentDetailsResponse  # noqa: E402
from app import equipment_repository  # noqa: E402

BASE = os.getenv("BIKER_API_URL", "http://localhost:8000").rstrip("/")
SEARCH_URL = f"{BASE}/v1/bike/search"
DETAILS_URL = f"{BASE}/v1/bike/details"
DETAILS_SEARCH_URL = f"{BASE}/v1/bike/details/search"
MISSING_URL = f"{BASE}/v1/bike/missing"
POPULAR_URL = f"{BASE}/v1/bike/popular"
USED_URL = f"{BASE}/v1/bike/used/olx"
USED_SEARCH_URL = f"{BASE}/v1/bike/used/search"
PARSE_URL = f"{BASE}/v1/bike/parse"
CENEO_URL = f"{BASE}/v1/bike/ceneo"
DECATHLON_URL = f"{BASE}/v1/bike/decathlon"
DECATHLON_SEARCH_URL = f"{BASE}/v1/bike/decathlon/search"
ALLEGRO_URL = f"{BASE}/v1/bike/allegro"
ALLEGRO_SEARCH_URL = f"{BASE}/v1/bike/allegro/search"
PHOTOS_URL = f"{BASE}/v1/bike/photos"
PHOTOS_SEARCH_URL = f"{BASE}/v1/bike/photos/search"
REVIEW_URL = f"{BASE}/v1/bike/review"
REVIEW_SEARCH_URL = f"{BASE}/v1/bike/review/search"
EQUIP_DETAILS_URL = f"{BASE}/v1/equipment/details"
EQUIP_PHOTOS_URL = f"{BASE}/v1/equipment/photos"
EQUIP_DETAILS_SEARCH_URL = f"{BASE}/v1/equipment/details/search"
EQUIP_PHOTOS_SEARCH_URL = f"{BASE}/v1/equipment/photos/search"
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
        insert_with_id = re.match(r"\s*INSERT INTO (bike|search_cache|bike_offer|bike_review)\b", sql, re.I)
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


def _cache_row_insert(endpoint: str, request_key: str, response: dict) -> None:
    conn = _DB()
    try:
        conn.execute(
            "INSERT INTO endpoint_req_to_body_cache (endpoint, request, response, time_stored) VALUES (?, ?, ?, ?)",
            (endpoint, request_key, json.dumps(response), _now()),
        )
        conn.commit()
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
            f"DELETE FROM bike_popular WHERE bike_id IN {ids}",
            f"DELETE FROM search_bike_rating_cache WHERE bike_id IN {ids}",
            f"DELETE FROM bike_detail_photos WHERE bike_id IN {ids}",
            f"DELETE FROM bike_review_source WHERE review_id IN (SELECT id FROM bike_review WHERE bike_id IN {ids})",
            f"DELETE FROM bike_review WHERE bike_id IN {ids}",
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

FIX_SEARCH_BRAND, FIX_SEARCH_MODEL = "Smoke Fixture", "Search Bike"
# The stale generic-cache answer. Namespaced like every fixture: a server still on the
# old code serves it and save_search() stores its search + bike, which the test removes.
FIX_STALE_QUERY, FIX_STALE_MODEL = "smoke fixture: stale generic row", "Stale Cache Row"
FIX_SEARCH_BARE_MODEL = "Search Bike Without Details"
FIX_SHORT = "Krótki opis testowy. Drugie zdanie opisu."
FIX_CHIPS = ["Shimano Deore RD-M6000", "Shimano BL-MT200", "Alloy"]


def _full_components() -> list:
    def cat(category, sub, name, specs=()):
        return BikeCategory(category=category, subcategories=[BikeSubcategory(subcategory=sub, elements=[
            ComponentElement(name=name, description="", specs=[SpecItem(key=k, value=v) for k, v in specs]),
        ])])
    return [
        cat("Frame", "Frame", "Smoke Frame", [("Material", "Alloy")]),
        cat("Drivetrain", "Rear Derailleur", "Shimano Deore RD-M6000"),
        cat("Brakes", "Brake Lever Front", "Shimano BL-MT200"),
    ]


def _seed_bike_details(brand: str, model: str, short: str, components: list, text_: str = "Opis testowy.") -> None:
    """Store details (+ short_description) through the ORM, replacing any earlier ones."""
    save_bike_details(brand, model, BikeDetailsResponse(
        company=brand, model=model,
        description=BikeDescription(text=text_, segments=[], citations=[]),
        components=components, short_description=short,
    ))


def case_search_db_hit():
    """/v1/bike/search served from the DB (zero AI), never from the generic cache."""
    # TODO-041: explanation = the stored short description, accessories = chips from
    # the stored components (rear derailleur, brake lever, frame material).
    _seed_bike_details(FIX_SEARCH_BRAND, FIX_SEARCH_MODEL, FIX_SHORT, _full_components())
    _insert_bike(FIX_SEARCH_BRAND, FIX_SEARCH_BARE_MODEL)
    body = {"brand": FIX_SEARCH_BRAND, "model": FIX_SEARCH_MODEL}
    key = _norm_key(body)
    # A stale generic-cache row for this exact body, like the 5-bike answers stored
    # before TODO-025. The endpoint must not read it (the cache has no TTL).
    stale = {"search": FIX_STALE_QUERY, "bikes": [{
        "brand": FIX_SEARCH_BRAND, "model": FIX_STALE_MODEL, "accessories": [],
        "explanation": "stale",
    }]}
    try:
        _cache_row_delete("/v1/bike/search", key)
        _cache_row_insert("/v1/bike/search", key, stale)
        t0 = time.perf_counter()
        resp = _post(SEARCH_URL, body, timeout=60)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        bikes = resp.json()["bikes"]
        assert all(b["model"] != FIX_STALE_MODEL for b in bikes), f"served the generic-cache row: {bikes}"
        assert bikes and all(b["brand"] == FIX_SEARCH_BRAND and b["model"] == FIX_SEARCH_MODEL for b in bikes), bikes
        assert isinstance(bikes[0]["accessories"], list), bikes[0]
        assert "match_score" not in bikes[0], f"match_score was removed (TODO-040): {bikes[0]}"
        assert bikes[0]["explanation"] == FIX_SHORT, f"explanation must be the stored short description: {bikes[0]}"
        assert bikes[0]["accessories"] == FIX_CHIPS, f"accessories must be the component chips: {bikes[0]}"
        assert elapsed < 5.0, f"DB hit took {elapsed:.2f}s — expected < 5s (AI ran?)"

        # A bike without stored details -> "" / [] (the frontend hides both).
        bare = _post(SEARCH_URL, {"brand": FIX_SEARCH_BRAND, "model": FIX_SEARCH_BARE_MODEL}, timeout=60)
        assert bare.status_code == 200, bare.text[:200]
        (b0,) = bare.json()["bikes"]
        assert b0["explanation"] == "" and b0["accessories"] == [], b0

    finally:
        _delete_bike(FIX_SEARCH_BRAND, FIX_SEARCH_BARE_MODEL)
        _cache_row_delete("/v1/bike/search", key)
        _delete_bike(FIX_SEARCH_BRAND, FIX_SEARCH_MODEL)
        _delete_bike(FIX_SEARCH_BRAND, FIX_STALE_MODEL)  # rating rows first, then the bike
        _drop_search_row(FIX_STALE_QUERY)


FIX_DETAILS_BRAND, FIX_DETAILS_MODEL = "Smoke Fixture", "Details Bike"


def case_details():
    """/v1/bike/details is a pure DB read: stored details incl. short_description, no AI,
    no generic-cache row; an unknown bike and a bike without details -> fast empty 200."""
    bare_model = "Details Bike Without Details"
    _delete_bike(FIX_DETAILS_BRAND, FIX_DETAILS_MODEL)
    _delete_bike(FIX_DETAILS_BRAND, bare_model)
    _seed_bike_details(FIX_DETAILS_BRAND, FIX_DETAILS_MODEL, FIX_SHORT, _full_components())
    _insert_bike(FIX_DETAILS_BRAND, bare_model)
    body = {"company": FIX_DETAILS_BRAND, "model": FIX_DETAILS_MODEL}
    key = _norm_key(body)
    empty = {"text": "", "segments": [], "citations": []}
    try:
        _cache_row_delete("/v1/bike/details", key)
        t0 = time.perf_counter()
        resp = _post(DETAILS_URL, body, timeout=10)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        data = resp.json()
        assert data["company"] == FIX_DETAILS_BRAND and data["model"] == FIX_DETAILS_MODEL, data
        assert data["short_description"] == FIX_SHORT, data
        assert data["description"]["text"] == "Opis testowy.", data
        assert [c["category"] for c in data["components"]] == ["Frame", "Drivetrain", "Brakes"], data["components"]
        assert "photos" not in data
        assert elapsed < 5.0, f"DB read took {elapsed:.2f}s — expected < 5s (AI ran?)"
        assert not _cache_row_exists("/v1/bike/details", key), "/v1/bike/details must not write a generic-cache row"
        for company, model in ((FIX_DETAILS_BRAND, bare_model), ("FakeBrand", "NoSuchModel XYZ999")):
            t0 = time.perf_counter()
            resp = _post(DETAILS_URL, {"company": company, "model": model}, timeout=10)
            assert resp.status_code == 200, resp.text[:200]
            assert resp.json() == {
                "company": company, "model": model, "description": empty, "components": [], "short_description": "",
            }, resp.json()
            assert time.perf_counter() - t0 < 5.0
    finally:
        _delete_bike(FIX_DETAILS_BRAND, FIX_DETAILS_MODEL)
        _delete_bike(FIX_DETAILS_BRAND, bare_model)


def case_details_search():
    """/v1/bike/details/search refuses an unknown bike with 404 before touching the searcher.

    No live run here: every searcher run is a paid subscription search (the suite's one
    live run is case_decathlon_search, same proxy code path)."""
    resp = _post(DETAILS_SEARCH_URL, {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=30)
    assert resp.status_code == 404, f"Expected 404 for an unknown bike, got {resp.status_code}: {resp.text[:200]}"


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


FIX_POP_BRAND, FIX_POP_MODEL_A, FIX_POP_MODEL_B = "Smoke Fixture", "Popular Bike A", "Popular Bike B"
# Three sentences, the first with an abbreviation the splitter must not cut on.
FIX_POP_TEXT = "Rower waży ok. 12 kg i ma koła 29 cali. Drugie zdanie opisu. Trzecie zdanie nie może trafić na kartę."
FIX_POP_BLURB = "Rower waży ok. 12 kg i ma koła 29 cali. Drugie zdanie opisu."


def case_popular():
    """/v1/bike/popular lists the bike_popular rows in position order with a two-sentence blurb (no AI, no cache; TODO-034)."""
    for m in (FIX_POP_MODEL_A, FIX_POP_MODEL_B):
        _delete_bike(FIX_POP_BRAND, m)
    id_a = _insert_bike(FIX_POP_BRAND, FIX_POP_MODEL_A)
    id_b = _insert_bike(FIX_POP_BRAND, FIX_POP_MODEL_B)
    try:
        # Bike A has details (the blurb source), bike B has none; B is listed first.
        save_bike_details(FIX_POP_BRAND, FIX_POP_MODEL_A, BikeDetailsResponse(
            company=FIX_POP_BRAND, model=FIX_POP_MODEL_A,
            description=BikeDescription(text=FIX_POP_TEXT, segments=[], citations=[]),
            components=[],
        ))
        conn = _DB()
        try:
            for bike_id, position in ((id_b, 1), (id_a, 2)):
                conn.execute("INSERT INTO bike_popular (bike_id, position, created_at) VALUES (?, ?, ?)", (bike_id, position, _now()))
            conn.commit()
        finally:
            conn.close()
        t0 = time.perf_counter()
        resp = httpx.get(POPULAR_URL, timeout=10)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        bikes = resp.json()["bikes"]
        # Real seeded rows may sit in the table too — assert on the fixture rows' relative order only.
        mine = [b for b in bikes if b["brand"] == FIX_POP_BRAND and b["model"] in (FIX_POP_MODEL_A, FIX_POP_MODEL_B)]
        assert [b["model"] for b in mine] == [FIX_POP_MODEL_B, FIX_POP_MODEL_A], f"position order / stored casing: {mine}"
        assert mine[0]["description"] == "", mine[0]
        assert mine[1]["description"] == FIX_POP_BLURB, mine[1]
        assert elapsed < 5.0, f"DB read took {elapsed:.2f}s — expected < 5s (AI ran?)"
        assert not _cache_row_exists("/v1/bike/popular", _norm_key({})), "/v1/bike/popular must not write a generic-cache row"
    finally:
        for m in (FIX_POP_MODEL_A, FIX_POP_MODEL_B):
            _delete_bike(FIX_POP_BRAND, m)


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
    """/v1/bike/allegro serves a stored allegro.pl offer from bike_offer (no AI, no cache, no photos; TODO-033)."""
    _delete_bike(FIX_ALLEGRO_BRAND, FIX_ALLEGRO_MODEL)
    url = "https://allegro.pl/oferta/smoke-fixture-allegro-ID1"
    conn = _DB()
    try:
        bike_id = conn.execute(
            "INSERT INTO bike (brand, model, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (FIX_ALLEGRO_BRAND, FIX_ALLEGRO_MODEL, _now(), _now()),
        ).lastrowid
        # Allegro rows never have photos (the searcher does not scrape allegro.pl — it answers 403); the
        # photo read path is covered by case_used.
        conn.execute(
            "INSERT INTO bike_offer (bike_id, price, is_new, url, source, city, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bike_id, "2 319 zł", True, url, "allegro.pl", None, _now()),
        )
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
        assert (offer["url"], offer["price"], offer["city"], offer["photos"]) == (url, "2 319 zł", None, []), offer
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
    search (a minute or two of CLI time), and the one live
    run this suite keeps is case_decathlon_search, which exercises the same proxy
    code path (searcher_client._search)."""
    resp = _post(ALLEGRO_SEARCH_URL, {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=30)
    assert resp.status_code == 404, f"Expected 404 for an unknown bike, got {resp.status_code}: {resp.text[:200]}"


FIX_PHOTOS_BRAND, FIX_PHOTOS_MODEL = "Smoke Fixture", "Photos Bike"


def case_photos():
    """/v1/bike/photos serves the stored bike_detail_photos rows in display_order (no AI, no cache, no details row)."""
    _delete_bike(FIX_PHOTOS_BRAND, FIX_PHOTOS_MODEL)
    bike_id = _insert_bike(FIX_PHOTOS_BRAND, FIX_PHOTOS_MODEL)
    photos = [f"https://example.com/smoke-photos-{i}.jpg" for i in range(3)]
    conn = _DB()
    try:
        # Inserted out of order: the response must follow display_order, not insertion order.
        for order in (2, 0, 1):
            conn.execute(
                "INSERT INTO bike_detail_photos (bike_id, url, display_order) VALUES (?, ?, ?)",
                (bike_id, photos[order], order),
            )
        conn.commit()
    finally:
        conn.close()
    body = {"company": FIX_PHOTOS_BRAND, "model": FIX_PHOTOS_MODEL}
    key = _norm_key(body)
    try:
        _cache_row_delete("/v1/bike/photos", key)
        t0 = time.perf_counter()
        resp = _post(PHOTOS_URL, body, timeout=10)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        assert resp.json() == {"photos": photos}, resp.json()
        assert elapsed < 5.0, f"DB read took {elapsed:.2f}s — expected < 5s (AI ran?)"
        assert not _cache_row_exists("/v1/bike/photos", key), "/v1/bike/photos must not write a generic-cache row"
        # An unknown bike is a fast, empty 200 — never an error.
        t0 = time.perf_counter()
        resp = _post(PHOTOS_URL, {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=10)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200 and resp.json() == {"photos": []}, resp.text[:200]
        assert elapsed < 5.0, f"unknown-bike read took {elapsed:.2f}s"
    finally:
        _delete_bike(FIX_PHOTOS_BRAND, FIX_PHOTOS_MODEL)


def case_photos_search():
    """/v1/bike/photos/search refuses an unknown bike with 404 before touching the searcher.

    Deliberately no live photo run here: every searcher run is a paid subscription
    search, and the one live run this suite keeps is case_decathlon_search, which
    exercises the same proxy code path (searcher_client._search)."""
    resp = _post(PHOTOS_SEARCH_URL, {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=30)
    assert resp.status_code == 404, f"Expected 404 for an unknown bike, got {resp.status_code}: {resp.text[:200]}"


FIX_REVIEW_BRAND, FIX_REVIEW_MODEL = "Smoke Fixture", "Review Bike"
FIX_REVIEW_BARE_MODEL = "Review Bike Without Review"
EMPTY_REVIEW = {"score": 0, "explanation": "", "ref": [], "rating": 0.0, "sources_used": 0}


def case_review():
    """/v1/bike/review serves the stored bike_review + bike_review_source rows (no AI, no cache; TODO-037)."""
    for model in (FIX_REVIEW_MODEL, FIX_REVIEW_BARE_MODEL):
        _delete_bike(FIX_REVIEW_BRAND, model)
    bike_id = _insert_bike(FIX_REVIEW_BRAND, FIX_REVIEW_MODEL)
    _insert_bike(FIX_REVIEW_BRAND, FIX_REVIEW_BARE_MODEL)
    refs = ["https://www.bikeradar.com/smoke-review", "https://www.reddit.com/r/bicycling/smoke-review"]
    explanation = "Recenzja testowa: rower solidny i wygodny."
    conn = _DB()
    try:
        review_id = conn.execute(
            "INSERT INTO bike_review (bike_id, score, explanation, rating, sources_used, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (bike_id, 8, explanation, 7.6, 2, _now(), _now()),
        ).lastrowid
        # Inserted out of order: `ref` must follow display_order (the tier order), not insertion order.
        for order in (1, 0):
            conn.execute(
                "INSERT INTO bike_review_source (review_id, url, display_order) VALUES (?, ?, ?)",
                (review_id, refs[order], order),
            )
        conn.commit()
    finally:
        conn.close()
    body = {"company": FIX_REVIEW_BRAND, "model": FIX_REVIEW_MODEL}
    key = _norm_key(body)
    try:
        _cache_row_delete("/v1/bike/review", key)
        t0 = time.perf_counter()
        resp = _post(REVIEW_URL, body, timeout=10)
        elapsed = time.perf_counter() - t0
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
        assert resp.json() == {
            "score": 8, "explanation": explanation, "ref": refs, "rating": 7.6, "sources_used": 2,
        }, resp.json()
        assert elapsed < 5.0, f"DB read took {elapsed:.2f}s — expected < 5s (AI ran?)"
        assert not _cache_row_exists("/v1/bike/review", key), "/v1/bike/review must not write a generic-cache row"
        # A known bike without a review and an unknown bike are both a fast 200 with the empty review.
        for bare in ({"company": FIX_REVIEW_BRAND, "model": FIX_REVIEW_BARE_MODEL},
                     {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}):
            t0 = time.perf_counter()
            resp = _post(REVIEW_URL, bare, timeout=10)
            elapsed = time.perf_counter() - t0
            assert resp.status_code == 200 and resp.json() == EMPTY_REVIEW, resp.text[:200]
            assert elapsed < 5.0, f"empty-review read took {elapsed:.2f}s — expected < 5s (AI ran?)"
    finally:
        for model in (FIX_REVIEW_MODEL, FIX_REVIEW_BARE_MODEL):
            _delete_bike(FIX_REVIEW_BRAND, model)


def case_review_search():
    """/v1/bike/review/search refuses an unknown bike with 404 before touching the searcher.

    No live run here: every searcher run is a paid subscription search, and a known
    bike now always reaches the searcher, stored review or not (the suite's one live
    run is case_decathlon_search, same proxy code path)."""
    resp = _post(REVIEW_SEARCH_URL, {"company": "FakeBrand", "model": "NoSuchModel XYZ999"}, timeout=30)
    assert resp.status_code == 404, f"Expected 404 for an unknown bike, got {resp.status_code}: {resp.text[:200]}"


# ── Equipment (TODO-042): DB reads + the 404 guards of the on-demand searches ──

FIX_EQUIP_MODEL = "Smoke Fixture Helmet"
FIX_EQUIP_CATEGORY = "helmets"
FIX_EQUIP_SHORT = "Kask testowy. Drugie zdanie."
FIX_EQUIP_BIKE_BRAND, FIX_EQUIP_BIKE_MODEL = "Smoke Fixture", "Equipment Bike"
EMPTY_DESC = {"text": "", "segments": [], "citations": []}


def _delete_equipment(model: str) -> None:
    """Remove fixture equipment and its rows (bike links fall back to NULL via ON DELETE SET NULL)."""
    conn = _DB()
    try:
        ids = "(SELECT id FROM equipment WHERE model_norm = ?)"
        p = (model.strip().lower(),)
        for sql in (
            f"UPDATE bike_detail_component SET equipment_id = NULL WHERE equipment_id IN {ids}",
            f"DELETE FROM equipment_detail_component WHERE equipment_detail_id IN "
            f"(SELECT id FROM equipment_detail WHERE equipment_id IN {ids})",
            f"DELETE FROM equipment_detail WHERE equipment_id IN {ids}",
            f"DELETE FROM equipment_detail_photos WHERE equipment_id IN {ids}",
            "DELETE FROM equipment WHERE model_norm = ?",
        ):
            conn.execute(sql, p)
        conn.commit()
    finally:
        conn.close()


def _equipment_cache_key(model: str) -> str:
    """The key the old in-backend /v1/equipment/details wrote its generic-cache rows under."""
    return _norm_key({"company": "", "model": model, "category": ""})


def case_equipment_details():
    """/v1/equipment/details is a pure DB read: by equipment_id and by name, no AI, no generic-cache row;
    an unknown id or name -> fast empty 200."""
    _delete_equipment(FIX_EQUIP_MODEL)
    eid = equipment_repository.save_equipment_details("", FIX_EQUIP_MODEL, FIX_EQUIP_CATEGORY, EquipmentDetailsResponse(
        company="", model=FIX_EQUIP_MODEL, category=FIX_EQUIP_CATEGORY,
        description=BikeDescription(text="Opis kasku testowego.", segments=[], citations=[]),
        components=[BikeCategory(category="Protection", subcategories=[BikeSubcategory(subcategory="Shell", elements=[
            ComponentElement(name="In-mould shell", description="", specs=[SpecItem(key="Weight", value="400 g")]),
        ])])],
        short_description=FIX_EQUIP_SHORT,
    ))
    assert eid is not None, "seeding the equipment fixture failed (is the DB migrated? scripts/migrate_equipment_tables.py)"
    key = _equipment_cache_key(FIX_EQUIP_MODEL)
    try:
        _cache_row_delete("/v1/equipment/details", key)
        for body in ({"model": "ignored when the id is given", "equipment_id": eid},
                     {"company": "", "model": FIX_EQUIP_MODEL.upper()}):
            t0 = time.perf_counter()
            resp = _post(EQUIP_DETAILS_URL, body, timeout=10)
            elapsed = time.perf_counter() - t0
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
            data = resp.json()
            assert (data["equipment_id"], data["company"], data["model"], data["category"]) == (
                eid, "", FIX_EQUIP_MODEL, FIX_EQUIP_CATEGORY), data
            assert data["description"]["text"] == "Opis kasku testowego." and data["short_description"] == FIX_EQUIP_SHORT, data
            assert data["components"][0]["subcategories"][0]["elements"][0]["specs"] == [{"key": "Weight", "value": "400 g"}], data
            assert "photos" not in data, data
            assert elapsed < 5.0, f"DB read took {elapsed:.2f}s — expected < 5s (AI ran?)"
        assert not _cache_row_exists("/v1/equipment/details", key), "/v1/equipment/details must not write a generic-cache row"
        for body in ({"model": "x", "equipment_id": 999999999}, {"company": "", "model": "No Such Equipment XYZ999"}):
            t0 = time.perf_counter()
            resp = _post(EQUIP_DETAILS_URL, body, timeout=10)
            assert resp.status_code == 200, resp.text[:200]
            data = resp.json()
            assert (data["description"], data["components"], data["short_description"], data["equipment_id"]) == (
                EMPTY_DESC, [], "", None), data
            assert time.perf_counter() - t0 < 5.0
    finally:
        _delete_equipment(FIX_EQUIP_MODEL)


def case_equipment_photos():
    """/v1/equipment/photos serves the stored equipment_detail_photos in display_order, by id and by name."""
    _delete_equipment(FIX_EQUIP_MODEL)
    photos = ["https://example.com/smoke-equipment-0.jpg", "https://example.com/smoke-equipment-1.jpg"]
    # Stored in the opposite order, then re-ordered: the answer must follow display_order, not insertion order.
    eid, written = equipment_repository.save_equipment_photos("", FIX_EQUIP_MODEL, FIX_EQUIP_CATEGORY, list(reversed(photos)))
    assert eid is not None and written == 2, f"seeding failed: {eid}, {written}"
    conn = _DB()
    try:
        for order, url in enumerate(photos):
            conn.execute("UPDATE equipment_detail_photos SET display_order = ? WHERE equipment_id = ? AND url = ?",
                         (order, eid, url))
        conn.commit()
    finally:
        conn.close()
    try:
        for body in ({"model": "x", "equipment_id": eid}, {"company": "", "model": f"  {FIX_EQUIP_MODEL.lower()} "}):
            t0 = time.perf_counter()
            resp = _post(EQUIP_PHOTOS_URL, body, timeout=10)
            elapsed = time.perf_counter() - t0
            assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
            assert resp.json() == {"photos": photos, "equipment_id": eid}, resp.json()
            assert elapsed < 5.0, f"DB read took {elapsed:.2f}s — expected < 5s (AI ran?)"
        assert not _cache_row_exists("/v1/equipment/photos", _equipment_cache_key(FIX_EQUIP_MODEL))
        for body in ({"model": "x", "equipment_id": 999999999}, {"company": "", "model": "No Such Equipment XYZ999"}):
            t0 = time.perf_counter()
            resp = _post(EQUIP_PHOTOS_URL, body, timeout=10)
            assert resp.status_code == 200 and resp.json() == {"photos": [], "equipment_id": None}, resp.text[:200]
            assert time.perf_counter() - t0 < 5.0
    finally:
        _delete_equipment(FIX_EQUIP_MODEL)


def _equipment_search_404s(url: str) -> None:
    """Unknown bike -> 404 "Bike not found"; known bike + an element it does not have -> 404 "Component not found".

    No live run: every searcher run is a paid subscription search (the suite's one
    live run is case_decathlon_search, same searcher_client code path)."""
    body = {"bike_company": "FakeBrand", "bike_model": "NoSuchModel XYZ999", "element_name": FIX_EQUIP_MODEL}
    resp = _post(url, body, timeout=30)
    assert resp.status_code == 404 and resp.json() == {"detail": "Bike not found"}, f"{resp.status_code}: {resp.text[:200]}"
    _delete_bike(FIX_EQUIP_BIKE_BRAND, FIX_EQUIP_BIKE_MODEL)
    _seed_bike_details(FIX_EQUIP_BIKE_BRAND, FIX_EQUIP_BIKE_MODEL, "", _full_components())
    try:
        body = {"bike_company": FIX_EQUIP_BIKE_BRAND, "bike_model": FIX_EQUIP_BIKE_MODEL,
                "element_name": "No Such Element XYZ999"}
        resp = _post(url, body, timeout=30)
        assert resp.status_code == 404 and resp.json() == {"detail": "Component not found"}, \
            f"{resp.status_code}: {resp.text[:200]}"
    finally:
        _delete_bike(FIX_EQUIP_BIKE_BRAND, FIX_EQUIP_BIKE_MODEL)


def case_equipment_details_search():
    """/v1/equipment/details/search: the two 404 guards run before any searcher call."""
    _equipment_search_404s(EQUIP_DETAILS_SEARCH_URL)


def case_equipment_photos_search():
    """/v1/equipment/photos/search: the two 404 guards run before any searcher call."""
    _equipment_search_404s(EQUIP_PHOTOS_SEARCH_URL)


# ── Cases that call the Anthropic API (--ai) ────────────────────────────────

def case_search_free_text():
    """/v1/bike/search with free text — one Claude call on every run (no generic cache)."""
    body = {"search": "comfortable bike for daily 10 km city commute, mostly paved roads"}
    # An older build cached this exact body; clear it so the check below sees only this run.
    _cache_row_delete("/v1/bike/search", _norm_key(body))
    resp = _post(SEARCH_URL, body, timeout=180)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    bikes = resp.json()["bikes"]
    assert len(bikes) >= 1, "expected at least 1 bike"
    first = bikes[0]
    assert first["brand"] and first["model"] and isinstance(first["explanation"], str), first
    assert isinstance(first["accessories"], list) and "match_score" not in first, first
    assert not _cache_row_exists("/v1/bike/search", _norm_key(body)), "search must not write a generic-cache row"


def case_parse():
    """/v1/bike/parse extracts structured fields from free text — one Claude call."""
    resp = _post(PARSE_URL, {"text": "Looking for Trek Marlin 7 2022, 29 inch wheels, non-electric"}, timeout=60)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    data = resp.json()
    assert data.get("brand") == "Trek" and data.get("year") == 2022 and data.get("is_electric") is False, data


# DEPRECATED endpoint, not used by the frontend or searcher; test kept until removal.
def case_ceneo():
    """/v1/bike/ceneo finds an offer on ceneo.pl — one web_search call."""
    resp = _post(CENEO_URL, {"company": "INDIANA", "model": "Rock Jr 24"}, timeout=180)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:200]}"
    _assert_offers(resp.json()["offers"], "ceneo.pl")


CASES = [
    (case_search_db_hit, False),
    (case_details, False),
    (case_details_search, False),
    (case_missing, False),
    (case_popular, False),
    (case_used, False),
    (case_used_search, False),
    (case_decathlon, False),
    (case_decathlon_search, False),
    (case_allegro, False),
    (case_allegro_search, False),
    (case_photos, False),
    (case_photos_search, False),
    (case_review, False),
    (case_review_search, False),
    (case_equipment_details, False),
    (case_equipment_photos, False),
    (case_equipment_details_search, False),
    (case_equipment_photos_search, False),
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
