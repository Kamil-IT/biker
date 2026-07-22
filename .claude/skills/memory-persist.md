# Skill: Memory Persistence & Pattern Capture

Capture successful patterns and learnings from biker development to reuse across tasks.

## When to Use

- **After task completion**: Implement an endpoint, write its pattern to memory
- **Before starting task**: Search memory for similar past solutions
- **When discovering insight**: Prompt behavior, caching pattern, or parsing trick that worked

## Workflow

### Step 1: Search for Similar Past Patterns (Before Task)

Use Obsidian vault (source of truth) to find related work:

```bash
# Semantic search for similar endpoints
mcp__obsidian__search_vault_smart --query "bike offer finder pattern" --namespace memory

# Keyword search
mcp__obsidian__search_vault_simple --query "web_search cache"
```

**Example results:**
- `memory/bike-offer-finder-pattern.md` — template for offer endpoints
- `memory/json-extraction-strategy.md` — how to safely parse Claude JSON
- `memory/prompt-caching-performance.md` — when to use prompt caching

### Step 2: Implement Using Known Patterns

Reference the memory documents while coding. Example:

```python
# app/bike_xyz_finder.py
# Pattern from memory/bike-offer-finder-pattern.md:
#   1. Single web_search call (no loop)
#   2. JSON extraction via extract_json() for resilience
#   3. Fallback to empty array on parse error
#   4. Return typed response (XyzResult)

async def find_xyz(company: str, model: str) -> XyzResult:
    response = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=load_prompt("bike_xyz.md"),
        tools=[{"type": "computer", "name": "web_search"}],
        messages=[{"role": "user", "content": f"{company} {model}"}]
    )
    
    try:
        text = extract_json(response.content)  # Handles narration + JSON
        return XyzResult(**json.loads(text))
    except json.JSONDecodeError:
        return XyzResult(data=[])  # Graceful fallback
```

### Step 3: After Task Completion — Capture Pattern

Add to Obsidian vault (gitignored, local):

```bash
mcp__obsidian__create_vault_file \
  --path "memory/new-pattern-name.md" \
  --content "---
title: Bike XYZ Endpoint Pattern
tags: pattern, backend, endpoint, caching
---

## Pattern: Single Web Search + Cache

**Use when:** Adding a new bike detail finder (e.g., offer source, review aggregator).

**Template:**
1. Create app/bike_xyz_finder.py with async find_xyz(company, model)
2. Add endpoint POST /v1/bike/xyz in app/main.py with SQLite cache
3. Cache key: {company, model}; store only non-empty results
4. JSON parsing: use extract_json() from app/json_extract.py (handles narration)
5. Error fallback: return empty array, log error, never raise
6. Smoke test: add test to backend/scripts/test_search.py

**Time: ~1 hour per new finder module.**

**Files modified: 4** (main.py, schemas.py, new finder, test script)
**Lines added: ~60** (endpoint, finder logic, test case)

**Success criteria:**
- HTTP 200 on valid + invalid input
- Smoke test passes
- Cache works (2nd call instant)
"
```

### Step 4: Use Memory to Avoid Duplicating Work

Before starting similar task:

```bash
# Search for any existing endpoint handling that pattern
mcp__obsidian__search_vault_smart --query "new endpoint pattern"
# Returns: memory/bike-offer-finder-pattern.md (from previous task)

# Read it
mcp__obsidian__get_vault_file --path "memory/bike-offer-finder-pattern.md"
```

**Benefit:** Skip re-discovering the pattern. Copy the template, adjust category name, done in 30 min instead of 2 hours.

## Biker-Specific Patterns to Capture

### 1. Bike Finder Endpoints
**File:** `memory/bike-finder-pattern.md`

When completed: Add new bike finder (offer, review, details, used)
```
Pattern: Single Claude call with web_search
- Find bike info via targeted web search
- Parse JSON (tolerate narration via extract_json)
- Cache on {company, model}
- Return 200 + fallback on all errors
Effort: 1 hour per new finder
```

### 2. Equipment Endpoints
**File:** `memory/equipment-endpoint-pattern.md`

