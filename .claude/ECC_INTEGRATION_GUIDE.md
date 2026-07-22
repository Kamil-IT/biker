# ECC Integration Guide

This guide explains the ECC (Agent Harness Performance Optimization System) integration into the biker project.

## What is ECC?

ECC is an open-source system providing **449 production-ready skills** for structured AI agent workflows. Skills are reusable workflow templates organized by domain (backend, frontend, security, testing, DevOps, etc.).

**Key features:**
- Pre-built workflow patterns (avoid re-discovering solutions)
- Language-specific best practices (Python, Go, TypeScript, Rust, etc.)
- Security & compliance templates (HIPAA, DeFi, healthcare)
- Framework-specific patterns (FastAPI, React, Django, SpringBoot, etc.)
- Test-driven development workflows
- Agent orchestration patterns

## What's Included in This PR

### Core Skills Created (Biker-Specific)

4 skills tailored to your biker project workflow:

1. **sparc-code.md** — Structured code implementation
   - Phases: Specification → Pseudocode → Implementation → Testing
   - Backend endpoint template with SQLite caching
   - Finder module template for Claude integration
   - Frontend component template

2. **sparc-tester.md** — Test-driven development
   - Backend smoke test templates (`backend/scripts/test_search.py`)
   - Frontend manual testing via browser DevTools
   - Cache behavior verification

3. **sparc-security-review.md** — Security audit for APIs
   - Input validation (SQL injection, prompt injection, length bounds)
   - API key safety and model verification
   - Error handling (graceful fallbacks, never 50x)
   - Pen-test examples using cURL

4. **memory-persist.md** — Pattern capture to Obsidian vault
   - Search for past solutions before coding
   - Capture learnings after task completion
   - Track effort estimates and success criteria

### Updated Documentation

- **CLAUDE.md** — New "ECC Skill Routing" section
  - Task type → Skill recommendation table
  - Example workflow for adding endpoints
  - Skills directory overview

### Download Scripts

Two scripts to fetch all 449 ECC skills:

- **fetch_ecc_skills.py** — Python-based downloader (recommended)
- **fetch-all-ecc-skills.ps1** — PowerShell alternative

## How to Use

### Immediate Use (4 Core Skills)

The 4 biker-specific skills in `.claude/skills/` are ready to use now:

```bash
# When implementing a new endpoint
/sparc:code        # Design endpoint + finder
/sparc:tester      # Write smoke tests  
/sparc:security-review  # Audit for security
/memory:persist     # Capture pattern for future reuse
```

**Example workflow:**
```
User: "Add new offer source endpoint"

1. Invoke /sparc:code
   → Follows Specification → Pseudocode → Implementation → Testing phases
   → Creates app/bike_xyz_finder.py + POST /v1/bike/xyz route
   
2. Invoke /sparc:tester  
   → Generates smoke test in backend/scripts/test_search.py
   → Verifies cache behavior, error handling
   
3. Invoke /sparc:security-review
   → Checks input validation, API key safety, error responses
   → Runs pen-tests (prompt injection, boundary conditions)
   
4. Invoke /memory:persist
   → Saves "New offer finder pattern" to Obsidian vault
   → Next time: search vault, reuse template, save 1.5 hours
```

### Get All 449 ECC Skills

Run the download script to fetch the complete ECC library:

#### Option 1: Python (Recommended)
```bash
# Install requests if needed
pip install requests

# Run downloader
python fetch_ecc_skills.py
```

**Output:** All 449 skills in `.claude/skills/` (organized alphabetically)

#### Option 2: PowerShell
```powershell
powershell -ExecutionPolicy Bypass -File fetch-all-ecc-skills.ps1
```

#### Option 3: Manual cURL/Wget
```bash
# Download one skill at a time
curl -O "https://raw.githubusercontent.com/affaan-m/ECC/main/skills/sparc-code.md"
```

## Available ECC Skills by Category

### AI & Agentic Systems (50+ skills)
- agent-architecture-audit, agent-eval, agent-introspection-debugging
- agentic-engineering, agentic-os, autonomous-agent-harness
- agent-payment-x402, agent-self-evaluation, agent-sort, agent-harness-construction

### Development & Programming (180+ skills)

**Language-specific:**
- Angular, C++, C#, Dart/Flutter, Go, Java, Kotlin, PHP, Python, Rust, Swift, TypeScript
- Pattern skills: `python-patterns`, `rust-patterns`, `golang-patterns`, etc.
- Testing: `python-testing`, `rust-testing`, `java-testing`, etc.
- Security: `golang-security`, `kotlin-security`, etc.

