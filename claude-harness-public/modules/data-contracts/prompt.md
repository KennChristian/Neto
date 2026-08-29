# Data Contracts Prompt — ODCS v3.1.0 Contract Generation

> **Purpose:** Generate Open Data Contract Standard (ODCS v3.1.0) data contracts for structured data outputs. Works standalone or as Phase 8.5 of the bootstrap prompt.
>
> **Prerequisites:** A project with structured data outputs (CSV, DB tables, API responses, or in-memory configs). Root CLAUDE.md should exist.
>
> **Templates:** References templates in `modules/data-contracts/templates/` (ODCS archetypes, quality catalog, CLAUDE.md template).

---

## Instructions for Claude

Follow these 5 phases in order. Phase 1 determines whether to proceed. If running as Phase 8.5 of bootstrap, skip Phase 1 preamble (project context already gathered) but still run the decision tree.

---

## Phase 1: Relevancy Qualification

Determine whether this project benefits from data contracts. Run the decision tree below.

### Decision Tree

**Q1: Does the project produce structured data artifacts?**

Scan the codebase for evidence:

```
# Persisted files (CSV, Parquet, JSON exports)
glob: outputs/**/*.csv exports/**/*.csv data/out/**/*.csv **/*.parquet

# DB schemas (tables, views, materialized views)
grep: "CREATE TABLE|CREATE VIEW|CREATE MATERIALIZED VIEW" in scripts/ migrations/ sql/

# API responses (REST, GraphQL endpoints)
grep: "app.route|@router|@api_view|func.*Handler|@GetMapping|@PostMapping" in src/ app/

# In-memory configs (dataclasses, typed configs)
grep: "@dataclass|dataclass|TypedDict|interface.*Config|struct.*Config" in src/ lib/ app/
```

- **NO evidence** → STOP. Data contracts are not applicable to this project. Inform the user and exit.
- **YES** → Continue to Q2.

**Q2: Are there downstream consumers?**

Scan for evidence of consumers:

```
# Dashboard connections
grep: "superset|metabase|grafana|tableau|looker|power.bi" (case insensitive) in config files, docs, scripts

# Cross-codebase consumers
grep: "import.*from|require\(|fetch\(|requests.get|http.Get" referencing output paths

# Pipeline downstream
grep: "downstream|consumer|subscriber|webhook|callback" in docs, config
```

- **NO evidence** → SUGGEST contracts as optional documentation. Ask user: "No downstream consumers detected. Data contracts are most valuable when outputs have consumers. Would you like to proceed anyway for documentation purposes?"
  - User says no → STOP.
  - User says yes → Continue in MINIMAL mode.
- **YES** → Continue to Q3.

**Q3: Artifact count determines mode.**

Count distinct output artifacts discovered in Q1.

| Count | Mode | What's generated |
|-------|------|-----------------|
| 1–2 | MINIMAL | Contracts only, no hook |
| 3–9 | STANDARD | Contracts + optional drift hook |
| 10+ | COMPREHENSIVE | Contracts + hook + CI recommendation |

**Present findings to user:**
```
## Data Contract Relevancy Assessment

Structured artifacts found: {count}
- Persisted files: {list}
- DB schemas: {list}
- API responses: {list}
- In-memory configs: {list}

Downstream consumers: {list or "none detected"}

Recommended mode: {MINIMAL|STANDARD|COMPREHENSIVE}
```

Ask the user to confirm before proceeding.

---

## Phase 2: Artifact Discovery

Inventory each output artifact discovered in Phase 1.

### Steps

1. **For each artifact, determine:**
   - **Name**: Human-readable name (e.g., "Equiplot Ready Output")
   - **Archetype**: `csv` | `db-table` | `api-response` | `inmemory-config`
   - **File/location**: Path pattern or endpoint
   - **Schema**: Column names and types (read from code, DDL, or sample data)
   - **Consumers**: Who/what reads this output
   - **Freshness needs**: How often must this be regenerated

2. **For schema extraction**, use these heuristics:
   - CSV: Read a sample file header, or find the write/export code
   - DB table: Read CREATE TABLE DDL or ORM model
   - API response: Read response serializer, schema definition, or OpenAPI spec
   - In-memory config: Read dataclass/struct definition

3. **Present the artifact inventory** to the user:
   ```
   ## Artifact Inventory

   | # | Name | Archetype | Location | Columns/Fields | Consumers |
   |---|------|-----------|----------|---------------|-----------|
   | 1 | ... | csv | ... | ... | ... |
   ```

4. **Ask the user to confirm/correct** the inventory. They may:
   - Add artifacts you missed
   - Remove artifacts that don't need contracts
   - Correct schema details

---

## Phase 3: Contract Scaffolding

Generate ODCS v3.1.0 contract files for each confirmed artifact.

### Steps

1. **Select the template** by archetype:
   - CSV → `modules/data-contracts/templates/odcs-contract-csv.yaml`
   - DB table → `modules/data-contracts/templates/odcs-contract-db-table.yaml`
   - API response → `modules/data-contracts/templates/odcs-contract-api-response.yaml`
   - In-memory config → `modules/data-contracts/templates/odcs-contract-inmemory-config.yaml`