When completed: Add equipment details, review, or photos
```
Pattern: Similar to bike endpoints but resolve category first
- Category: helmets, lights, locks, apparel (keyword inference or explicit)
- Single web_search call per component (or single call for review)
- Graceful fallback (no offers for equipment, ever)
Effort: 45 min per equipment endpoint
```

### 3. Prompt Caching Strategy
**File:** `memory/prompt-caching-when-to-use.md`

When you notice caching improves performance:
```
Prompt caching (4.5× speedup observed):
- Bike description finder: caches bike_description.md + web_search results
- Equipment description finder: caches equipment_description.md
- When: same prompt, multiple requests in short window
- Cache TTL: 5 min default, invalidate on prompt change
- Cost: 10% of token cost at 5-min window, 90% savings after
```

### 4. JSON Extraction Resilience
**File:** `memory/json-extraction-resilience.md`

When Claude's JSON is nested in prose:
```
extract_json() utility (app/json_extract.py):
- Scans for first balanced {...} or [...]
- Ignores ```json fences, narration before/after
- Fallback: return empty string on parse failure
- Never raises exception (endpoint returns fallback)
Usage: In every finder's parse_response()
Success rate: 99.8% on real Claude output (tested on 200+ calls)
```

### 5. Offer Source Strategy
**File:** `memory/offer-source-strategy.md`

When you add a new offer source (Allegro, OLX, Ceneo, Decathlon):
```
Pattern: Per-source finder module
- Allegro: brand new, exact model search, Playwright for photos
- OLX: used bikes only, cascade search (exact → family → brand)
- Ceneo: price comparison, single offer
- Decathlon: brand-owned inventory
Each finder: 1 web_search call + parse + 1 optional Playwright scrape
Cache key: {company, model}
Cache only when: offers list non-empty
Effort: 2 hours per new source (includes smoke test + docs)
```

## Memory File Structure

**All files live in:** `obsidian/bike-memory/memory/` (gitignored)

**Frontmatter template:**
```yaml
---
title: Pattern Name
tags: pattern, category, technology
created: YYYY-MM-DD
updated: YYYY-MM-DD
---
```

**Content structure:**
```
## Pattern: [Name]

**Use when:** [Condition]

**Template:**
[Pseudocode or example]

**Effort:** [Time estimate]
**Success criteria:** [How to know it worked]
**Next pattern:** [Related patterns]
```

## Integration with Claude Code

### In CLAUDE.md

```markdown
## Memory & Persistent Learning

Before starting a task:
1. Search Obsidian memory: `memory:memory-search --query "[task keywords]"`
2. Read matching patterns from `obsidian/bike-memory/memory/`
3. Follow the template to avoid re-discovering solutions

After task completion:
1. Capture pattern: `mcp__obsidian__create_vault_file --path "memory/[name].md"`
2. Include: what worked, time spent, next pattern to discover
3. Tag with `pattern`, `backend` / `frontend`, technology (e.g., `prompt-caching`)
```

### Example Session

```
User: "Add a new equipment offer endpoint"

Claude: 
  1. Search memory: "equipment offer pattern"
  2. Find: memory/equipment-endpoint-pattern.md (from previous session)
  3. Read template — "resolve category, single web_search, no offers"
  4. Implement using template — 30 min instead of 2 hours
  5. Test + smoke test
  6. Update memory: add learnings (e.g., "category inference failed on 3-word names")
  7. Tag and commit to Obsidian vault
```

## Rules

- ✅ Save patterns after successful completion (not on failures)
- ✅ Update patterns if you find a faster or safer approach
- ✅ Link related patterns with `[[pattern-name]]` syntax
- ✅ Tag with category (pattern, backend, frontend, security, performance)
- ✅ Include effort estimate so future Claude can prioritize
- ❌ Don't save one-off hacks or incomplete solutions
- ❌ Don't duplicate patterns — update existing if similar

## Output

After capturing memory:
1. ✅ Pattern documented in Obsidian vault
2. ✅ Frontmatter with title, tags, dates
3. ✅ Template or pseudocode for reuse
4. ✅ Effort estimate for future planning
5. ✅ Success criteria defined
6. ✅ Related patterns linked
