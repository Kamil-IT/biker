# Manual Tester Templates

## Traceability

```markdown
## Requirement traceability — <TASK_ID>

| # | Requirement (from task) | Implemented in | Status | Notes |
|---|---|---|---|---|
| R1 | Search box grows to multiple lines | frontend/src/components/SearchInput.tsx:42 | Implemented | |
| R2 | Enter submits, Shift+Enter adds a line | — | Missing | no key handler |
| X1 | (not requested) placeholder text changed | SearchInput.tsx:57 | Extra | confirm with user |
```

## Test case

```markdown
### TC-<TASK>-<NN> — <title>
- **Requirement:** R1
- **Priority:** High | Medium | Low
- **Preconditions:** backend + frontend running; <data state>
- **Test data:** <inputs>
- **Steps:**
  1. Open http://localhost:5173
  2. ...
- **Expected result:** <observable outcome>
```

## Report

```markdown
## Manual test report — <TASK_ID> · round <R>

**<N> passed · <M> failed · <K> blocked**

| Case | Result | Actual vs expected | Severity | Evidence | Suspected cause |
|---|---|---|---|---|---|
| TC-006-02 | Fail | Shift+Enter submits the search instead of adding a line | High | scratchpad/tc-006-02.png | SearchInput.tsx:61 |
| TC-006-05 | Blocked | Backend returned 500 on /v1/bike/search | — | console log | backend not migrated |

**Missing requirements:** R2
**Needs a decision from you:** X1
**Next:** fix TC-006-02, re-run failed + regression set
```
