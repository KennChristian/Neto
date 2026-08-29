---
status: proposed
date: 2026-03-23
---

# ADR-001: Modular Architecture for Claude Harness

## Context and Problem Statement

Claude-harness has grown to 31 files in a flat directory structure. Adding the data-contracts capability required editing `bootstrap-prompt.md` to insert Phase 8.5 as a hardcoded conditional block. Each new capability module requires editing the same core files. There is no concept of self-contained capability modules, no self-documentation, and no way for the harness to govern its own evolution using its own templates.

How should claude-harness organize its capabilities so that new modules can be added without editing existing orchestration files?

## Decision Drivers

- **Scalability**: New modules should not require editing `bootstrap-prompt.md` or `orchestration-prompt.md`
- **Discoverability**: It should be obvious what capabilities the harness provides
- **Separation of concerns**: Each capability should be self-contained with its own templates, scripts, and lessons
- **Self-documentation**: The harness should govern itself using its own templates (ADRs, plans, lessons)
- **Submodule ergonomics**: Downstream projects inherit all governance docs automatically via `git submodule add`

## Considered Options

### Option A: Status Quo — Flat Structure with Conditional Phases

Keep the current flat layout. Add new capabilities by inserting conditional phases into `bootstrap-prompt.md`.

- **Pro**: Simple, no restructuring needed
- **Con**: Every new capability edits the same file. No module isolation. Phase numbering becomes fragile (8.5, 8.6, ...). No discoverability — must read bootstrap to know what exists.

### Option B: Module Directories with Manifests + Self-Documenting `docs/`

Restructure into three tiers:
- `core/` — always-active orchestration backbone (orchestration prompt, bootstrap, templates, scripts, hooks)
- `modules/` — optional, self-describing capability packages (data-contracts, verification, etc.)
- `patterns/` — cross-cutting reusable knowledge library (anti-patterns, decision guides, test patterns)

Plus a `docs/` tree where the harness documents its own evolution using its own templates.

- **Pro**: Each module is self-contained (module.yaml + prompt + templates + scripts + lessons). New capability = new directory. `registry.yaml` as single entry point. Future projects inherit all governance docs.
- **Con**: More directories (mitigated by `registry.yaml` as discovery mechanism)

### Option C: Plugin System with Dynamic Loading

Build a plugin system that dynamically discovers and loads capability modules at runtime.

- **Pro**: Maximum extensibility
- **Con**: Over-engineered for a markdown/prompt repository. No runtime exists — Claude reads files, it doesn't execute plugin loaders. Complexity without benefit.

## Decision Outcome

**Chosen option: Option B** — Module directories with manifests + self-documenting `docs/`.

Three-tier structure:
1. **`core/`** (always active): Orchestration prompt, bootstrap prompt, documentation templates, enforcement scripts, hook examples
2. **`modules/`** (optional, self-describing): Each module has `module.yaml` manifest, prompt, templates, scripts, lessons. Activated by relevance scoring (see ADR-002).
3. **`patterns/`** (cross-cutting): Reusable anti-patterns, decision guides, test patterns extracted from downstream projects (see ADR-003).
4. **`docs/`** (self-governance): Harness-scoped ADRs, plans, test specs, lessons, guides — using its own templates.

### Consequences

**Positive:**
- Each capability is fully self-contained — adding a new module never touches existing files
- `registry.yaml` serves as a single discovery point for all capabilities
- Downstream projects inherit governance docs (ADRs, lessons, patterns) automatically via submodule
- The harness practices what it preaches — self-documenting using its own templates

**Negative:**
- More directories than the flat structure (mitigated by `registry.yaml` as the entry point)
- Migration effort for existing consumers (mitigated by symlinks for backward compatibility, see Plan-006)

**Risk:**
- Self-documenting `docs/` may conflict with downstream project's `docs/` — mitigated by harness-scoped numbering (ADR-001 vs project's ADR-035+) and the submodule path prefix (`claude-harness/docs/`)
