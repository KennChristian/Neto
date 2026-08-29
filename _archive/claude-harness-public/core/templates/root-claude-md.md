# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## {PROJECT_NAME}

{PROJECT_DESCRIPTION}

### Tech Stack

{TECH_STACK}

### Commands

```bash
{COMMANDS}
```

### Directory Structure

```
{DIRECTORY_STRUCTURE}
```

### Key Conventions

{KEY_CONVENTIONS}

### Deep Docs

{DEEP_DOCS}

### MANIFEST.md Maintenance

When creating or deleting a source file, update the nearest ancestor `MANIFEST.md` to keep file indexes current. A PostToolUse hook on Write|Edit will remind you if a new file is missing from its MANIFEST. Run `./scripts/validate-manifests.sh` to check all MANIFESTs.

### Planning Protocol

When in Plan mode, produce plans designed for later execution via the orchestration prompt.
Plans should specify verifiability mechanisms — never execute them.

Structure plans with progressive disclosure:
- Lead with a 3-line summary (objective, scope, key constraint)
- Then detailed steps referencing exact file paths
- End with failure modes, edge cases, and observability concerns

Partition work by separation of concerns:
- Implementation steps → `{PLANS_DIR}/`
- Architectural decisions → `{DECISIONS_DIR}/` (MADR 4.0, atomic — split if warranted)
- Lessons learned / bug resolutions → `{LESSONS_DIR}/`
- Test specifications → `docs/test-specs/` (model-based testing, atomic)
- Persona-relevant guides → `docs/guides/`

For architectural decisions:
1. Create ADR in `{DECISIONS_DIR}/` using next sequential number
2. Follow MADR 4.0 template from `{DECISIONS_DIR}/000-adr-manifest.md`
3. Required sections: Context, Decision Drivers, Considered Options, Decision Outcome, Consequences
4. Update the ADR index table in the relevant CLAUDE.md

After exiting Plan mode: summarize planned documents, then STOP.
Do NOT proceed to implementation.
