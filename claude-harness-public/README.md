# Claude Harness

A project-agnostic, modular orchestration system for plan-driven development with Claude Code. Provides reusable prompts, document templates, enforcement scripts, capability modules, and a cross-project pattern library.

## What This Is

When building software with Claude Code, large projects benefit from structured planning: implementation plans with dependency graphs, progressive documentation hierarchies, and automated verification. This repo packages those patterns into a reusable system that works with any tech stack.

**Core idea:** The orchestration prompt tells Claude HOW to execute. Plan files tell Claude WHAT to build. Modules add optional capabilities (data contracts, verification agents). Patterns provide cross-project knowledge (anti-patterns, decision guides).

## Architecture

```
claude-harness/
├── registry.yaml                  # Module registry + routing metadata
├── core/                          # ALWAYS ACTIVE — orchestration backbone
│   ├── module.yaml
│   ├── orchestration-prompt.md    # Master execution guide
│   ├── bootstrap-prompt.md        # One-time project setup (3-stage pipeline)
│   ├── templates/                 # Documentation templates (7 files)
│   ├── scripts/                   # MANIFEST enforcement scripts
│   └── hooks/                     # Claude Code hook examples
├── modules/                       # OPTIONAL — activated by relevance scoring
│   ├── data-contracts/            # ODCS v3.1.0 contract generation
│   │   ├── module.yaml            # Relevance signals + scoring
│   │   ├── prompt.md              # Data contracts prompt
│   │   ├── templates/             # ODCS contract templates (6 files)
│   │   ├── scripts/               # Drift detection hook
│   │   └── ...
│   └── verification/              # Verification audit agent
│       ├── module.yaml
│       ├── prompt.md              # Agent creator prompt
│       ├── templates/             # Agent templates (2 files)
│       └── ...
├── patterns/                      # CROSS-CUTTING — reusable knowledge
│   ├── anti-patterns/             # Recurring failure modes (4 patterns)
│   ├── decision-guides/           # Architectural decision guides (4 guides)
│   └── test-patterns/             # Reusable test strategies (2 patterns)
├── docs/                          # SELF-DOCUMENTING — harness governs itself
│   ├── decisions/                 # Harness ADRs (MADR 4.0)
│   ├── plans/                     # Harness implementation plans
│   ├── test-specs/                # Module validation specs
│   ├── lessons/                   # Operational knowledge
│   └── guides/                    # Module author + pattern contributor guides
├── .claude/skills/                # Claude Code skills (3 skills)
├── orchestration-prompt.md        # Symlink → core/orchestration-prompt.md
├── bootstrap-prompt.md            # Symlink → core/bootstrap-prompt.md
├── verifier-creator.md            # Symlink → modules/verification/prompt.md
└── data-contracts-prompt.md       # Symlink → modules/data-contracts/prompt.md
```

## Quick Start

### 1. Get the orchestration repo

```bash
git submodule add <this-repo-url> claude-harness
# or
git clone <this-repo-url> claude-harness
```

### 2. Run the bootstrap prompt

Open a Claude Code session in your project and paste the contents of `bootstrap-prompt.md`. Claude will:

1. **ANALYZE** — Detect your project's tech stack and structure
2. **ROUTE** — Evaluate which modules and skills are relevant, present routing table for confirmation
3. **EXECUTE** — Generate CLAUDE.md hierarchy, MANIFESTs, plan index, enforcement scripts, and run activated module phases

### 3. Reference from your CLAUDE.md

Add pointers in your root CLAUDE.md's Deep Docs section:

```markdown
### Deep Docs

- Orchestration: `claude-harness/core/orchestration-prompt.md` (on-demand reference)
- Patterns: `claude-harness/patterns/README.md` (on-demand)
- Implementation plans: `docs/implementation-plans/00-index.md`
```

### 4. Start building

Begin a Claude Code session. Claude will read the orchestration prompt, discover the plan index, and execute plans in dependency order.

## Module System

### How Module Routing Works

During bootstrap, each module's relevance is scored against your project:

