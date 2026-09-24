# TODO_020: Adopt Graphify — Code Knowledge Graph for the Repo

**Status:** Planning complete, ready for implementation

**Goal:** Install [Graphify](https://github.com/Graphify-Labs/graphify) (PyPI
`graphifyy`) as a project-local Claude Code skill and commit a code-only
knowledge graph of `backend/` + `frontend/`, so structural questions ("who calls
`extract_json`?", "is `repository.py` dead code?") are answered from a graph
instead of by hand-grepping.

## Problem

Structural questions about this repo are currently answered by manual grep, and
the results get frozen into markdown that immediately goes stale:

- `backlog/TODO_ISSUE_012_CONSOLIDATE_JSON_EXTRACTION.md` contains a
  hand-written "Call-site inventory" table of every module with its own JSON
  extractor. That table is exactly a call graph rooted at
  `backend/app/json_extract.py::extract_json`, produced by hand.
- `backlog/TODO_009_DIRECT_SEARCH_DB_FALLBACK.md` asserts `models.py` /
  `repository.py` are "broken ORM… dead code". Nothing verifies that claim; zero
  inbound edges in a graph would.
- `CLAUDE.md` (30.7 KB) is the de-facto architecture spec and drifts:
  `POST /v1/bike/parse` exists at `backend/app/main.py:352` but is **not**
  documented there.
- The 15 near-clone `backend/app/*_finder.py` modules (77–241 LOC each) duplicate
  structure that no tool currently measures.

Repo scale is ~8,300 LOC of Python + TS/TSX across 53 source files — small
enough that a full extract is cheap, large enough that the finder-module
duplication is not eyeballable.

## Solution (Approved)

**Scope this task to the code-only, offline path.** No API keys, no LLM calls,
no CI, no git hooks.

Adoption cascade:
1. **Install the tool** — `uv tool install`, version-pinned. `uv` is already in
   use here (`backend/uv.lock`).
2. **Install the skill project-locally** — `graphify install --project` →
   `.claude/skills/graphify/SKILL.md`, matching the canonical form used by 9 of
   the 18 existing skills.
3. **Scope the index** — `.graphifyignore` to keep `.venv/`, `node_modules/`,
   the Obsidian vault and the databases out.
4. **Build and commit the graph** — `graphify extract . --code-only`, commit
   `graphify-out/` per upstream's own recommendation.
5. **Document it** — `CLAUDE.md` + `README.md`.

**Explicitly out of scope** (each has a stated reason, see Known Issues):
`graphify hook install` (broken on Windows), `graphify claude install`
(rewrites `.claude/settings.json`), the semantic docs/PDF pass (needs an API
key), the MCP server, CI integration, and indexing `backend/app/prompts/*.md`.

## Changes Required

### 1. Install the tool (local machine, not a repo change)

```powershell
uv tool install "graphifyy==0.9.25"
graphify --version
```

Pin the version. Upstream ships ~daily (193 releases, still `0.9.x`), and the
skill file must be refreshed with `graphify install --project` after any upgrade
or it warns about a version mismatch.

Do **not** use `pip install` — on Windows the CLI frequently lands off PATH and
the skill resolves Python from `graphify-out/.graphify_python`, which then points
at the wrong env (`ModuleNotFoundError: No module named 'graphify'`).
Do **not** use `uvx graphify` — the package is `graphifyy`, so it must be
`uvx --from graphifyy graphify`.

### 2. `.graphifyignore` — new file, repo root

`.gitignore` syntax; merged with `.gitignore` and evaluated last, so it can only
ever exclude more. There are no include globs and no config file — this file
plus CLI flags plus env vars is the entire configuration surface.

```
# Dependency trees
backend/.venv/
frontend/node_modules/
frontend/.vite/
frontend/dist/

# Caches and build artifacts
**/__pycache__/
*.pyc

# Local state and databases (cache.db is tracked, so .gitignore misses it)
backend/cache.db
ruvector.db
agentdb.rvf
.swarm/
.claude-flow/

# Contains a bearer token — must never be indexed
obsidian/

# Prompt corpus is runtime data, not code (see Known Issues)
backend/app/prompts/

# Stray artifacts
*.stackdump
docs/pr-evidence/
backend/scripts/ss_*.png
```

`obsidian/bike-memory/` is already in `.gitignore` and would be skipped anyway;
it is listed here explicitly because it holds a bearer token and the redundancy
is deliberate.

### 3. `.gitignore` — root, append

Upstream recommends **committing** `graphify-out/` so the map is shared rather
than rebuilt per machine. Ignore only the local-only parts:

```
graphify-out/cost.json
graphify-out/cache/
graphify-out/.graphify_python
```

### 4. `graphify install --project` — writes `.claude/`

Creates `.claude/skills/graphify/SKILL.md` plus a `references/` sidecar and
`.graphify_version`, and appends a registration block to `.claude/CLAUDE.md`.

**Review the diff before committing.** In particular confirm it did not touch
`.claude/settings.json` — that is `graphify claude install`, a different command,
which registers `PreToolUse` hooks firing on every Bash/Grep/Read. We are not
running it in this task.

### 5. Build the graph

```powershell
graphify extract . --code-only --timing
```

`--code-only` is AST-only via tree-sitter: fully local, zero LLM calls, no API
key. All grammars ship as pinned wheels, so no C toolchain is needed on Windows.

Produces `graphify-out/` — `graph.json`, `graph.html`, `GRAPH_REPORT.md`,
`manifest.json`. Rebuild incrementally later with `graphify update`.

Use `graphify .` in PowerShell, never `/graphify .` — the leading slash is a
path separator on Windows.

### 6. Documentation

- **`CLAUDE.md`:** new `## Code Graph` section under Architecture — what
  `graphify-out/` is, the rebuild command, and a note that it is orthogonal to
  both the ruflo/AgentDB agent-memory graph and the Obsidian vault.
- **`README.md`:** two lines under setup — install command and rebuild command.

## Testing

No unit tests; this is tooling. Acceptance is manual and each check must be run:

1. **Scope check** — after extract, confirm `graph.json` contains **no** node
   whose path is under `.venv/`, `node_modules/`, or `obsidian/`. A single
   `obsidian/` node is a hard failure (token exposure).
2. **Known-answer query** — `graphify query "what calls extract_json"` must
   return the call sites already enumerated by hand in
   `TODO_ISSUE_012_CONSOLIDATE_JSON_EXTRACTION.md`. Any divergence is either a
   graph bug or a stale table; record which.
3. **Dead-code check** — `graphify explain "repository.py"` — confirm whether
   `models.py` / `repository.py` really have zero inbound edges, validating or
   refuting the claim in `TODO_009`.
4. **Route coverage** — confirm all 12 handlers in `backend/app/main.py` appear,
   including the undocumented `POST /v1/bike/parse`.
5. **Cross-stack collision** — check that no backend and frontend file sharing a
   basename has been merged into one node (upstream issue #1829 — real risk in
   a `backend/` + `frontend/` monorepo).
6. **Skill smoke test** — in a fresh Claude Code session, invoke `/graphify` and
   confirm it loads and answers one query.

## Documentation Updates

- **`CLAUDE.md`** — add `## Code Graph` section
- **`README.md`** — install + rebuild commands

## Files Changed

- `.graphifyignore` — new (~30 lines)
- `.gitignore` — +3 lines
- `.claude/skills/graphify/**` — written by `graphify install --project`
- `.claude/CLAUDE.md` — registration block appended by the installer
- `graphify-out/**` — generated, committed
- `CLAUDE.md` — +1 section
- `README.md` — +2 lines

**Total scope:** ~35 hand-written lines plus generated output; fully reversible
via `graphify uninstall --purge`.

## Success Criteria

- ✅ `graphify --version` reports the pinned 0.9.25
- ✅ `graphify extract . --code-only` completes with no API key set
- ✅ `graph.json` contains zero nodes from `.venv/`, `node_modules/`, `obsidian/`
- ✅ All 12 `main.py` routes present, including `POST /v1/bike/parse`
- ✅ `extract_json` call sites match the `TODO_ISSUE_012` table (or the
  divergence is recorded)
- ✅ `.claude/settings.json` is unmodified
- ✅ `/graphify` skill loads in a fresh session
- ✅ `CLAUDE.md` and `README.md` updated

## Known Issues / Decisions

- **Version pinned to 0.9.25.** Repo created 2026-04-03, 193 PyPI releases,
  still `0.9.x`, ~daily cadence, 614 open issues. Do not float the version.
  Re-run `graphify install --project` after every upgrade.
- **Skip `graphify hook install`.** Upstream #2126: the post-commit hook's
  interpreter allowlist rejects backslashes, so it fails silently on Windows
  paths. Rebuild manually with `graphify update` instead. Revisit when fixed.
- **Skip `graphify claude install`.** It writes `PreToolUse` hooks into
  `.claude/settings.json` that fire on every Bash/Grep/Read, and `--strict`
  blocks the first raw source read of a session. That is a large behavioural
  change to every session in this repo; it should be its own task with its own
  review, not a side effect of adopting the tool.
- **PowerShell 5.1 risk.** Upstream #1637: the skill's inline Python snippets
  fail under PowerShell 5.1 quoting and Windows multiprocessing. This shell is
  5.1. If the `/graphify` skill misbehaves, fall back to the headless
  `graphify extract` / `graphify query` CLI — that is the primary path here
  regardless. Upstream #1742 (`Expand-Archive` error) is also Windows-only.
- **Prompts excluded from the index.** `backend/app/prompts/*.md` (50 files) are
  runtime data loaded by filename convention from `categories.py` /
  `equipment_categories.py`. Tree-sitter markdown yields only headings, so
  indexing them adds noise without the edge that would matter
  (module → prompt file via string literal). Worth revisiting: it would identify
  the apparently-orphaned `bike_offer.md`, `bike_details.md`,
  `bike_details_fields.md`, `allegro_image_extractor_prompt.md`.
- **Leiden silently downgrades to Louvain.** The `[leiden]` extra depends on
  `graspologic; python_version < '3.13'`; on newer interpreters it is simply not
  installed and `graphify/cluster.py` falls back to networkx Louvain. Accepted —
  community detection quality is not why we are adopting this. To get real
  Leiden: `uv tool install --python 3.12 "graphifyy[leiden]"`.
- **Output directory is hardcoded** to `graphify-out/`. No flag relocates it
  (`--output` on `extract` is ignored — upstream #2004).
- **Prompt-cache side effect.** Writing `graph.json` into the workspace
  invalidates Claude Code's prompt cache on each extract. Upstream suggests
  adding `graphify-out/` to `.claudeignore`; this repo has no `.claudeignore`
  today, so creating one is deferred until the churn is actually observed.
- **Query logging.** Upstream README contradicts itself: the Privacy section
  says queries are logged to `~/.cache/graphify-queries.log` by default, the
  env-var table (newer, per #1797) says off unless enabled. Set
  `GRAPHIFY_QUERY_LOG_DISABLE=1` to be certain.
- **Not a duplicate of existing infrastructure.** The ruflo/AgentDB stack
  (`ruvector.db`, `agentdb.rvf`, `agentdb_graph-query`) is an *agent-memory*
  graph, and CLAUDE.md already deprioritises it in favour of the Obsidian vault.
  Graphify is a *code-structure* graph — orthogonal to both.
- **License:** Apache-2.0 (the package also ships `LICENSE-MIT` and `NOTICE`).
  Third-party summaries calling it MIT-only are wrong.
- **Read the `v8` branch, not `main`** — `main`'s README is stale.

## Rollback

```powershell
graphify uninstall --purge     # removes the skill, the CLAUDE.md block, graphify-out/
uv tool uninstall graphifyy
```

Then delete `.graphifyignore`, revert the 3 `.gitignore` lines, and revert the
`CLAUDE.md` / `README.md` sections. Nothing in `backend/` or `frontend/` is
touched by this task, so there is no runtime impact to roll back.

## Related

- `backlog/TODO_ISSUE_012_CONSOLIDATE_JSON_EXTRACTION.md` — its hand-written
  call-site inventory is the motivating use case
- `backlog/TODO_009_DIRECT_SEARCH_DB_FALLBACK.md` — its "dead ORM" claim is
  test #3 above
- `backlog/TODO_017_BIKE_DETAILS_DATA_MODEL.md` — a graph of `schemas.py` /
  `models.py` is useful input to that redesign

---

**Created:** 2026-07-23
**Assigned to:** architect (design ✅), coder (implement), tester (verify), reviewer (approve)
**Ready for:** Implementation