2. **Fill required skeleton** for each contract:
   - `id`: `dc-{kebab-name}-001`
   - `version`: `1.0.0`
   - `status`: `draft`
   - `name`, `domain`, `dataProduct`: From project context
   - `description.purpose`: What this artifact is and why it exists
   - `description.limitations`: Known constraints (from code comments, docs)
   - `description.usage`: How consumers access this
   - `schema.properties`: One entry per column/field from Phase 2
   - `contractCreatedTs`: Current ISO timestamp

3. **Fill optional sections** based on mode:

   **MINIMAL mode**: Required skeleton only.

   **STANDARD mode**: Add:
   - `authoritativeDefinitions`: Links to implementation code, specs, tests
   - `quality`: Select applicable rules from `modules/data-contracts/templates/odcs-quality-rules-catalog.md`
   - `slaProperties`: Freshness and retention if applicable

   **COMPREHENSIVE mode**: Add everything in STANDARD plus:
   - `servers`: Full server declarations
   - `customProperties`: Domain-specific metadata
   - Additional quality rules for cross-artifact consistency

4. **Select quality rules** from the catalog:
   - Read `modules/data-contracts/templates/odcs-quality-rules-catalog.md`
   - For each artifact, pick rules that match its schema and data characteristics
   - Substitute `{col}` placeholders with actual column names
   - Add table-level rules (row count, PK uniqueness) first, then column-level

5. **Write contract files** to `docs/datacontracts/`:
   - Filename: `{kebab-name}.odcs.yaml`
   - Add comment header: `# {Name} — {one-line description}`
   - Add comment: `# See: docs/datacontracts/CLAUDE.md for conventions`

6. **Present generated contracts** to the user for review.

---

## Phase 4: Governance Setup

Set up the contract directory infrastructure and optional enforcement.

### Steps

1. **Generate `docs/datacontracts/CLAUDE.md`:**
   - Use `modules/data-contracts/templates/datacontracts-claude-md.md` as the template
   - Fill `{CONVENTIONS}` with project-specific naming and versioning rules
   - Fill `{VALIDATE_COMMANDS}` — detect if `datacontract-cli` is available:
     - If yes: `datacontract lint` and `datacontract test` commands
     - If no: manual review instructions + suggestion to install
   - Fill `{CONTRACT_INVENTORY}` with table of generated contracts
   - Fill `{REFERENCE_LINKS}` with links to related docs (ADRs, test specs)

2. **Ask about drift hook** (STANDARD and COMPREHENSIVE modes only):

   > "Would you like a PostToolUse hook that warns when output files change without updating their data contract? This is warning-only — it never blocks your work. It catches cases where schema changes slip through without contract updates."
   >
   > - **Yes**: Generate `scripts/check-contract-drift.sh` and update `.claude/settings.json`
   > - **No**: Skip hook setup (contracts still work without it)

3. **If drift hook accepted:**
   - Generate `scripts/check-contract-drift.sh` following the pattern from `modules/data-contracts/scripts/check-contract-drift.sh`
   - Configure `CONTRACTS_DIR`, `OUTPUT_DIRS`, `SCHEMA_DIRS`, `OUTPUT_EXTENSIONS` in the header
   - Make executable (`chmod +x`)
   - Add hook entry to `.claude/settings.json` (or create if it doesn't exist)

4. **For COMPREHENSIVE mode**, additionally recommend:
   - CI pipeline step: `datacontract lint docs/datacontracts/*.odcs.yaml`
   - Pre-commit hook for contract validation
   - Contract review as part of PR checklist

---

## Phase 5: Integration

Wire contracts into the project's documentation and governance structure.

### Steps

1. **Add Deep Docs entry** to root CLAUDE.md:
   ```
   - **Data contracts:** `docs/datacontracts/CLAUDE.md` — ODCS output contracts (on-demand)
   ```

2. **If project orchestration overlay exists**, add to health checks:
   ```
   ### Contract Validation
   datacontract lint docs/datacontracts/*.odcs.yaml  # Schema conformance
   ```

3. **If project orchestration overlay exists**, add to verification checklist:
   ```
   - [ ] Data contracts updated if output schema changed
   ```

4. **Summary to user:**
   ```
   ## Data Contracts Setup Complete

   ### Files Created:
   - docs/datacontracts/CLAUDE.md
   - {list of .odcs.yaml files}
   - {scripts/check-contract-drift.sh if accepted}

   ### Integration Points:
   - Root CLAUDE.md: Deep Docs entry added
   - {Orchestration overlay: health check + verification checklist if exists}
   - {.claude/settings.json: drift hook if accepted}

   ### Next Steps:
   1. Review generated contracts and adjust quality rules
   2. Promote contract status from `draft` to `active` after review
   3. (Optional) Install datacontract-cli: `pip install datacontract-cli`
   4. (Optional) Add contract lint to CI pipeline
   ```
