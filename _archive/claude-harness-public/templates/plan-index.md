# {PROJECT_NAME} — Implementation Plans

## Overview

This directory contains the implementation plan documents for building {PROJECT_NAME}. Each plan follows separation of concerns and single responsibility principles, with clear dependency chains and verifiable test criteria.

## Plan Status Key

| Status | Meaning | When to set |
|--------|---------|-------------|
| `completed` | Fully implemented and verified | After execution finishes and all tests pass |
| `pending` | Currently being implemented | At the start of execution, before writing any code |
| `planned` | Not yet started | Default for new plans |

**Workflow:** `planned` → `pending` → `completed`

> **Session recovery:** On interruption (token limit, crash, etc.), read this table at the start of the next session. Resume any `pending` plan — review what was done, fix any partial state, then complete it. Proceed to the next eligible `planned` plan.

## Plans

| # | Plan | Status | Scope | Depends On |
|---|------|--------|-------|------------|
| [01](./01-{slug}.md) | {Plan Title} | `planned` | {Brief scope description} | — |

## Dependency Graph

```
{ASCII_DEPENDENCY_GRAPH}
```

## Parallel Execution Opportunities

These plans can be worked on simultaneously:
- **Plans {X} + {Y}** (after {Z}): {Reason they are independent}

## Adding New Plans

To add a new plan:

1. Create `{PLANS_DIR}/{NN}-{slug}.md` following existing plan format
2. Add a row to the **Plans** table above with status `planned`
3. Add dependency edges to the **Dependency Graph**
4. Score the plan using the complexity rubric and update the model assignment table in the project orchestration overlay
5. Add a corresponding ADR in `{DECISIONS_DIR}/` if the plan introduces architectural choices
