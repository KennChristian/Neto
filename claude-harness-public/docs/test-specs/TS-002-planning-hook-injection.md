# TS-002: Planning Hook Injection Behavior

**Objective:** Verify the planning module's PreToolUse hook correctly injects context on EnterPlanMode.
**Scope:** PreToolUse hook behavior for EnterPlanMode event.
**Method:** Scenario-based testing with pre/post conditions.

---

## Hook Under Test

- **Event:** PreToolUse
- **Matcher:** EnterPlanMode
- **Type:** prompt
- **Source:** `modules/planning/hooks/settings-fragment.json`

## Preconditions

| Condition | Required State |
|-----------|---------------|
| settings.json | Contains PreToolUse hook on EnterPlanMode with prompt type |
| Plan index | `{PLANS_DIR}/00-index.md` exists and is readable |
| ADR manifest | `{DECISIONS_DIR}/000-adr-manifest.md` exists and is readable |
| Lessons | `{LESSONS_DIR}/CLAUDE.md` exists and is readable |

---

## Scenarios

### Scenario 1: Hook fires on EnterPlanMode (happy path)
**Given:** All precondition files exist
**When:** User presses Shift+Tab to enter Plan mode (triggers EnterPlanMode)
**Then:**
- Hook injects prompt containing planning constraints
- Claude reads plan index, ADR manifest, and lessons before planning
- Planning output follows separation of concerns (plans, ADRs, test specs, lessons)
- Each plan leads with 3-line summary

**Verification:**
- [ ] References to existing plans from 00-index.md
- [ ] References to existing ADRs from 000-adr-manifest.md
- [ ] Awareness of known pitfalls from lessons CLAUDE.md
- [ ] 3-line summary format on each plan

### Scenario 2: Missing precondition files
**Given:** Plan index does not exist (new project, pre-bootstrap)
**When:** EnterPlanMode fires
**Then:**
- Hook still fires (prompt type hooks don't depend on file existence)
- Claude attempts to read files, gets "file not found"
- Claude should note missing infrastructure and proceed with planning
- Planning output should recommend creating the missing files

**Verification:**
- [ ] Hook does not crash or block on missing files
- [ ] Claude gracefully handles missing context files

### Scenario 3: Plan mode via CLI flag
**Given:** All precondition files exist
**When:** `claude --permission-mode plan` starts a session
**Then:** Same behavior as Scenario 1 — hook fires regardless of entry method

### Scenario 4: Post-plan handoff
**Given:** Planning session produced 3 documents (1 plan, 1 ADR, 1 test spec)
**When:** User approves ExitPlanMode
**Then:**
- Claude summarizes all planned documents with target file paths
- Claude stops — does not proceed to implementation
- No files were written during the planning session

**Verification:**
- [ ] Summary lists all 3 documents with paths
- [ ] No Write/Edit tool calls in session transcript
- [ ] Session ends after summary

---

## Edge Cases

| Edge Case | Expected Behavior |
|-----------|-------------------|
| EnterPlanMode called when already in plan mode | Hook fires again (idempotent — re-injecting context is harmless) |
| Multiple planning sessions in sequence | Each session independently loads latest context from index files |
| Plan index updated between sessions | Second session sees updated index (no caching) |
| Hook prompt exceeds reasonable token budget | Monitor prompt length — current prompt is ~100 words, well within limits |
