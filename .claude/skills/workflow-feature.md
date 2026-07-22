# workflow-feature

Multi-task batch processor: scan backlog, spawn workers, track completion, loop until done.

---

## Message Structures

### TASK_CONTEXT_MESSAGE (Coordinator → Worker)
```json
{
  "messageType": "task:start",
  "coordinator": "task-orchestrator",
  "timestamp": "[ISO 8601]",
  "task": {
    "id": "[TASK_ID]",
    "name": "[TASK_NAME]",
    "description": "[FULL_DESCRIPTION]",
    "backlogFile": "[FILENAME]",
    "backlogPath": "[FULL_PATH]"
  },
  "worktree": {
    "path": "[WORKTREE_PATH]",
    "branch": "feature/[TASK_ID]-[SLUG]",
    "mainPath": "[MAIN_PROJECT_PATH]"
  },
  "ports": {
    "backend": [PORT_NUMBER],
    "frontend": [PORT_NUMBER + 173]
  },
  "instructions": {
    "command": "feature-full-impl",
    "expectedSteps": ["checkout branch", "implement feature", "run tests", "create PR", "report completion"],
    "reportOn": ["test results", "test coverage", "PR URL", "any blockers"]
  },
  "agentContext": {
    "workerAgentName": "feature-worker-[TASK_ID]",
    "permissions": "bypassPermissions",
    "canSpawnSubAgents": true,
    "tools": ["all"]
  }
}
```

### TASK_COMPLETION_MESSAGE (Worker → Coordinator)
```json
{
  "messageType": "task:complete",
  "workerAgent": "feature-worker-[TASK_ID]",
  "timestamp": "[ISO 8601]",
  "task": {
    "id": "[TASK_ID]",
    "name": "[TASK_NAME]",
    "status": "COMPLETE"
  },
  "results": {
    "implementation": {
      "status": "SUCCESS",
      "filesChanged": [NUMBER],
      "linesAdded": [NUMBER],
      "linesDeleted": [NUMBER]
    },
    "tests": {
      "status": "PASSED",
      "total": [NUMBER],
      "passed": [NUMBER],
      "failed": 0,
      "skipped": [NUMBER],
      "coverage": "[PERCENTAGE]%"
    },
    "pullRequest": {
      "url": "[PR_URL]",
      "number": [PR_NUMBER],
      "branch": "feature/[TASK_ID]-[SLUG]",
      "title": "[PR_TITLE]",
      "status": "ready_for_review"
    }
  },
  "logs": {
    "implementation": "[SUMMARY]",
    "testRun": "[SUMMARY]",
    "pr": "[SUMMARY]"
  },
  "nextAction": "awaiting_coordinator",
  "readyForNextTask": true
}
```

### TASK_BLOCKER_MESSAGE (Worker → Coordinator)
```json
{
  "messageType": "task:blocker",
  "workerAgent": "feature-worker-[TASK_ID]",
  "timestamp": "[ISO 8601]",
  "task": {
    "id": "[TASK_ID]",
    "status": "BLOCKED"
  },
  "error": {
    "type": "[test_failure|build_error|architecture_issue]",
    "severity": "[high|medium|low]",
    "message": "[ERROR_MESSAGE]",
    "details": "[DETAILED_CONTEXT]",
    "file": "[FILE_PATH]",
    "line": [LINE_NUMBER]
  },
  "assistanceNeeded": {
    "type": "[code_review|debugging|architecture_decision]",
    "description": "[WHAT_IS_NEEDED]",
    "context": "[CONTEXT]"
  },
  "canContinue": false,
  "awaitingInput": true
}
```

### COORDINATOR_SCAN_MESSAGE (Internal)
```json
{
  "messageType": "coordinator:scan",
  "timestamp": "[ISO 8601]",
  "backlogPath": "[BACKLOG_PATH]",
  "todoTasks": [
    {
      "id": "[ID]",
      "filename": "[FILENAME]",
      "name": "[NAME]",
      "priority": [NUMBER],
      "status": "pending"
    }
  ],
  "doneTasks": [
    {
      "id": "[ID]",
      "filename": "[FILENAME]",
      "completedAt": "[ISO 8601]"
    }
  ],
  "currentlyProcessing": {
    "taskId": "[TASK_ID]",
    "agentName": "feature-worker-[TASK_ID]",
    "started": "[ISO 8601]"
  }
}
```

### SUB_AGENT_SPAWN_MESSAGE (Worker → Sub-agent)
```json
{
  "messageType": "agent:spawn-request",
  "parentAgent": "feature-worker-[TASK_ID]",
  "timestamp": "[ISO 8601]",
  "subAgentConfig": {
    "name": "feature-worker-[TASK_ID]-[ROLE]",
    "role": "[ROLE]",
    "task": {
      "id": "[TASK_ID]-[SUBTASK]",
      "description": "[DESCRIPTION]"
    },
    "context": {
      "worktreePath": "[WORKTREE_PATH]",
      "branch": "feature/[TASK_ID]-[SLUG]",
      "parentTask": "[TASK_ID]"
    },
    "permissions": "bypassPermissions",
    "canSpawnFurther": false,
    "expectedReport": ["[FIELD1]", "[FIELD2]"]
  }
}
```

## Workflow Steps

**STEP 1 - SCAN BACKLOG**
- Read all files from BACKLOG_PATH
- Find first file matching TODO_*.md (sort by ID ascending)
- Extract TASK_ID from filename (e.g., "001" from "TODO_001_Feature_Name.md")
- Extract task description from file content
- Log: "Found task [TASK_ID]: [NAME]"

