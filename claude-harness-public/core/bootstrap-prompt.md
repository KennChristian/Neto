# Bootstrap Prompt — Project Setup Guide

> **Purpose:** One-time setup prompt. Paste this into a Claude Code session at the start of a new project to generate all orchestration infrastructure (CLAUDE.md hierarchy, MANIFESTs, plan index, enforcement scripts, module activation).
>
> **Prerequisites:** A code repository exists with at least some initial files (package.json, requirements.txt, Cargo.toml, docker-compose.yml, etc.).
>
> **Templates:** This prompt references templates in `core/templates/`. Module-specific templates are in `modules/{name}/templates/`. Ensure the orchestration repo is accessible.

---

## Instructions for Claude

This bootstrap follows a **3-stage pipeline**:

1. **Stage 1 — ANALYZE** (Phases 1): Detect project profile
2. **Stage 2 — ROUTE** (Phase 2): Evaluate modules and skills against project profile, present routing decisions for user confirmation
3. **Stage 3 — EXECUTE** (Phases 3–9 + activated module phases): Generate project infrastructure

At each phase, show the user what you've discovered or generated and ask them to confirm before proceeding.

---

# Stage 1 — ANALYZE

## Phase 1: Project Analysis

Gather information about the project by reading existing files and scanning the directory structure.

### Steps

1. **Detect project files:** Read files that reveal tech stack and structure:
   - `package.json`, `tsconfig.json` (Node/TypeScript)
   - `requirements.txt`, `pyproject.toml`, `setup.py`, `setup.cfg` (Python)
   - `Cargo.toml` (Rust)
   - `go.mod` (Go)
   - `docker-compose.yml`, `Dockerfile` (Containerization)
   - `Makefile`, `justfile` (Build automation)
   - `.github/workflows/` (CI/CD)

2. **Scan directory structure:** List directories at depth 2 to understand the project layout.

3. **Identify key characteristics:**
   - Programming language(s) and framework(s)
   - Build system and package manager
   - Test framework and test command
   - Database (if any)
   - Infrastructure (Docker, cloud services, etc.)
   - Existing documentation patterns

4. **Present discoveries to user:**
   ```
   ## Project Profile
   - Name: {detected or ask}
   - Description: {detected or ask}
   - Language(s): {detected}
   - Framework(s): {detected}
   - Build system: {detected}
   - Test command: {detected}
   - Database: {detected or none}
   - Infrastructure: {detected}
   ```

5. **Ask the user to confirm/correct** the profile and provide:
   - Key project conventions (data scoping patterns, access control, naming conventions)
   - Plans directory location (default: `docs/implementation-plans/`)
   - Decisions directory location (default: `docs/decisions/`)

---

# Stage 2 — ROUTE

## Phase 2: Module & Skill Routing

Using the project profile from Phase 1, evaluate which optional modules and skills to activate.

### Steps

1. **Read the registry:** Read `claude-harness/registry.yaml` to discover available modules and skills.

   > **Fallback:** If `registry.yaml` does not exist or cannot be parsed, skip Stage 2 entirely and proceed to Stage 3 with core phases only. This provides backward compatibility with pre-modular harness versions.

2. **Evaluate each module** using weighted relevance scoring:

   For each module listed in `registry.yaml.modules`:
   1. Read the module's `module.yaml` file
   2. Evaluate each signal type against the project:

      **file_signals**: For each signal, use glob to check if matching files exist in the project (optionally restricted to declared `locations`). If found → add `weight` to score.

      **code_signals**: For each signal, use grep to search for the pattern in project source files. If found → add `weight` to score.

      **tech_signals**: For each signal, check if the `tech` appears in the project profile from Phase 1. If match → add `weight` to score.

   3. Determine decision:
      - Score **≥ threshold** → **ACTIVATE** (include module phases in Stage 3)
      - **0 < score < threshold** → **SUGGEST** (present to user for manual confirmation)
      - Score **= 0** → **SKIP** (no relevant signals detected)

3. **Evaluate skills** from `registry.yaml.skills`:

   For each skill, check if any of its `tech_signals` match the project profile. If ≥1 match → SUGGEST the skill. Skills are always suggestions (never auto-activated).

4. **Present the routing table** to the user:

   ```
   ## Module Routing

   | Module          | Score  | Threshold | Decision | Top Signals               |
   |-----------------|--------|-----------|----------|---------------------------|
   | data-contracts  | {n}/16 | 4         | {decision} | {matched signals}       |
   | verification    | {n}/8  | 3         | {decision} | {matched signals}       |
   | docs-retrieval  | {n}/15 | 6         | {decision} | {matched signals}       |

   ## Skill Suggestions

   | Skill               | Matched Signals     | Status   |
   |---------------------|---------------------|----------|
   | frontend-hook       | {signals or "none"} | {SUGGEST/SKIP} |
   | zod-schema          | {signals or "none"} | {SUGGEST/SKIP} |
   | web-design-guidelines | {signals or "none"} | {SUGGEST/SKIP} |
   ```

