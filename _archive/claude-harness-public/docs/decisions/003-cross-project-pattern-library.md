---
status: proposed
date: 2026-03-23
---

# ADR-003: Cross-Project Pattern Library

## Context and Problem Statement

The kinyen-equiplot project accumulated 40 bug reports over its development lifecycle. Many bugs recurred across multiple resolution generations, revealing structural anti-patterns that are not project-specific but applicable to any data pipeline, configuration-driven system, or plan-driven development workflow. These learnings are currently trapped in the project's `docs/lessons/` directory and are invisible to future projects.

How should reusable learnings from downstream projects be extracted and made available to future projects?

## Decision Drivers

- **Knowledge reuse**: Future projects should start with battle-tested patterns, not from scratch
- **Prevention over cure**: Anti-patterns and decision guides should prevent bugs, not just document them
- **Institutional memory**: Structural insights should survive across projects and teams
- **Traceability**: Extracted patterns should link back to their origin for context

## Considered Options

### Option A: Keep Lessons Project-Specific, Copy Manually

Leave learnings in each project's `docs/lessons/`. When starting a new project, manually copy relevant lessons.

- **Pro**: Simple, no extraction effort
- **Con**: Knowledge loss — requires someone to remember which project had which lesson. Manual copying is error-prone and incomplete.

### Option B: Extract into Generalized Patterns in Harness

Create a `patterns/` directory in claude-harness with three categories:
- **Anti-patterns**: Recurring failure modes with symptoms, root cause, and prevention rules
- **Decision guides**: Structured guidance for common architectural decisions
- **Test patterns**: Reusable test strategies and methodologies

Each pattern follows a structured template with an `## Origin` section for traceability.

- **Pro**: Future projects inherit patterns automatically via submodule. Upfront extraction effort pays off across all future projects. Origin links enable traceability.
- **Con**: Manual extraction effort. Patterns may over-abstract and lose structural insight — mitigated by including concrete (domain-neutral) examples and Origin links.

### Option C: Auto-Extract via LLM Analysis

Use an LLM to analyze bug reports and automatically extract generalized patterns.

- **Pro**: Low manual effort
- **Con**: Unreliable abstraction — LLM may miss structural insights or over-generalize. No quality gate for domain-term leakage. Not reproducible.

## Decision Outcome

**Chosen option: Option B** — Extract into generalized patterns in the harness.

### Pattern Categories

1. **Anti-patterns** (`patterns/anti-patterns/`): Recurring failure modes. Template has 6 required sections: The Pattern, Symptoms, Root Cause, Prevention Rules, Detection, Origin.

2. **Decision guides** (`patterns/decision-guides/`): Structured guidance for architectural decisions. Template has 5 required sections: The Decision, When This Applies, Options, Recommendation, Origin.

3. **Test patterns** (`patterns/test-patterns/`): Reusable test strategies. Structured with methodology description, when to use, implementation guidance, and origin.

### Extraction Rules

When extracting from a downstream project:
- Replace ALL domain-specific terms with generic equivalents (e.g., "codec" → "configuration mapping", "equiplot" → "output artifact")
- Preserve structural insight (root cause analysis and prevention rules)
- Include `## Origin` section linking back to source project, bug IDs, and ADR IDs
- Quality gate: zero occurrences of project-specific terms in the final pattern

### Initial Patterns

10 patterns extracted from kinyen-equiplot as the founding library:
- 4 anti-patterns (silent-skip, stale-output, config-data-misalignment, silent-substitution)
- 4 decision guides (data-centric-integrity, output-regeneration, progressive-disclosure, data-provenance)
- 2 test patterns (contract-as-specification, ground-truth-comparison)

### Consequences

**Positive:**
- Future projects start with battle-tested patterns — prevents known failure modes from Day 1
- Origin links maintain traceability back to the real-world incidents that motivated each pattern
- Structured templates ensure consistency and completeness

**Negative:**
- Manual extraction effort per pattern — mitigated by contributor guide and extraction happening during bug resolution (see LRN-002)
- Patterns may drift from their origins — mitigated by Origin links enabling periodic validation
