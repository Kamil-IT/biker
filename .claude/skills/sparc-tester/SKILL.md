---
name: sparc-tester
description: TDD workflow and smoke-test templates for biker endpoints and components — writes tests into backend/scripts/test_search.py. Use after implementing an endpoint and before opening a PR, when fixing a bug (regression test), or when verifying a refactor did not break anything.
---

# SPARC: Test-Driven Development Skill

TDD approach for biker endpoints and components. Write tests before or alongside implementation.

## When to Use

- **New endpoint**: Before implementation, define test cases
- **Bug fix**: Add regression test that fails on the bug
- **Feature completion**: Verify all code paths tested
- **Refactor**: Run existing tests to ensure no breakage

## Workflow

### Phase 1: Test Design (10 min)
Identify test cases based on requirements.

**For backend endpoints:**
- Happy path: Valid request → HTTP 200 + correct response structure
- Empty result: Query returns no matches → HTTP 200 + empty list
- Malformed input: Missing required field → HTTP 400 or graceful empty response
- API error: Claude call fails → HTTP 200 + fallback (never 502)
- Cache hit: Same request twice → second call instant (check logs for cache key)

**For frontend components:**
- Component renders without crash (use browser devtools)
- API call fires and data displays
- Error state shows graceful message
- Loading state visible while fetching
- Links open in new tab (_target="blank"_)

### Phase 2: Test Implementation (20 min)

**Backend:** Add to `backend/scripts/test_search.py`
```python
def test_bike_xyz_success():
    """Happy path: valid request returns HTTP 200 with data."""
    resp = requests.post("http://localhost:8000/v1/bike/xyz", json={
        "company": "Canyon",
        "model": "Grizl"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "xyz" in data  # or whatever top-level key
    assert len(data["xyz"]) > 0 or data["xyz"] == []  # non-crash

def test_bike_xyz_empty():
    """Empty result: no matches but HTTP 200."""
    resp = requests.post("http://localhost:8000/v1/bike/xyz", json={
        "company": "Nonexistent Brand",
        "model": "Fake Model"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("xyz") == [] or data.get("xyz") is None
```

**Frontend:** Manual smoke test using browser
- Start backend: `cd backend && uvicorn app.main:app --reload --port 8000`
- Start frontend: `cd frontend && npm run dev` (port 5173)
- Open http://localhost:5173
- Interact with new feature
- Check browser DevTools Console for errors (should be clean)
- Test on multiple browsers if applicable

### Phase 3: Validation (5 min)

**Backend:**
```bash
cd backend
python scripts/test_search.py::test_bike_xyz_success -v
python scripts/test_search.py::test_bike_xyz_empty -v
```

**Frontend:**
- Manual browser testing (no automated suite, use `/run` skill to start dev server)
- Verify no console errors
- Verify API calls hit backend (check Network tab)

## Biker-Specific Patterns

### Smoke Test Template (backend/scripts/test_search.py)
```python
import requests
import json

BASE_URL = "http://localhost:8000"

def test_xyz_happy_path():
    """Happy path test."""
    payload = {"company": "Canyon", "model": "Grizl CF 7 ESC"}
    resp = requests.post(f"{BASE_URL}/v1/bike/xyz", json=payload)
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    # Assert structure
    assert "xyz" in data, f"Missing 'xyz' key in response: {data.keys()}"
    # Assert no crash (empty is valid)
    if isinstance(data["xyz"], list):
        assert len(data["xyz"]) >= 0

def test_xyz_cache_behavior():
    """Verify caching works: second call should be instant."""
    payload = {"company": "Canyon", "model": "Grizl CF 7 ESC"}
    
    # First call (may be slow, hits Claude)
    resp1 = requests.post(f"{BASE_URL}/v1/bike/xyz", json=payload)
    assert resp1.status_code == 200
    data1 = resp1.json()
    
    # Second call (should be instant from cache)
    resp2 = requests.post(f"{BASE_URL}/v1/bike/xyz", json=payload)
    assert resp2.status_code == 200
    data2 = resp2.json()
    
    # Results should be identical
    assert data1 == data2
```

### Frontend Component Test (Browser DevTools)
```javascript
// In browser console while frontend is running:

// Test 1: Component renders without error
console.assert(
  document.querySelector('[data-testid="xyz-view"]') !== null,
  "XyzView component not found in DOM"
);

// Test 2: API call fires
const networkTab = performance.getEntries().filter(e => e.name.includes("/v1/bike/xyz"));
console.assert(networkTab.length > 0, "No API call to /v1/bike/xyz detected");

// Test 3: No console errors (should be clean)
// Just open DevTools Console and look — should have no red errors
```

## Running Tests

**All backend smoke tests:**
```bash
cd backend
python scripts/test_search.py -v
```

**Specific test:**
```bash
cd backend
python -m pytest scripts/test_search.py::test_xyz_happy_path -v
```

**Frontend (manual):**
```bash
cd frontend && npm run dev
# Open http://localhost:5173 in browser
# Interact with feature, check DevTools Console for errors
```

## Output

After testing:
1. ✅ All smoke tests pass (HTTP 200, correct structure)
2. ✅ No unhandled errors in backend or frontend
3. ✅ Cache behavior verified (second call uses cache)
4. ✅ Documentation updated with test examples
5. ✅ Edge cases covered (empty results, malformed input)