5. **Ask the user to confirm:**
   - "Proceed with the above routing? You can override any decision (e.g., activate a SUGGEST module, skip an ACTIVATE module)."
   - Apply any user overrides

### Edge Cases

- **Module YAML parse error**: Skip that module with a warning. Do not abort the entire routing.
- **All modules score 0**: Proceed with core-only bootstrap (Phases 3-9). This is valid for simple projects.
- **Registry missing**: Fall back to legacy bootstrap (Phases 1-8 without module routing).

---

# Stage 3 — EXECUTE

## Phase 3: Generate CLAUDE.md Hierarchy

Using `core/templates/root-claude-md.md`, generate the project's documentation hierarchy.

### Steps

1. **Generate root CLAUDE.md:**
   - Fill `{PROJECT_NAME}` and `{PROJECT_DESCRIPTION}` from Phase 1 profile
   - Fill `{TECH_STACK}` as a bulleted list from detected technologies
   - Fill `{COMMANDS}` with essential dev commands (start, test, build, lint)
   - Fill `{DIRECTORY_STRUCTURE}` as an annotated tree at depth 2, with `# see X/CLAUDE.md` pointers for major subdirectories
   - Fill `{KEY_CONVENTIONS}` from user-provided conventions
   - Fill `{DEEP_DOCS}` with initial pointers (orchestration prompt, plan index, pattern library)
   - Fill `{DECISIONS_DIR}` with the decisions directory path

2. **Generate L1 CLAUDE.md files** for each major subdirectory:
   - Use `core/templates/subdirectory-claude-md.md`
   - Fill `{SUBSYSTEM_NAME}` with the directory's role
   - Fill `{SUBSYSTEM_CONVENTIONS}` with subsystem-specific conventions
   - Fill `{L2_POINTERS}` with references to any schema docs, specs, or other reference material in the subtree
   - Only create L1 files for directories that have distinct conventions

3. **Present generated files** to the user for review.

---

## Phase 4: Generate MANIFEST.md Files

Using `core/templates/manifest-md.md`, create file indexes.

### Steps

1. **Generate root MANIFEST.md:**
   - List all top-level directories with their purpose
   - Include the `Directories` table with CLAUDE.md indicator

2. **Generate per-subdirectory MANIFESTs** by scanning existing files:
   - Group files by role (entry points, components, services, utilities, config, tests)
   - Write one-line descriptions based on file contents
   - Skip generated/vendored directories (`node_modules`, `dist`, `build`, `__pycache__`, `.venv`, `vendor`)

3. **Present generated files** to the user for review.

---

## Phase 5: Generate Plan Index

Using `core/templates/plan-index.md`, create the implementation plan infrastructure.

### Steps

1. **Create the plans directory** at the configured location (default: `docs/implementation-plans/`).

2. **Generate `00-index.md`:**
   - Fill `{PROJECT_NAME}`
   - Start with an empty plans table

3. **Help the user define initial plans:**
   - Ask: "What are the major features or milestones for this project?"
   - For each feature, suggest a plan with:
     - Sequential number and kebab-case slug
     - Brief scope description
     - Dependencies on other plans
   - Generate an ASCII dependency graph

4. **Generate individual plan stubs** using `core/templates/plan-document.md`:
   - Fill in objective, dependencies, and scope boundary
   - Leave implementation sections as TODO placeholders
   - Create one file per plan: `{NN}-{slug}.md`

5. **Present the full plan structure** to the user for review.

---

## Phase 6: Score Plans for Model Assignment

Using the complexity scoring rubric from the orchestration prompt.

### Steps

1. **Walk through each plan** with the user.

2. **For each plan, score the 5 axes** (1–5):
   - Concurrency & state
   - Algorithmic complexity
   - Cross-service orchestration
   - UI interaction complexity
   - Novelty / pattern deviation

3. **Calculate totals** and assign models:
   - <= 10 → Haiku
   - 11–17 → Sonnet
   - >= 18 → Opus

4. **Generate the model assignment table** for the project orchestration overlay.

---

## Phase 7: Generate Health Check Commands

Map the generic health check categories to project-specific commands.

### Steps

1. **Infrastructure health:** Detect the infrastructure tool:
   - Docker Compose → `docker compose ps`
   - Systemd → `systemctl status {services}`
   - Bare process → `pgrep / lsof`
   - Kubernetes → `kubectl get pods`

2. **Build system clean:** Detect the build system:
   - Python/Django → `python manage.py showmigrations`, `python manage.py check`
   - Node/npm → `npm run build`, `tsc --noEmit`
   - Rust/Cargo → `cargo check`, `cargo clippy`
   - Go → `go build ./...`, `go vet ./...`

