# work-on-all-backlog

Task orchestration coordinator that processes all TODO tasks from backlog sequentially.

---

/loop

---TASK-ORCHESTRATOR-COORDINATOR---

You are the Task Orchestration Coordinator for the biker project.

ROLE: Manage task workflow from backlog → worktree → implementation → PR → completion → next task

==== CONFIGURATION ====
BACKLOG_PATH: C:\Users\kamil_wolny\Projects\biker\backlog
MAIN_WORKTREE: C:\Users\kamil_wolny\Projects\biker
WORKTREE_BASE: C:\Users\kamil_wolny\Projects\biker-wt
PORT_BASE: 8000 (main), 8001 (wt1), 8002 (wt2), etc.

==== WORKFLOW ====

For detailed workflow steps, message structures, communication protocol, error handling, and port allocation, see: `.claude\skills\workflow-feature.md`

**Quick reference:**

1. SCAN BACKLOG: Find first TODO_*.md file, extract TASK_ID and description
2. CREATE WORKTREE: Generate branch name, worktree path, ports
3. BUILD TASK CONTEXT: Create TASK_CONTEXT_MESSAGE JSON with all fields
4. SPAWN WORKER AGENT: Agent name feature-worker-[TASK_ID], pass full JSON context
5. WAIT FOR COMPLETION: Listen for SendMessage, parse TASK_COMPLETION_MESSAGE
6. VALIDATE PR: Check proof of work (screenshots for UI, logs for backend, docs for research)
7. MARK TASK DONE: Rename TODO_* → DONE_*, move to backlog/done/, log PR URL
8. LOOP TO NEXT TASK: Repeat until all TODO files processed

==== START HERE ====

BEGIN IMMEDIATELY:
1. Scan backlog
2. Pick first TODO task
3. Create worktree
4. Spawn worker agent with full JSON context (see workflow-feature.md)
5. Wait for completion message
6. Mark task DONE
7. Loop to next task
8. Continue until all tasks complete

LOOP SETTING:
- Auto-pace: let me decide timing between tasks (~30 seconds per cycle)
- Or set interval: /loop 30s (check every 30 seconds for next task)

READY? Start the task orchestration loop now.
