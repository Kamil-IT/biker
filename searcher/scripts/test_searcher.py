"""Smoke test for the searcher service — run it against a live server on port 8100.

    cd searcher && ..\\backend\\.venv\\Scripts\\python.exe scripts/test_searcher.py

Reads SEARCHER_URL (default http://localhost:8100) and SEARCHER_API_KEY from the
environment or searcher/.env. Every case here is free: health, auth (401) and
validation (422) on all four search routes (olx, decathlon, allegro, photos),
plus a photos request for a bike that already HAS photo rows, which must come
back from the DB without a search (TC-11; the bike is SEARCHER_PHOTOS_BIKE
"Brand|Model", else the first one with photos found through DATABASE_URL; it is
posted only after DATABASE_URL confirms it has >= 1 photo row, else SKIP) — no
`claude -p` run is ever started, so the suite costs nothing and finishes in
seconds. DATABASE_URL here MUST be the database the running searcher uses (both
read searcher/.env by default): against a different database TC-11 could pick a
bike the searcher has no photos for and start a paid search. The one paid, live search of the whole test set is
`backend/scripts/test_search.py` `case_decathlon_search` (through the backend
proxy, only when the searcher is up); the OLX, Allegro and photo searches and
their DB writes are covered by the manual test plans under docs/testing/.
"""
import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.getenv("SEARCHER_URL", "http://localhost:8100").strip().rstrip("/")
API_KEY = os.getenv("SEARCHER_API_KEY", "").strip()
HEALTH_URL = f"{BASE_URL}/health"
SEARCH_URL = f"{BASE_URL}/v1/search/olx"
DECATHLON_URL = f"{BASE_URL}/v1/search/decathlon"
ALLEGRO_URL = f"{BASE_URL}/v1/search/allegro"
PHOTOS_URL = f"{BASE_URL}/v1/search/photos"

assert API_KEY, "SEARCHER_API_KEY must be set (env or searcher/.env)"


def _show(label: str, body, resp: httpx.Response):
    print(f"\n{label} -> HTTP {resp.status_code}")
    if body is not None:
        print(f"Body: {json.dumps(body)}")
    try:
        data = resp.json()
        print(json.dumps(data, indent=2, ensure_ascii=False)[:3000])
        return data
    except ValueError:
        print(resp.text[:500])
        return None


# ── [TC-1] GET /health is open and reports the CLI + DB ──
print(f"GET {HEALTH_URL}")
resp = httpx.get(HEALTH_URL, timeout=60)
data = _show("[TC-1] health", None, resp)
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
assert data["status"] == "ok", data
assert data["database"] is True, "searcher cannot reach its database — check DATABASE_URL / biker-pg"
if not data.get("claude_cli"):
    print("WARNING: /health reports no claude CLI — real searches would fail")
print(f"OK -- health: claude_cli={data.get('claude_cli')!r} database={data['database']}")

# ── [TC-2] POST /v1/search/olx without X-Searcher-Key → 401 ──
body = {"company": "Trek", "model": "Marlin 5"}
resp = httpx.post(SEARCH_URL, json=body, timeout=30)
_show("[TC-2] olx: no key", body, resp)
assert resp.status_code == 401, f"Expected 401 without a key, got {resp.status_code}"
print("OK -- 401 without X-Searcher-Key")

# ── [TC-3] Wrong X-Searcher-Key → 401 ──
resp = httpx.post(SEARCH_URL, json=body, headers={"X-Searcher-Key": API_KEY + "-wrong"}, timeout=30)
_show("[TC-3] olx: wrong key", body, resp)
assert resp.status_code == 401, f"Expected 401 with a wrong key, got {resp.status_code}"
print("OK -- 401 with a wrong X-Searcher-Key")

# ── [TC-4] Empty company → 422 (validation runs after auth, before any CLI run) ──
bad_body = {"company": "", "model": "x"}
resp = httpx.post(SEARCH_URL, json=bad_body, headers={"X-Searcher-Key": API_KEY}, timeout=30)
_show("[TC-4] olx: empty company", bad_body, resp)
assert resp.status_code == 422, f"Expected 422 for an empty company, got {resp.status_code}"
print("OK -- 422 for an empty company")

# ── [TC-5] POST /v1/search/decathlon without X-Searcher-Key → 401 ──
dec_body = {"company": "Decathlon", "model": "Rockrider ST 100"}
resp = httpx.post(DECATHLON_URL, json=dec_body, timeout=30)
_show("[TC-5] decathlon: no key", dec_body, resp)
assert resp.status_code == 401, f"Expected 401 without a key, got {resp.status_code}"
print("OK -- 401 without X-Searcher-Key on /v1/search/decathlon")