3. **Test runner:** Detect the test framework:
   - Python → `pytest` or `python manage.py test`
   - Node → `npm test` or `npx vitest`
   - Rust → `cargo test`
   - Go → `go test ./...`

4. **Cross-boundary checks:** Detect integration points:
   - Frontend + backend → `curl health endpoint`, CORS check
   - Microservices → health endpoints per service
   - Monolith → framework system check

5. **Generate the health check section** for the project orchestration overlay.

---

## Phase 8: Set Up Enforcement

Generate MANIFEST enforcement scripts and Claude Code hooks.

### Steps

1. **Determine source file extensions** for this project:
   - Python: `py`
   - TypeScript/JavaScript: `ts|tsx|js|jsx`
   - Rust: `rs`
   - Go: `go`
   - Include config: `yml|yaml|json|toml|sh`

2. **Determine skip patterns:**
   - Standard: `__pycache__|node_modules|.git|dist|build`
   - Project-specific: `migrations|.venv|vendor|target` (as applicable)

3. **Generate `scripts/check-manifest.sh`:**
   - Copy from `core/scripts/check-manifest.sh`, update `SOURCE_EXTENSIONS` and `SKIP_DIRS` header
   - Make executable (`chmod +x`)

4. **Generate `scripts/validate-manifests.sh`:**
   - Copy from `core/scripts/validate-manifests.sh`, update `SOURCE_EXTENSIONS` and `SKIP_DIRS` header
   - Make executable (`chmod +x`)

5. **Generate `.claude/settings.json`:**
   - Start from `core/hooks/settings.json.example` as the base
   - Adjust the script path if scripts live in a different location

---

## Phase 9: Generate Project Orchestration Overlay

Using `core/templates/project-orchestration-overlay.md`, create the project-specific companion.

### Steps

1. **Fill health check commands** from Phase 7 output.
2. **Fill model assignment table** from Phase 6 output.
3. **Add project-specific verification checklist items** based on:
   - Data scoping patterns (e.g., org-scoped queries)
   - Access control patterns (e.g., role-based permissions)
   - Integration points (e.g., CORS, API contracts)
4. **Add integration test scenarios** (if the user has cross-plan test ideas).
5. **Wire pattern library** into Deep Docs:
   ```
   - **Patterns:** `claude-harness/patterns/README.md` — Anti-patterns, decision guides, test patterns (on-demand)
   ```
6. **Save to `docs/project-orchestration-overlay.md`** (or user's preferred location).

---

## Activated Module Phases

Execute each ACTIVATED module's phase in `bootstrap.phase_order` order. Module phases run after Phase 9.

### For each activated module:

1. Read the module's `prompt.md`
2. Execute the module's phases as described in that prompt
3. Merge the module's hook fragment (if any) into `.claude/settings.json`
4. Add relevant Deep Docs entries to root CLAUDE.md

### Module Phase Order Reference

| Order | Module | Phase Name |
|-------|--------|------------|
| 10.5 | data-contracts | Data Contracts — runs relevancy qualification, artifact discovery, contract scaffolding, governance setup, integration |
| 11 | verification | Verification Agent — runs codebase exploration, interview, scenario generation, agent assembly, validation |
| 11 | docs-retrieval | Multi-Axis Docs Retrieval — seeds baseline stage/depth AVRs, copies scripts, appends retrieval protocol to CLAUDE.md, creates `docs/RETRIEVAL.md`, registers pre-commit hand-edit hook, STOPS before backfill (LL-068). Activates when markdown corpus ≥100 files (score ≥6/15). |

> **Note:** SUGGESTED modules that the user confirmed in Phase 2 are treated as ACTIVATED for execution purposes.

---

## Completion

After all phases complete, summarize what was created:

```
## Bootstrap Complete

### Core Infrastructure:
- CLAUDE.md (root)
- {list of L1 CLAUDE.md files}
- {list of MANIFEST.md files}
- {PLANS_DIR}/00-index.md
- {PLANS_DIR}/{list of plan stubs}
- {DECISIONS_DIR}/0001-use-madr.md
- docs/project-orchestration-overlay.md
- scripts/check-manifest.sh
- scripts/validate-manifests.sh
- .claude/settings.json

### Module Routing Results:
{routing table from Phase 2}

### Activated Module Files:
{for each activated module, list created files}

### Next Steps:
1. Review all generated files and make adjustments
2. Reference the orchestration prompt from your CLAUDE.md Deep Docs section
3. Flesh out plan documents with detailed implementation instructions
4. Start executing plans using the orchestration prompt
```

### Optional: Configure Verification Agent

If the verification module was activated, a verification-audit-agent was generated during bootstrap. If it was SUGGESTED but skipped, you can generate one later by running `modules/verification/prompt.md` in a separate Claude Code session. See `core/orchestration-prompt.md` Section 10 for details.
