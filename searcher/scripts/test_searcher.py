"""Smoke test for the searcher service — run it against a live server on port 8100.

    cd searcher && ..\\backend\\.venv\\Scripts\\python.exe scripts/test_searcher.py

Reads SEARCHER_URL (default http://localhost:8100), SEARCHER_API_KEY and
DATABASE_URL from the environment or searcher/.env. TC-5 performs ONE real OLX
search through the claude CLI (Trek Marlin 5, ~1–2 min with the Playwright
photo scrape) and TC-6 checks the rows it wrote in the database; TC-8 then
performs ONE real Decathlon search (Rockrider ST 100, ~1 min, no Playwright)
and TC-9 checks its rows (source decathlon.pl, no photo rows).
"""
import json
import os
import sys
import time as _time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
# Prices like "1 200 zł" must survive a cp1252 Windows console.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = os.getenv("SEARCHER_URL", "http://localhost:8100").strip().rstrip("/")
API_KEY = os.getenv("SEARCHER_API_KEY", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
HEALTH_URL = f"{BASE_URL}/health"
SEARCH_URL = f"{BASE_URL}/v1/search/olx"
DECATHLON_URL = f"{BASE_URL}/v1/search/decathlon"
SEARCH_TIMEOUT = 900  # one CLI run (≤ 300 s by default) + photo scraping

assert API_KEY, "SEARCHER_API_KEY must be set (env or searcher/.env)"
assert DATABASE_URL, "DATABASE_URL must be set (env or searcher/.env)"


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
    print("WARNING: /health reports no claude CLI — the real search below will fail")
print(f"OK -- health: claude_cli={data.get('claude_cli')!r} database={data['database']}")

# ── [TC-2] No X-Searcher-Key → 401 ──
body = {"company": "Trek", "model": "Marlin 5"}
resp = httpx.post(SEARCH_URL, json=body, timeout=30)
_show("[TC-2] no key", body, resp)
assert resp.status_code == 401, f"Expected 401 without a key, got {resp.status_code}"
print("OK -- 401 without X-Searcher-Key")

# ── [TC-3] Wrong X-Searcher-Key → 401 ──
resp = httpx.post(SEARCH_URL, json=body, headers={"X-Searcher-Key": API_KEY + "-wrong"}, timeout=30)
_show("[TC-3] wrong key", body, resp)
assert resp.status_code == 401, f"Expected 401 with a wrong key, got {resp.status_code}"
print("OK -- 401 with a wrong X-Searcher-Key")

# ── [TC-4] Empty company → 422 (validation runs after auth) ──
bad_body = {"company": "", "model": "x"}
resp = httpx.post(SEARCH_URL, json=bad_body, headers={"X-Searcher-Key": API_KEY}, timeout=30)
_show("[TC-4] empty company", bad_body, resp)
assert resp.status_code == 422, f"Expected 422 for an empty company, got {resp.status_code}"
print("OK -- 422 for an empty company")

# ── [TC-5] One real search: Trek Marlin 5 through the claude CLI ──
print(f"\n[TC-5] POST {SEARCH_URL} — real OLX search, this takes a minute or two...")
t0 = _time.perf_counter()
resp = httpx.post(SEARCH_URL, json=body, headers={"X-Searcher-Key": API_KEY}, timeout=SEARCH_TIMEOUT)
elapsed = _time.perf_counter() - t0
data = _show("[TC-5] real search", body, resp)
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
assert isinstance(data["offers"], list), "offers must be a list"
assert isinstance(data["info"], str), "info must be a string"
assert isinstance(data["bike_id"], int), f"bike_id must be an int, got {data['bike_id']!r}"
assert data["saved"] == len(data["offers"]), \
    f"saved ({data['saved']}) must equal the offers returned ({len(data['offers'])})"
for o in data["offers"]:
    assert o["url"].startswith("https://www.olx.pl/"), f"offer url must be on olx.pl: {o['url']!r}"
    assert o["is_new"] is False, "used offers are never new"
    assert o["source"] == "olx.pl", f"source must be olx.pl, got {o['source']!r}"
    assert isinstance(o["photos"], list), "photos must be a list"
print(f"OK -- {len(data['offers'])} offer(s) in {elapsed:.1f}s, bike_id={data['bike_id']}, saved={data['saved']}")
if not data["offers"]:
    print("WARNING: the search returned 0 offers — check the searcher log (claude CLI stderr) before trusting this")

# ── [TC-6] The rows are in the database ──
print(f"\n[TC-6] checking bike_offer / bike_offer_photos for bike_id={data['bike_id']}")
engine = create_engine(DATABASE_URL)
with engine.connect() as conn:
    offer_rows = conn.execute(
        text("SELECT id, url FROM bike_offer WHERE bike_id = :b AND source = 'olx.pl' ORDER BY id"),
        {"b": data["bike_id"]},
    ).fetchall()
    photo_rows = conn.execute(
        text(
            "SELECT count(*) FROM bike_offer_photos WHERE bike_offer_id IN "
            "(SELECT id FROM bike_offer WHERE bike_id = :b AND source = 'olx.pl')"
        ),
        {"b": data["bike_id"]},
    ).scalar()
engine.dispose()
print(f"bike_offer rows: {len(offer_rows)}, bike_offer_photos rows: {photo_rows}")
assert len(offer_rows) == len(data["offers"]), \
    f"expected {len(data['offers'])} bike_offer rows with source olx.pl, found {len(offer_rows)}"
assert {r.url for r in offer_rows} == {o["url"] for o in data["offers"]}, "stored urls differ from the response"
assert photo_rows >= 0
assert photo_rows == sum(len(o["photos"]) for o in data["offers"]), \
    f"expected {sum(len(o['photos']) for o in data['offers'])} photo rows, found {photo_rows}"
print("OK -- database holds exactly the returned offers and their photos")

# ── [TC-7] POST /v1/search/decathlon without X-Searcher-Key → 401 ──
# The identity the app already carries for this bike (`Decathlon` / `Rockrider ST 100`),
# not a fresh `Rockrider` / `ST 100`: a decathlon.pl product URL is globally unique in
# bike_offer, so a duplicate identity would capture it and starve the one the UI opens.
dec_body = {"company": "Decathlon", "model": "Rockrider ST 100"}
resp = httpx.post(DECATHLON_URL, json=dec_body, timeout=30)
_show("[TC-7] decathlon: no key", dec_body, resp)
assert resp.status_code == 401, f"Expected 401 without a key, got {resp.status_code}"
print("OK -- 401 without X-Searcher-Key on /v1/search/decathlon")

# ── [TC-8] One real Decathlon search: Rockrider ST 100 through the claude CLI (no Playwright) ──
print(f"\n[TC-8] POST {DECATHLON_URL} — real Decathlon search, this takes about a minute...")
t0 = _time.perf_counter()
resp = httpx.post(DECATHLON_URL, json=dec_body, headers={"X-Searcher-Key": API_KEY}, timeout=SEARCH_TIMEOUT)
elapsed = _time.perf_counter() - t0
dec = _show("[TC-8] real decathlon search", dec_body, resp)
assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text[:300]}"
assert isinstance(dec["offers"], list), "offers must be a list"
assert isinstance(dec["info"], str), "info must be a string"
assert isinstance(dec["bike_id"], int), f"bike_id must be an int, got {dec['bike_id']!r}"
assert dec["saved"] == len(dec["offers"]), \
    f"saved ({dec['saved']}) must equal the offers returned ({len(dec['offers'])})"
