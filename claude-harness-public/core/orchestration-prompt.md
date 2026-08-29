# Project Orchestration Prompt

> **Purpose:** Master execution guide for building a software project by executing implementation plans.
>
> **How to use:** At session start, run the **Plan Discovery** procedure (Section 1) to determine which plans remain. Then execute the next eligible plan(s) using the protocols in this document. Each plan file tells you WHAT to build; this document tells you HOW to execute, verify, and sequence.
>
> **Companion documents:**
> - `core/bootstrap-prompt.md` — One-time setup guide; generates project-specific pieces from templates
> - `core/templates/project-orchestration-overlay.md` — Project-specific additions (health check commands, model assignment table)

---

## Table of Contents

1. [Plan Discovery](#1-plan-discovery)
2. [Dependency Graph & Sequencing](#2-dependency-graph--sequencing)
3. [Model Assignment — Complexity Scoring Rubric](#3-model-assignment--complexity-scoring-rubric)
4. [Execution Protocol](#4-execution-protocol)
5. [Health Check Protocol](#5-health-check-protocol)
6. [Verification Audit Protocol](#6-verification-audit-protocol)
7. [Progressive Disclosure System](#7-progressive-disclosure-system)
8. [MANIFEST.md Indexing System](#8-manifestmd-indexing-system)
9. [ADR Protocol](#9-adr-protocol)
10. [Agent Configuration & Module Routing](#10-agent-configuration--module-routing)

---

## 1. Plan Discovery

At the start of each session, determine what work remains.

### 1.1 Discovery Procedure

1. **Read the plan index:** `{PLANS_DIR}/00-index.md` — the `Status` column is the single source of truth.
2. **Categorize plans** from the index table:
   - `completed` — done, no action needed
   - `pending` — was in progress when the last session ended; **resume this first** (review partial work, fix any incomplete state, then finish)
   - `planned` — not yet started; eligible only when ALL plans in its `Depends On` column are `completed`
3. **Determine next eligible plans:** A `planned` plan is eligible when every plan listed in its `Depends On` column has status `completed`.

### 1.2 Session Recovery

If a `pending` plan exists, it means the previous session was interrupted mid-implementation. Before starting anything new:

1. Read the `pending` plan's file to understand its full scope
2. Check what was already built (git diff, existing files, build state)
3. Run existing tests to identify what works and what's broken
4. Complete the remaining work
5. Update the plan's status to `completed` in `00-index.md`

### 1.3 Session Output

After discovery, state:

```
## Plan Status
- Completed: [list from index]
- Pending (resume): [list, if any]
- Next eligible: [planned plans whose dependencies are all completed]
```

Then proceed per Section 4.

---

## 2. Dependency Graph & Sequencing

### 2.1 Authority

`{PLANS_DIR}/00-index.md` is the single source of truth for the dependency graph, plan list, and status. The `Depends On` column and `Dependency Graph` section there define the full execution order. Do not duplicate the graph here — read it from the index.

### 2.2 Sequencing Rules

1. Never start a plan whose dependencies are not all `completed`.
2. When multiple `planned` plans are eligible, prefer the critical path (longest chain to completion).
3. Within a plan, follow the implementation order specified in that plan's document.
4. When multiple eligible plans are independent, they can be executed in parallel.
5. Run the health check protocol (Section 5) after each plan completes.

---

## 3. Model Assignment — Complexity Scoring Rubric

Cost-optimize by assigning Claude model tiers based on plan complexity. Score each plan on 5 axes (1–5 each):

| Axis | 1 (Low) | 3 (Medium) | 5 (High) |
|------|---------|------------|----------|
| **Concurrency & state** | Single-threaded, no shared state | Some async, localized state | Distributed locks, race conditions, state machines |
| **Algorithmic complexity** | CRUD, simple transforms | Moderate logic, standard algorithms | Math-heavy, novel algorithms |
| **Cross-service orchestration** | Single module | 2–3 modules coordinated | Multi-service pipeline, queues, webhooks |
| **UI interaction complexity** | Static display, forms | Drag-and-drop, modals, multi-step flows | Canvas rendering, real-time collaboration, gesture handling |
| **Novelty / pattern deviation** | Follows existing codebase patterns exactly | Minor extensions to patterns | New patterns, no precedent in codebase |

### Scoring Thresholds

- Total **<= 10** → **Haiku** (boilerplate, scaffolding, CRUD)
- Total **11–17** → **Sonnet** (standard features with some complexity)
- Total **>= 18** → **Opus** (complex reasoning, concurrent state, multi-service orchestration)

### Project-Specific Model Table

Each project creates a plan-to-score table in its **project orchestration overlay** (see `core/templates/project-orchestration-overlay.md`):

```markdown
| Plan | C&S | Algo | Orch | UI | Novel | Total | Model |
|------|-----|------|------|----|-------|-------|-------|
| 01   | 1   | 1    | 2    | 1  | 1     | 6     | Haiku |
```

**Rule of thumb:** Haiku for boilerplate-heavy plans. Sonnet for standard features. Opus for concurrent state, canvas interactions, multi-service orchestration, and math-heavy logic.

---

## 4. Execution Protocol

### 4.1 Per-Plan Execution Steps

For each plan:

1. **Read the plan file:** `{PLANS_DIR}/{NN}-{slug}.md`
2. **Verify preconditions:** All dependency plans show `completed` in `00-index.md`
3. **Set status to `pending`** in `00-index.md` — this marks the plan as in-progress for session recovery
4. **Implement:** Follow the plan's sections in order
5. **Run build steps** — project-specific (migrations, compilation, code generation, etc.)
6. **Run plan-specific tests** — scoped to the module/app this plan touches
7. **Run full regression** — all project tests
8. **Run health check protocol** (Section 5)
9. **Run verification audit** (Section 6) — invoke verification-audit-agent
10. **Update MANIFEST.md** files if new source files were created
11. **Check pattern citations** — if any ADRs were created or updated during this plan, verify the `Pattern-Ref:` field is filled
12. **Set status to `completed`** in `00-index.md` — only after all gates pass

### 4.2 Edge Case Handling

Each plan file documents its own edge cases. Additionally:

- **Build conflicts:** Resolve before proceeding; never skip
- **Circular dependencies:** Check after adding cross-module imports
- **Port conflicts:** Surface as errors, not silent failures
- **Infrastructure drift:** Re-run build steps if services were restarted between sessions

---

## 5. Health Check Protocol

Run after **every plan** to confirm nothing broke.

### Required Categories

Fill in project-specific commands in your project orchestration overlay.

1. **Infrastructure health** — all services/processes running
   - `{PROJECT: e.g., docker compose ps, systemctl status, etc.}`

2. **Build system clean** — no pending migrations, no stale builds
   - `{PROJECT: e.g., manage.py showmigrations, npm run build, cargo check}`

3. **System checks pass** — framework-level validation
   - `{PROJECT: e.g., manage.py check --deploy, next lint, cargo clippy}`

4. **All tests pass** — full test suite
   - `{PROJECT: e.g., manage.py test, npm test, cargo test}`

5. **Cross-boundary checks** — API contracts, type safety
   - `{PROJECT: e.g., curl health endpoint, tsc --noEmit}`

### Failure Handling

If any health check fails after a plan:
1. Do NOT mark the plan as `completed`
2. Diagnose and fix the issue
3. Re-run the full health check suite
4. Only proceed once all checks pass

---

## 6. Verification Audit Protocol

### 6.1 When to Invoke verification-audit-agent

| Trigger | Scope |
|---------|-------|
| After each plan completes | Plan-level audit |
| After all plans in a dependency tier complete | Cross-plan audit |
| Before high-complexity plans (Opus-tier) | Pre-implementation complexity review |
| On any test failure | Regression diagnosis |

### 6.2 Invocation Format

> **Agent setup:** If no verification-audit-agent exists yet, generate one using `verifier-creator.md`. See Section 10 for agent configuration details.

```
## VERIFICATION AUDIT REQUEST
### Plan: [number and title]
### Status: [just completed | mid-implementation | regression check]
### Verification Criteria: [reference to plan doc section]
### Files Created/Modified: [list of files]
### Test Results: [paste test output]
### Known Issues: [any encountered issues]
```

### 6.3 Universal Checklist (Every Plan)

- [ ] Build system succeeds (no errors, no pending operations)
- [ ] All plan-specific tests pass
- [ ] All **prior** plan tests still pass (no regressions)
- [ ] All services/processes healthy
- [ ] No circular dependencies introduced
- [ ] New endpoints/APIs follow the project's access control pattern
- [ ] MANIFEST.md files updated for new source files

Add project-specific checklist items in your project orchestration overlay.

### 6.4 Audit Report Template

```
## VERIFICATION AUDIT REPORT — Plan [##]
### Overall Status: [PASS | PARTIAL | FAIL]

### Criteria Results
| # | Criterion | Status | Notes |
|---|-----------|--------|-------|
| 1 | ... | PASS/FAIL | ... |

### Regression Check
| Plan | Tests | Status |
|------|-------|--------|
| 01 | ... | PASS |

### Files Audited: [count]
### Issues Found: [count]
### Recommendations: [list]
### Approved to Proceed: [YES / NO — with blockers if NO]
```

---

## 7. Progressive Disclosure System

Organize project documentation into three layers to optimize context window usage.

### L0 — Root CLAUDE.md (~100 lines max, always loaded by Claude Code)

- Project identity (1 paragraph)
- Tech stack (bulleted)
- Essential commands (single fenced code block)
- Directory structure (annotated tree with `# see X/CLAUDE.md` pointers)
- Key conventions (project-wide invariants)
- Deep Docs section (named links to L1/L2 resources with `(on-demand)` annotations)
- Process protocols (MANIFEST maintenance, planning protocol)

### L1 — Subdirectory CLAUDE.md (auto-loaded when working in that directory)

- Subsystem-specific conventions only
- Never duplicates L0 content
- Cross-references L2 resources in its subtree

### L2 — On-demand references (read explicitly when needed)

- MANIFEST.md files (file indexes per directory)
- Schema docs, spec docs, reference material
- Referenced from L0/L1 with `(on-demand, not auto-loaded)` annotation

### Design Rules

- L0 contains routing information, not content
- Total L0 content <= 100 lines (respects context window)
- Deep Docs section is the routing table — one line per L2 resource
- Never duplicate information across layers; reference instead

---

## 8. MANIFEST.md Indexing System

Track every source file in a directory-level index for quick navigation.

### Format Standard

```markdown
# {Directory Name} MANIFEST

## {Role Group}  (e.g., Entry Points, Components, Services)

| File | Purpose |
|------|---------|
| `filename.ext` | One-line description |

## Directories

| Directory | CLAUDE.md? | Purpose |
|-----------|-----------|---------|
| `subdir/` | Yes/No | What lives there |
```

### Rules

- Each MANIFEST.md tracks files at depth=1 only (its own directory)
- Deep subdirectories get their own MANIFEST
- Filenames appear in backticks in the first column
- Sections group files by role, not alphabetically
- Root MANIFEST includes a `Directories` table with CLAUDE.md indicator column

### Enforcement (Dual Mechanism)

1. **PostToolUse hook** (`check-manifest.sh`): Fires on every Write/Edit, walks up directory tree to find nearest MANIFEST, warns if the new/edited file is missing
2. **CI script** (`validate-manifests.sh`): Two-pass validation — missing entries (exit 1) + stale entries (warning)

### Maintenance

When creating or deleting a source file, update the nearest ancestor MANIFEST.md to keep file indexes current.

---

## 9. ADR Protocol

### When to Create an ADR

- Any architectural choice that constrains future implementation
- Technology selection, pattern adoption, trade-off resolution
- NOT for implementation details within a plan

### Format

MADR 4.0 (see `core/templates/adr-template.md`). Required sections:

- Context and Problem Statement
- Decision Drivers
- Considered Options
- Decision Outcome
- Consequences (positive, negative, neutral)

### Maintenance

- Sequential numbering: `{NNNN}-{kebab-title}.md`
- Index table in the relevant CLAUDE.md (L0 or L1 depending on scope)
- Frontmatter includes `status` and `date` fields

### Pattern Citation

When creating or updating an ADR, check if any patterns from `claude-harness/patterns/` were consulted or applied during the decision. If so, fill the `Pattern-Ref:` field in the ADR with the relevant pattern slugs (filenames without `.md`). If no patterns apply, set the field to `none`.

Pattern slugs are listed in `claude-harness/patterns/README.md`. Common examples:
- `silent-skip` — pipeline silently produces partial output
- `stale-output` — config changed but artifacts not regenerated
- `progressive-disclosure` — layered docs for LLM context efficiency
- `data-provenance` — verify input file identity

---

## 10. Agent Configuration & Module Routing

### 10.1 Module System

Claude-harness uses a modular architecture (see `registry.yaml`):

- **`core/`** — Always active. Orchestration prompt, bootstrap, templates, scripts, hooks.
- **`modules/`** — Optional capabilities activated by weighted relevance scoring during bootstrap.
- **`patterns/`** — Cross-cutting reusable knowledge (anti-patterns, decision guides, test patterns).

**Module discovery**: Read `registry.yaml` at the harness root. Each module is a self-contained directory with `module.yaml` (manifest), `prompt.md`, and optional templates/scripts/lessons.

**Module activation**: During bootstrap Phase 2, each module's relevance signals are evaluated against the project profile. Modules scoring ≥ threshold are ACTIVATED; those with partial matches are SUGGESTED for user confirmation; those with no matches are SKIPPED.

**Pattern library**: Available to all projects regardless of module routing. Reference from project CLAUDE.md Deep Docs: `claude-harness/patterns/README.md`.

### 10.2 Agent Directory Convention

Agents are stored in standard Claude Code locations:

- `.claude/agents/` — Agent prompt files (YAML frontmatter + markdown body)
- `.claude/agent-memory/` — Per-agent persistent memory directories

**Naming convention:** `{agent-name}.md` in agents, `{agent-name}/` in agent-memory. The agent name uses kebab-case.

### 10.3 Agent Invocation

Three invocation patterns:

1. **Explicit** — User directly requests agent use (e.g., "use the verification-audit-agent to check this")
2. **Automatic** — Orchestration step 9 in Section 4.1 invokes verification-audit-agent after each plan completes
3. **Proactive** — Coding agent recognizes a trigger condition (vague instructions, complex task, post-implementation) and invokes the agent without being asked

### 10.4 Verification Audit Agent

The primary agent for plan-driven development. Operates in 4 phases:

1. **Requirement Analysis** — Parses instructions, identifies ambiguities, formulates clarifying questions
2. **Plan Construction** — Defines target outcomes, verification criteria, milestone decomposition
3. **System Prompt Generation** — Produces comprehensive prompts for autonomous coding agents
4. **Post-Implementation Audit** — Reviews completed work against milestones, generates audit reports

**Setup:** Generate a project-specific verification-audit-agent using `verifier-creator.md`. The creator explores the codebase, interviews the user for domain knowledge, and assembles the agent from `modules/verification/templates/verification-audit-agent.md`.

**Invocation format and audit report template:** See Section 6.

### 10.5 Agent Memory

- Set `memory: project` in YAML frontmatter — Claude Code auto-generates the Persistent Agent Memory boilerplate
- `MEMORY.md` in the agent's memory directory is always loaded into the agent's context (keep under 200 lines)
- Organize memory semantically by topic; create separate files for detailed notes
- Memory directory is project-scoped and version-controlled

### 10.6 Adding Custom Agents

To create additional project-specific agents:

1. Create `.claude/agents/{agent-name}.md` with YAML frontmatter:
   - Required fields: `name`, `description`, `model`, `color`, `memory`
   - `model`: use `inherit` to match the parent session's model, or specify `sonnet`/`opus`/`haiku`
   - `memory`: use `project` for project-scoped persistent memory
2. Create `.claude/agent-memory/{agent-name}/` directory for persistent memory
3. Register in the project orchestration overlay if the agent should be invoked automatically during plan execution
