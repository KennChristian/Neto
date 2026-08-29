---
status: proposed
date: 2026-03-23
---

# ADR-002: Weighted Relevance Routing for Module Activation

## Context and Problem Statement

Bootstrap Phase 8.5 uses a boolean decision tree to determine whether to activate data contracts. This approach doesn't scale to 5+ modules and doesn't handle partial signals gracefully. A project with some but not all signals for a module gets a binary yes/no decision with no middle ground.

How should the bootstrap process determine which optional modules to activate for a given project?

## Decision Drivers

- **Graceful degradation**: Partial signal matches should still surface modules as suggestions
- **Transparency**: Users should understand why a module was activated or skipped
- **Tunability**: Module authors should control sensitivity via weights and thresholds
- **Determinism**: Same project profile should produce same routing decisions

## Considered Options

### Option A: Boolean Decision Tree

Each module defines a decision tree (if X and Y → activate). Current approach for data-contracts.

- **Pro**: Deterministic, simple to implement
- **Con**: Brittle — adding a new signal requires restructuring the tree. No partial matches. Doesn't scale beyond 2-3 modules.

### Option B: Weighted Scoring with Threshold

Modules declare signals with weights in `module.yaml`. Bootstrap evaluates signals against the project, sums weights for matched signals, and compares to a threshold:
- Score ≥ threshold → **ACTIVATE** (include module phases in bootstrap)
- 0 < score < threshold → **SUGGEST** (present to user for manual confirmation)
- Score = 0 → **SKIP** (no relevant signals detected)

- **Pro**: Graceful — partial signals still surface modules via SUGGEST tier. Transparent audit trail ("score: 8/16, threshold: 4 → ACTIVATE"). Module authors tune sensitivity independently.
- **Con**: Threshold calibration required per module. Initial tuning effort.

### Option C: LLM-Judged Relevance

Ask Claude to judge relevance based on the project profile in natural language.

- **Pro**: Maximum flexibility, handles nuanced cases
- **Con**: Non-deterministic — different sessions may produce different decisions. Opaque — no audit trail. Can't be validated by test specs.

## Decision Outcome

**Chosen option: Option B** — Weighted scoring with threshold.

### Signal Types

Modules declare three signal types in `module.yaml`:

1. **`file_signals`**: Glob patterns to match against project files
   - `pattern`: glob pattern (e.g., `**/*.csv`)
   - `locations`: optional directory constraints (e.g., `["outputs/", "data/"]`)
   - `weight`: integer score contribution

2. **`code_signals`**: Regex patterns to grep in source files
   - `pattern`: regex (e.g., `CREATE TABLE|CREATE VIEW`)
   - `case_insensitive`: optional boolean
   - `weight`: integer score contribution

3. **`tech_signals`**: Technology identifiers to match against project profile
   - `tech`: technology name (e.g., `postgresql`, `pandas`)
   - `weight`: integer score contribution

### Routing Algorithm

```
For each module in registry.yaml.modules:
  score = 0
  For each file_signal: glob for pattern in locations → if found, score += weight
  For each code_signal: grep for pattern in project → if found, score += weight
  For each tech_signal: match against project profile → if match, score += weight

  ACTIVATE if score >= module.relevance.threshold
  SUGGEST  if 0 < score < module.relevance.threshold
  SKIP     if score == 0
```

### Routing Table Output

Bootstrap Stage 2 presents a routing table for user confirmation:

```
| Module          | Score | Threshold | Decision | Top Signals          |
|-----------------|-------|-----------|----------|----------------------|
| data-contracts  | 10/16 | 4         | ACTIVATE | CSV+PostgreSQL+pandas|
| verification    | 5/8   | 3         | ACTIVATE | pytest + plans       |
```

### Consequences

**Positive:**
- Partial signals still surface modules via SUGGEST tier — reduces false negatives
- Transparent audit trail enables debugging routing decisions
- Each module tunes independently — no central coordination needed
- Test specs can validate routing against known project profiles (see TS-002)

**Negative:**
- Threshold calibration required per module — mitigated by SUGGEST tier catching borderline cases
- More complex than boolean trees — mitigated by clear algorithm and test coverage
