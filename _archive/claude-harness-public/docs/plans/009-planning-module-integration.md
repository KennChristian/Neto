# Plan-009: Planning Module Integration into Orchestration Prompt

**Objective:** Document the planning module and plan-to-execution handoff in orchestration-prompt.md.
**Scope:** New Section 4.3, Section 10.1 additions, Section 4.1 step update.
**Key constraint:** Reference `modules/planning/prompt.md` for full protocol; don't duplicate its content.

---

## Depends On

- Plan-008 (Section 8 restructured, so Section 10.1 can reference "Section 8.2")

---

## Steps

### Step 1: Add plan-to-execution awareness in Section 4.1

In the Per-Plan Execution Steps, insert a new preliminary step (step 1a):

```
**Step 1a: Receive planning session output (if applicable)**
If this execution session follows a planning-only session, verify all planned
documents have been written to their declared target paths before proceeding.
Planning sessions produce document content in-conversation — an execution session
must write these to disk first.
```

Update the existing MANIFEST step (currently step 10) to also mention registry:

```
10. **Update MANIFEST.md** files if new source files were created. If module files
    were created or modified, verify registry.yaml consistency (Section 8.2).
```

### Step 2: Add Section 4.3 — Plan-to-Execution Handoff

Insert after Section 4.2:

```
### 4.3 Plan-to-Execution Handoff

Planning sessions (via the planning module, `modules/planning/`) and execution
sessions are distinct operational modes with a clean handoff boundary:

**Planning session** (Plan mode active):
- Produces plans, ADRs, test specs, lessons, and guides as markdown in-conversation
- Write/Edit tools are structurally unavailable — no files are created during planning
- After ExitPlanMode: summarizes all planned documents with target file paths, then stops

**Execution session** (normal mode):
1. Writes planned documents to their target file paths
2. Updates MANIFEST.md and CLAUDE.md as needed
3. Executes implementation plans via Section 4.1
4. Runs verification per Section 6

**Handoff boundary:** Planning specifies; execution implements. A planning session
never modifies source code. An execution session never invents new plans — it
executes what was planned.

See `modules/planning/prompt.md` for the planning module's full protocol, including
allowed output directories and required plan structure.
```

### Step 3: Add planning module to Section 10.1

After the existing module description paragraph ("Module discovery: Read registry.yaml..."), add:

```
**Planning module** (`modules/planning/`): Enhances Claude Code's built-in Plan
mode with project-aware context injection. A PreToolUse hook on `EnterPlanMode`
automatically loads the plan index, ADR manifest, and lessons before any planning
begins. Plans produced in planning sessions are designed for later execution via
this orchestration prompt (see Section 4.3). The module also provides a CLAUDE.md
template snippet for the project's Planning Protocol section.
```

After the "Module activation" paragraph, add:

```
**Module registration:** All modules must be listed in `registry.yaml`. A
PostToolUse hook and CI script enforce this consistency (see Section 8.2).
```

---

## Failure Modes

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Section 4.3 content diverges from planning module prompt.md | Compare Section 4.3 claims against modules/planning/prompt.md | Reference prompt.md rather than restating its rules |
| Planning module description in 10.1 becomes stale when module is updated | modules/planning/module.yaml version change | Keep 10.1 description high-level; point to prompt.md for details |
| Section 4.1 step renumbering breaks references | Grep for "step 10" or specific step references | Use descriptive step names, not just numbers |

## Verifiability

- [ ] Section 4.3 accurately describes the planning/execution boundary
- [ ] Section 4.3 references `modules/planning/prompt.md` (not duplicating content)
- [ ] Section 10.1 mentions planning module with PreToolUse hook description
- [ ] Section 10.1 mentions registry enforcement with Section 8.2 cross-reference
- [ ] Section 4.1 preliminary step mentions planning session document verification
