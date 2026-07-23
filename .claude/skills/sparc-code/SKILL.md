---
name: sparc-code
description: Structured Specification → Pseudocode → Implementation → Testing workflow for biker code. Use when adding a POST /v1/bike/* or /v1/equipment/* endpoint, a new app/*_finder.py module, a new frontend component, or a refactor touching 3+ files.
---

# SPARC: Code Implementation Skill

Structured code implementation for biker backend endpoints and frontend components.

## When to Use

- **New backend endpoint**: POST /v1/bike/* or /v1/equipment/*
- **New finder module**: app/bike_*_finder.py or app/equipment_*_finder.py
- **New frontend view**: src/components/*.tsx
- **Multi-file refactor**: affects 3+ files across backend/frontend

## Workflow

### Phase 1: Specification (5 min)
Analyze requirements and existing patterns in the codebase.
- For **endpoints**: Review app/main.py for route structure, app/schemas.py for request/response models
- For **finders**: Study app/bike_finder.py, app/bike_review_finder.py as templates
- For **frontend**: Check src/App.tsx for state management, src/components/ for component patterns

### Phase 2: Pseudocode (10 min)
Outline the implementation in pseudocode or comments.
- Backend: Data flow → API call → parsing → caching → response
- Frontend: Component state → API call → UI update → error handling

### Phase 3: Implementation (30 min)
Write production code following biker conventions:
- **Python**: Type hints, docstrings only on public functions, 500-line file limit
- **TypeScript**: src/types.ts for shared models, strict null checks, Tailwind classes
- **Caching**: Always use SQLite cache for Claude API calls (see app/cache.py pattern)
- **Error handling**: Return 200 with empty/fallback response, never 502 on JSON parse error

### Phase 4: Testing (15 min)
Write smoke tests in the appropriate test script:
- **Backend**: Add test to backend/scripts/test_search.py (single file for all smoke tests)
- **Frontend**: Manual browser testing against running backend (no unit tests for views)

## Biker-Specific Patterns

### Backend Endpoint Template
```python
# app/main.py
@app.post("/v1/bike/xyz")
async def get_bike_xyz(req: XyzRequest) -> XyzResponse:
    _fields = {"company": req.company, "model": req.model}  # cache key
    cached = get_cached("/v1/bike/xyz", _fields, XyzResponse)
    if cached is not None:
        return cached
    
    result = await call_finder(req)  # your finder logic
    
    if result.data:  # only cache non-empty results
        set_cached("/v1/bike/xyz", _fields, result)
    return result
```

### Finder Module Template
```python
# app/bike_xyz_finder.py
async def find_xyz(company: str, model: str) -> XyzResult:
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=load_prompt("bike_xyz.md"),
        tools=[{"type": "computer", "name": "web_search", ...}],
        messages=[{"role": "user", "content": f"{company} {model}"}]
    )
    return parse_response(response)  # see app/json_extract.py

def parse_response(response: Message) -> XyzResult:
    text = extract_json(response.content)  # shared parser
    return XyzResult(**json.loads(text))
```

### Frontend Component Template
```tsx
// src/components/XyzView.tsx
interface Props { xyz: XyzData }
export function XyzView({ xyz }: Props) {
  const [state, setState] = useState<XyzState>(...)
  
  useEffect(() => {
    // fetch data from backend
  }, [])
  
  return (
    <div className="space-y-4">
      {/* content */}
    </div>
  )
}
```

## Output

After implementation:
1. ✅ Code passes syntax check
2. ✅ Smoke test passes (calls endpoint, asserts HTTP 200)
3. ✅ Documentation updated (README.md, CLAUDE.md if new pattern)
4. ✅ Cache pattern used for API calls (backend only)
5. ✅ Error handling graceful (return fallback, never 502)