for o in dec["offers"]:
    assert o["url"].startswith("https://www.decathlon.pl/"), f"offer url must be on decathlon.pl: {o['url']!r}"
    assert o["source"] == "decathlon.pl", f"source must be decathlon.pl, got {o['source']!r}"
    assert o["photos"] == [], f"decathlon offers carry no photos, got {o['photos']!r}"
    assert isinstance(o["is_new"], bool), f"is_new must be a bool, got {o['is_new']!r}"
print(f"OK -- {len(dec['offers'])} offer(s) in {elapsed:.1f}s, bike_id={dec['bike_id']}, saved={dec['saved']}")
if not dec["offers"]:
    print("WARNING: the Decathlon search returned 0 offers — check the searcher log (claude CLI stderr) before trusting this")

# ── [TC-9] The decathlon.pl rows are in the database, without photo rows ──
print(f"\n[TC-9] checking bike_offer (source decathlon.pl) for bike_id={dec['bike_id']}")
engine = create_engine(DATABASE_URL)
with engine.connect() as conn:
    dec_rows = conn.execute(
        text("SELECT id, url FROM bike_offer WHERE bike_id = :b AND source = 'decathlon.pl' ORDER BY id"),
        {"b": dec["bike_id"]},
    ).fetchall()
    dec_photo_rows = conn.execute(
        text(
            "SELECT count(*) FROM bike_offer_photos WHERE bike_offer_id IN "
            "(SELECT id FROM bike_offer WHERE bike_id = :b AND source = 'decathlon.pl')"
        ),
        {"b": dec["bike_id"]},
    ).scalar()
engine.dispose()
print(f"bike_offer rows: {len(dec_rows)}, bike_offer_photos rows: {dec_photo_rows}")
if dec["offers"]:
    assert len(dec_rows) == len(dec["offers"]), \
        f"expected {len(dec['offers'])} bike_offer rows with source decathlon.pl, found {len(dec_rows)}"
    assert {r.url for r in dec_rows} == {o["url"] for o in dec["offers"]}, "stored urls differ from the response"
else:
    # A run that found nothing keeps the rows already stored, so older rows may
    # legitimately be there — only the "no photos" invariant can be checked.
    print("WARNING: 0 offers returned — stored rows (if any) predate this run; the store path was NOT exercised")
assert dec_photo_rows == 0, f"decathlon offers must have no photo rows, found {dec_photo_rows}"
print("OK -- database holds exactly the returned decathlon.pl offers and no photos")

print("\nALL OK")
sys.exit(0)
