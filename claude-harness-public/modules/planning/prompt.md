# Planning Mode Context Injection

> **Purpose:** Provide project-aware context when Claude Code enters Plan mode.
> Injected automatically via a `PreToolUse` hook on `EnterPlanMode`.
>
> **How it works:** The hook fires a `prompt`-type injection that instructs Claude
> to load prior plans, ADRs, and lessons before producing a plan. The CLAUDE.md
> planning protocol section provides the always-active lightweight guidance.

---

## Planning-Only Session Constraints

This is a planning-only session. Plan mode structurally removes Write/Edit tools —
all plan content is produced **in the conversation**, not as files on disk.
Files are written only after ExitPlanMode, during execution via the orchestration prompt.

### Allowed plan outputs (markdown only, written post-plan)

- `{PLANS_DIR}/**` — Implementation plans
- `{DECISIONS_DIR}/**` — Architectural Decision Records (MADR 4.0)
- `{LESSONS_DIR}/**` — Lessons learned and bug resolutions
- `docs/test-specs/**` — Model-based testing specifications
- `docs/guides/**` — Persona-relevant guides (end user, reviewer, admin, manager)
- Relevant `MANIFEST.md` updates
- Relevant `CLAUDE.md` updates

---

## Pre-Planning Discovery

Before producing any plan, read these files to understand prior work:

1. `{PLANS_DIR}/00-index.md` — Existing plans, dependencies, and status
2. `{DECISIONS_DIR}/000-adr-manifest.md` — Prior architectural decisions
3. `{LESSONS_DIR}/CLAUDE.md` — Known pitfalls and prevention rules

---

## Planning Methodology

For each planning objective, apply separation of concerns:

### Partitioning

- Partition into multiple implementation plans when a task spans distinct subsystems
- Keep ADRs atomic — one decision per file; split if multiple decisions emerge
- Keep test specs atomic — one scenario per file
- Document bug resolutions as separate lessons learned

### Required plan content

For each plan produced, include:

1. **3-line summary** — Objective, scope, key constraint (for progressive disclosure — other plans reference this without re-reading the full plan)
2. **Detailed steps** — Reference exact file paths and function names
3. **Verifiability mechanisms** — Tests, audits, and acceptance criteria (specified, not executed)
4. **Failure modes and edge cases** — What can go wrong and how to detect it
5. **Observability** — Logging, metrics, or alerts that should be added
6. **Persona-relevant guide updates** — Which guides in `docs/guides/` need updating and for which audience

### Testing specifications

- Use model-based testing where applicable
- Place specs in `docs/test-specs/` with prefix `TS-{NNN}-`
- Specify state machines, property invariants, or scenario tables — do not write test code

### ADR protocol

- Use MADR 4.0 format from `{DECISIONS_DIR}/000-adr-manifest.md`
- Required sections: Context, Decision Drivers, Considered Options, Decision Outcome, Consequences
- File naming: next sequential number in `{DECISIONS_DIR}/`

---

## Post-Plan Protocol

After ExitPlanMode approval:

1. Summarize all planned documents with their target file paths
2. **STOP** — Do not proceed to implementation
3. Plans are designed for later execution via the orchestration prompt