# ── [TC-6] POST /v1/search/decathlon with the key but an empty model → 422 (no CLI run) ──
bad_body = {"company": "Decathlon", "model": "   "}
resp = httpx.post(DECATHLON_URL, json=bad_body, headers={"X-Searcher-Key": API_KEY}, timeout=30)
_show("[TC-6] decathlon: blank model", bad_body, resp)
assert resp.status_code == 422, f"Expected 422 for a blank model, got {resp.status_code}"
print("OK -- 422 for a blank model on /v1/search/decathlon")

# ── [TC-7] POST /v1/search/allegro without X-Searcher-Key → 401 ──
alg_body = {"company": "Trek", "model": "Marlin 5"}
resp = httpx.post(ALLEGRO_URL, json=alg_body, timeout=30)
_show("[TC-7] allegro: no key", alg_body, resp)
assert resp.status_code == 401, f"Expected 401 without a key, got {resp.status_code}"
print("OK -- 401 without X-Searcher-Key on /v1/search/allegro")

# ── [TC-8] POST /v1/search/allegro with the key but a blank model → 422 (no CLI run) ──
bad_body = {"company": "Trek", "model": "   "}
resp = httpx.post(ALLEGRO_URL, json=bad_body, headers={"X-Searcher-Key": API_KEY}, timeout=30)
_show("[TC-8] allegro: blank model", bad_body, resp)
assert resp.status_code == 422, f"Expected 422 for a blank model, got {resp.status_code}"
print("OK -- 422 for a blank model on /v1/search/allegro")

# ── [TC-9] POST /v1/search/photos without X-Searcher-Key → 401 ──
ph_body = {"company": "Trek", "model": "Marlin 5"}
resp = httpx.post(PHOTOS_URL, json=ph_body, timeout=30)
_show("[TC-9] photos: no key", ph_body, resp)
assert resp.status_code == 401, f"Expected 401 without a key, got {resp.status_code}"
print("OK -- 401 without X-Searcher-Key on /v1/search/photos")

# ── [TC-10] POST /v1/search/photos with the key but an over-long company → 422 (no CLI run) ──
bad_body = {"company": "x" * 256, "model": "Marlin 5"}
resp = httpx.post(PHOTOS_URL, json=bad_body, headers={"X-Searcher-Key": API_KEY}, timeout=30)
_show("[TC-10] photos: 256-char company", {"company": "x*256", "model": "Marlin 5"}, resp)
assert resp.status_code == 422, f"Expected 422 for a 256-char company, got {resp.status_code}"
print("OK -- 422 for a 256-char company on /v1/search/photos")


def _bike_with_photos() -> tuple[str, str] | None:
    """A bike that HAS photo rows in DATABASE_URL: SEARCHER_PHOTOS_BIKE="Brand|Model" when it
    has some, else the first one found; None (→ SKIP) otherwise. Never guesses: posting for a
    bike without photos would start a paid search that outlives this test's 30 s timeout."""
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        print("(DATABASE_URL is not set — cannot confirm a bike has photos)")
        return None
    from sqlalchemy import create_engine, text
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT b.brand, b.model FROM bike b WHERE EXISTS "
                "(SELECT 1 FROM bike_detail_photos p WHERE p.bike_id = b.id) ORDER BY b.id"
            )).all()
    except Exception as exc:  # noqa: BLE001 — an unmigrated DB (no bike_id column) just skips the case
        print(f"(could not look up a bike with photos: {exc.__class__.__name__})")
        return None
    finally:
        engine.dispose()
    pinned = os.getenv("SEARCHER_PHOTOS_BIKE", "").strip()
    if "|" in pinned:
        brand, model = (s.strip() for s in pinned.split("|", 1))
        # Same identity rule as the searcher: Python strip().lower(), never SQL lower().
        if any(b.strip().lower() == brand.lower() and m.strip().lower() == model.lower() for b, m in rows):
            return brand, model
        print(f"(SEARCHER_PHOTOS_BIKE={pinned!r} has no photo rows in DATABASE_URL)")
        return None
    return (rows[0][0], rows[0][1]) if rows else None


# ── [TC-11] A bike that already has photos → 200 from the DB, saved 0, no CLI run ──
bike = _bike_with_photos()
if bike is None:
    print("\n[TC-11] SKIP -- no bike with photo rows confirmed in DATABASE_URL")
else:
    ph_body = {"company": bike[0], "model": bike[1]}
    t0 = time.perf_counter()
    resp = httpx.post(PHOTOS_URL, json=ph_body, headers={"X-Searcher-Key": API_KEY}, timeout=30)
    elapsed = time.perf_counter() - t0
    data = _show("[TC-11] photos: bike with stored photos", ph_body, resp)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert data["photos"], "stored photos must be returned"
    assert data["saved"] == 0, "a bike with photos must never be searched or written"
    assert data["bike_id"] is not None, data
    assert elapsed < 5, f"took {elapsed:.1f}s — a CLI run must not have started"
    print(f"OK -- {len(data['photos'])} stored photos returned in {elapsed:.2f}s without a search")

print("\nALL OK")
sys.exit(0)