**STEP 2 - CREATE WORKTREE**
- Generate branch name: feature/[TASK_ID]-[SLUG] (slug = lowercase, hyphens)
- Generate worktree path: WORKTREE_BASE\feature-[TASK_ID]
- Generate ports: 8000 + TASK_ID for backend, 5173 + TASK_ID for frontend
- Call: /new-worktree feature/[TASK_ID]-[SLUG]
- Verify worktree created

**STEP 3 - BUILD TASK CONTEXT JSON**
- Create TASK_CONTEXT_MESSAGE with all fields populated
- Include worktree path, branch, ports, task info, agent context
- Pretty-print for readability

**STEP 4 - SPAWN WORKER AGENT**
- Agent name: feature-worker-[TASK_ID]
- Subagent type: general-purpose
- Run in background: true
- Pass full TASK_CONTEXT_MESSAGE in prompt
- Instruction: "Here is your task context as JSON: [JSON]"
- Instruction: "Follow these steps:
  1. cd to worktree path
  2. git checkout the branch
  3. Read the full task from backlog file
  4. Run: /feature-full-impl
  5. Ensure all tests pass
  6. Create PR and push
  7. SendMessage back with TASK_COMPLETION_MESSAGE JSON"

**STEP 5 - WAIT FOR COMPLETION**
- Listen for SendMessage from feature-worker-[TASK_ID]
- Parse incoming message as JSON
- If messageType == "task:complete" and status == "COMPLETE":
  → Log completion
  → Extract PR URL and test results

**STEP 5A - VALIDATE PR & PROOF OF WORK**

Before marking task DONE, coordinator validates PR contains proof of work:

**FOR UI/FRONTEND CHANGES:**
- PR must include: Screenshots or GIFs showing the UI change
- Screenshots should demonstrate: normal state + edge cases
- Attach to PR description or in commit message
- Validate: Layout responsive, no visual bugs, design matches Café Rider system

**FOR BACKEND/API CHANGES:**
- PR must include: Test logs showing full request/response for cases covered
- Logs should contain:
  - HTTP method + endpoint (POST /v1/bike/search)
  - Full request body (JSON)
  - Full response body (JSON) with status code
  - Test assertions passed (200, schema valid, cache hit, error handling)
- Format: Append to test output or include in PR description
- Validate: All success + error cases covered, graceful degradation

**FOR DOCUMENTATION/RESEARCH:**
- PR must reference the doc output (e.g., backend/docs/offer_sources.md)
- Validate: Doc is complete, comprehensive, well-formatted

**VALIDATION FAILURE:**
- If PR lacks proof of work, request worker to add it
- Do not proceed to STEP 6 until validation passes

If messageType == "task:blocker":
- Log blocker
- Spawn helper agent if needed (e.g., debugger)
- Wait for resolution or escalate

**STEP 6 - MARK TASK DONE**
- Rename backlog file: TODO_[ID]_[NAME].md → DONE_[ID]_[NAME].md
- Log: "Task [TASK_ID] completed. PR: [PR_URL]"
- Record completion in .claude-flow/data/task-history.json

**STEP 7 - LOOP TO NEXT TASK**
- Go back to STEP 1
- Pick next TODO file
- Continue until all TODO files are DONE
- On no more TODO files: log "All tasks complete" and stop

## Communication Protocol

**OUTBOUND (Coordinator → Worker)**
- Use SendMessage with full JSON task context
- Include all required fields
- Pretty-print JSON for readability

**INBOUND (Worker → Coordinator)**
- Worker sends JSON via SendMessage
- Parse as JSON using JSON.parse()
- Validate messageType field
- Extract task ID, status, results, PR URL
- Log to .claude-flow/data/messages.log

**AUDIT TRAIL**
- Log all messages sent/received to .claude-flow/data/messages.log
- Format: [TIMESTAMP] [DIRECTION] [AGENT] [MESSAGE_TYPE] [SUMMARY]
- Example: "2026-07-21T10:30:00Z → feature-worker-001 task:start Task 001: Feature Name"
- Example: "2026-07-21T11:45:00Z ← feature-worker-001 task:complete Task 001 PASSED, PR #37"

## Sub-Agent Policy

Worker agents can spawn sub-agents using ruflo:
- Use mcp__ruflo__agent_spawn for specialized tasks
- Use mcp__ruflo__hooks_route to get agent role suggestions
- Sub-agents send results back via SendMessage
- Parent waits for all sub-agents before completing

Example sub-agent roles:
- feature-worker-[ID]-tester: test_specialist
- feature-worker-[ID]-reviewer: code_reviewer
- feature-worker-[ID]-debugger: debugger

## Error Handling

**If worker agent reports blocker:**
1. Log error to .claude-flow/data/blockers.log
2. Spawn helper agent if needed
3. Wait for resolution
4. If unresolvable, pause and notify user
5. User can resume with manual fix or new instructions

**If worktree creation fails:**
1. Log error
2. Retry up to 2 times
3. If still failing, escalate to user

**If PR creation fails:**
1. Log error with branch name
2. Instruct worker to retry
3. If still failing, mark task as BLOCKED and notify user

## Port Allocation

| Worktree | Backend | Frontend |
|----------|---------|----------|
| Main (biker\) | 8000 | 5173 |
| Feature/1 | 8001 | 5174 |
| Feature/2 | 8002 | 5175 |
| Feature/3 | 8003 | 5176 |

Set env vars in worktree:
```powershell
$env:BACKEND_PORT = 8001
$env:FRONTEND_PORT = 5174
```

## State Tracking

Maintain state in `.claude-flow/data/`:
- `app-runner-state.json`: ports and service status
- `task-history.json`: all tasks (TODO/DONE with timestamps)
- `messages.log`: audit trail of all agent messages
- `blockers.log`: any blockers encountered
- `current-task.json`: task in progress (cleared on completion)