**Frameworks:**
- FastAPI, Django, Flask (Python)
- React, Vue, Angular, Next.js (JavaScript/TypeScript)
- Spring Boot, Spring Cloud (Java)
- Gin, Echo (Go)
- Tokio, Actix (Rust)

**Testing:**
- TDD workflows across languages
- E2E testing patterns
- Regression testing for AI
- Continuous learning via tests

### Infrastructure & DevOps (60+ skills)
- Docker, Kubernetes, deployment patterns
- GitHub operations, Git workflows
- CI/CD patterns
- Terraform, configuration management
- Monitoring, observability, logging

### Specialized Domains
- **Healthcare:** HIPAA compliance, PHI handling, EMR patterns, CDSS (clinical decision support)
- **Blockchain/DeFi:** Token decimals, AMM security, trading agent patterns
- **Finance:** Billing ops, investor materials, market intelligence
- **E-commerce:** Inventory planning, logistics, returns management
- **Compliance:** Customs/trade, accessibility (a11y), design systems

### Business & Operations (30+ skills)
- Customer billing ops, CRM patterns
- Automation audits, workflow optimization
- Brand discovery, voice guidelines
- Analytics dashboards, reporting
- Email ops, messaging operations

## File Organization

```
.claude/
├── skills/                          # All 449 ECC skills
│   ├── sparc-code.md               # (Biker-specific)
│   ├── sparc-tester.md             # (Biker-specific)
│   ├── sparc-security-review.md    # (Biker-specific)
│   ├── memory-persist.md           # (Biker-specific)
│   │
│   # Framework-specific (sample)
│   ├── fastapi-patterns.md
│   ├── react-patterns.md
│   ├── react-testing.md
│   ├── python-patterns.md
│   │
│   # Testing (sample)
│   ├── tdd-workflow.md
│   ├── e2e-testing.md
│   ├── python-testing.md
│   │
│   # Security (sample)
│   ├── security-review.md
│   ├── security-scan.md
│   ├── hipaa-compliance.md
│   ├── defi-amm-security.md
│   │
│   # ... 440+ more skills organized alphabetically
│
├── settings.json
├── CLAUDE.md                        # Updated with ECC routing table
└── ECC_INTEGRATION_GUIDE.md         # This file
```

## Recommended Skills for Biker Project

Based on your tech stack (Python FastAPI + React TypeScript + SQLite):

| Category | Skill | Use Case |
|----------|-------|----------|
| **Backend** | `fastapi-patterns.md` | Learn FastAPI best practices |
| | `python-patterns.md` | Python code patterns |
| | `python-testing.md` | Unit/integration tests |
| **Frontend** | `react-patterns.md` | React component patterns |
| | `react-testing.md` | Frontend test strategies |
| | `typescript.md` (if exists) | TypeScript best practices |
| **Database** | `postgres-patterns.md` | SQL optimization |
| **Testing** | `tdd-workflow.md` | Test-driven development |
| | `e2e-testing.md` | End-to-end testing |
| **Security** | `security-review.md` | Security audit checklist |
| | `security-scan.md` | Automated security scanning |
| **DevOps** | `docker-patterns.md` | Docker/containerization |
| | `github-ops.md` | GitHub workflows/CI-CD |
| **AI Agents** | `autonomous-agent-harness.md` | Agent orchestration |
| | `team-agent-orchestration.md` | Multi-agent coordination |

## Next Steps

1. **Review this PR** — Check the 4 core biker-specific skills
2. **Merge the PR** — Adds ECC integration framework
3. **Download all skills** (optional):
   ```bash
   python fetch_ecc_skills.py
   ```
4. **Start using skills**:
   ```bash
   # When implementing features
   /sparc:code
   /sparc:tester
   /sparc:security-review
   /memory:persist
   ```
5. **Explore relevant skills**:
   - `fastapi-patterns.md` for backend
   - `react-patterns.md` for frontend
   - `python-testing.md` for tests
   - etc.

## Implementation Benefits

- **Reusable patterns**: 449 pre-written templates, not starting from scratch
- **Language-specific best practices**: Organized by Python, Go, TypeScript, Rust, etc.
- **Security checklists**: Pre-built templates for common vulnerabilities
- **Framework expertise**: FastAPI, React, Django, Spring Boot, etc.
- **Avoid bikeshedding**: Validated patterns across 100+ projects
- **Onboarding**: New team members learn faster using established patterns

## References

- **ECC Repository**: https://github.com/affaan-m/ECC
- **Skills Directory**: https://github.com/affaan-m/ECC/tree/main/skills
- **Your Memory System**: `obsidian/bike-memory/` (Obsidian vault)

## Questions?

Refer to:
- CLAUDE.md — Project-specific rules
- Individual skill files — Detailed templates and examples
- ECC README — Complete documentation at the source repo
