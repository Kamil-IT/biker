"""Smoke test for the searcher service — run it against a live server on port 8100.

    cd searcher && ..\\backend\\.venv\\Scripts\\python.exe scripts/test_searcher.py

Reads SEARCHER_URL (default http://localhost:8100) and SEARCHER_API_KEY from the
environment or searcher/.env. Every case here is free: health, auth (401) and
validation (422) on both search routes — no `claude -p` run is ever started, so
the suite costs nothing and finishes in seconds. The one paid, live search of the
whole test set is `backend/scripts/test_search.py` `case_decathlon_search`
(through the backend proxy, only when the searcher is up); the OLX path and the
DB writes are covered by the manual test plans under docs/testing/.
"""
import json
import os
import sys
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

print("\nALL OK")
sys.exit(0)