| Signal Type | Example | How Evaluated |
|-------------|---------|---------------|
| file_signals | `**/*.csv` in `outputs/` | Glob for pattern |
| code_signals | `CREATE TABLE\|CREATE VIEW` | Grep source files |
| tech_signals | `postgresql`, `pandas` | Match project profile |

**Scoring**: Score ≥ threshold → ACTIVATE. 0 < score < threshold → SUGGEST. Score = 0 → SKIP.

### Available Modules

| Module | Purpose | Signals |
|--------|---------|---------|
| data-contracts | ODCS v3.1.0 contract generation + governance | CSV/Parquet outputs, SQL DDL, dashboard tools, pandas |
| verification | Project-specific verification audit agent | Plan index, test directories, test frameworks |

### Creating New Modules

See `docs/guides/harness-module-author-guide.md`.

## Pattern Library

10 battle-tested patterns extracted from downstream projects:

- **4 anti-patterns**: silent-skip, stale-output, config-data-misalignment, silent-substitution
- **4 decision guides**: data-centric-integrity, output-regeneration, progressive-disclosure, data-provenance
- **2 test patterns**: contract-as-specification, ground-truth-comparison

All patterns are project-agnostic with Origin traceability. See `patterns/README.md` for the full index.

### Contributing Patterns

See `docs/guides/harness-pattern-contributor-guide.md`.

## Key Concepts

### Progressive Disclosure (L0/L1/L2)

Documentation is layered to optimize Claude's context window:

- **L0 (root CLAUDE.md):** Always loaded. Project identity, commands, directory tree, conventions. ~100 lines max.
- **L1 (subdirectory CLAUDE.md):** Auto-loaded when working in that directory. Subsystem-specific conventions.
- **L2 (on-demand):** MANIFEST.md files, schema docs, specs. Read explicitly when needed.

### Plan-Driven Development

- Plans live in `{PLANS_DIR}/00-index.md` with status tracking (`planned` → `pending` → `completed`)
- Dependency graph prevents out-of-order execution
- Session recovery: `pending` plans resume automatically on session start
- Each plan has verification criteria that must pass before completion

### Complexity Scoring Rubric

Plans are scored on 5 axes (1–5 each) to determine which Claude model to use:

| Score | Model |
|-------|-------|
| <= 10 | Haiku |
| 11–17 | Sonnet |
| >= 18 | Opus |

### MANIFEST Enforcement

Dual mechanism keeps file indexes current:
- **Real-time hook** (`check-manifest.sh`): Warns during development when a new file is missing from its MANIFEST
- **CI validation** (`validate-manifests.sh`): Catches missing and stale entries in CI pipelines

## Self-Documentation

Claude-harness documents its own evolution using its own templates:

- `docs/decisions/` — Harness ADRs (3 architectural decisions)
- `docs/plans/` — Harness implementation plans (7 plans)
- `docs/test-specs/` — Module validation specs (3 test specs)
- `docs/lessons/` — Operational lessons learned (2 lessons)
- `docs/guides/` — Contributor guides (2 guides)

## Migration

For existing consumers upgrading from the flat structure, see `MIGRATION.md`. Root-level symlinks provide transparent backward compatibility — no changes required in downstream projects.

## Customization

### Configuring Scripts

Both enforcement scripts have a configuration header — update for your project:

```bash
SOURCE_EXTENSIONS="py|ts|tsx|js|jsx|yml|yaml|json|toml|cfg|ini|sh"
SKIP_DIRS="__pycache__|node_modules|.git|dist|build|.venv|vendor|target"
SKIP_FILES="__init__.py|MANIFEST.md|CLAUDE.md"
```

### Project Orchestration Overlay

The overlay (`core/templates/project-orchestration-overlay.md`) is where project-specific additions live:
- Health check commands (actual shell commands for your stack)
- Model assignment table (scored per plan)
- Project-specific verification checklist items
- Integration test scenarios

This keeps the core orchestration prompt clean and updatable independently.
