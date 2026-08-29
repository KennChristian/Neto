# Harness Pattern Contributor Guide

How to extract reusable patterns from downstream projects into the claude-harness pattern library.

## When to Extract

Extract a pattern when:
- A bug has **≥2 resolution generations** (fixed, recurred, fixed again) — the recurrence proves it's a structural issue, not a one-off mistake
- An ADR captures a decision that applies beyond the specific project — the architectural insight is generalizable
- A test methodology proves effective and would benefit other projects — the testing strategy is reusable

## Anti-Pattern Template

6 required sections:

```markdown
# Anti-Pattern: {Name}

## The Pattern
{2-3 sentences describing the failure mode in project-agnostic terms}

## Symptoms
{Observable signs that this anti-pattern is present}

## Root Cause
{Structural reason this happens — not "developer forgot" but "no mechanism existed to..."}

## Prevention Rules
{Actionable rules with specific detection mechanisms}
1. {Rule}: {How to implement it}
2. ...

## Detection
{Grep patterns, code smells, review checklist items that surface this anti-pattern}

## Origin
{Source project, BUG/ADR IDs — for traceability, not as required reading}
```

## Decision Guide Template

5 required sections:

```markdown
# Decision Guide: {Topic}

## The Decision
{What architectural choice does a project face?}

## When This Applies
{Project characteristics that trigger this decision}

## Options
### Option A: {Name}
- **When to choose**: {conditions}
- **Pros**: {advantages}
- **Cons**: {disadvantages}

### Option B: {Name}
...

## Recommendation
{Default choice + conditions for deviation}

## Origin
{Source ADR, project — for traceability}
```

## Abstraction Rules

When extracting from a downstream project, you MUST replace all domain-specific terms:

| Domain Term | Generic Replacement |
|-------------|-------------------|
| Project-specific artifact names | "output artifact" |
| Project-specific encoding mechanisms | "configuration mapping" |
| Project-specific identifiers (RQ1, etc.) | "indicator" |
| Project-specific geographic/entity terms | "entity" |
| Project-specific tool names | Generic category (e.g., "dashboard tool") |
| Project name | "downstream project" |

## Quality Gate

Before merging a pattern, verify:

1. **Zero project-specific terms**: Run `grep -ri "{project-name}\|{domain-term-1}\|{domain-term-2}" patterns/{file}` — must return empty
2. **All required sections present**: Check against the template
3. **Structural insight preserved**: The root cause and prevention rules must be specific enough to be actionable, not so abstract they're useless
4. **Origin section included**: Links back to source for traceability
5. **Concrete examples**: Include at least one domain-neutral example in prevention rules or detection

## Worked Example

### Source: Bug Report BUG-020 from downstream project

> "Pipeline loads 15 of 17 regions. Two regions silently skipped because their names in the config don't match the source data column values."

### Extraction Steps

1. **Identify the structural pattern**: The pipeline iterates over config entries, not source data. Missing config entries cause silent skips.
2. **Generalize**: Replace "regions" → "entities", "config" → "configuration", remove project name
3. **Root cause**: No reconciliation between config coverage and source data coverage
4. **Prevention**: Add a post-processing count assertion
5. **Write using template**: See `patterns/anti-patterns/silent-skip.md`
6. **Verify quality gate**: `grep -ri "region\|{project-name}" patterns/anti-patterns/silent-skip.md` → empty
