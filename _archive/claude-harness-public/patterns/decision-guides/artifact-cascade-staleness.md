# Artifact Cascade Staleness

## Problem

When a project manages multiple versioned artifacts with generation dependencies (e.g., an API spec generated from a schema, or a UI kit built from a design system), bumping an upstream artifact's version may cause downstream artifacts to become stale. Without a principled detection mechanism, staleness goes unnoticed until runtime failures or manual review discover the inconsistency.

## When to Use

- Your project has directed dependencies between versioned artifacts (artifact A generates artifact B)
- Upstream version bumps should trigger awareness of downstream staleness
- You want advisory warnings without automatic scope expansion of plans

## Cascade Graph Format

Define cascade relationships as a directed graph. Each rule specifies a source artifact, target artifact, detection condition, severity, and message template.

```yaml
cascade_rules:
  - id: C-1
    source: SCHEMA
    target: API
    condition: "source.target != source.latest AND target has no planned impact"
    severity: warning
    message_template: >
      {target.name} {target.latest} was generated from {source.name} {source.latest}.
      {source.name} is bumping to {source.target}.
      Consider regenerating {target.name}.

  - id: C-2
    source: SCHEMA
    target: UIKIT
    condition: "source.target != source.latest AND target has no planned impact"
    severity: warning
    message_template: >
      {target.name} {target.latest} was generated from {source.name} {source.latest}.
      {source.name} is bumping to {source.target}.
      Consider regenerating {target.name}.

  - id: C-3
    source: API
    target: CLIENT_SDK
    condition: "source.target != source.latest AND target has no planned impact"
    severity: info
    message_template: >
      {target.name} was generated from {source.name} {source.latest}.
      Consider regenerating after {source.name} stabilizes.
```

### Rule Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique rule identifier for reference and suppression |
| `source` | prefix | Upstream artifact prefix from the artifact registry |
| `target` | prefix | Downstream artifact prefix that may become stale |
| `condition` | expression | Boolean condition evaluated after resolution completes |
| `severity` | `warning` or `info` | Determines output prominence |
| `message_template` | template | Human-readable message with variable interpolation |

## Severity Levels

### Warning

- **Display:** Prominently shown in session output with `[WARNING]` prefix
- **When to use:** Target artifact is a primary deliverable that users interact with directly
- **Example:** Schema bumps but API spec (used by external consumers) is not regenerated

### Info

- **Display:** Reduced prominence in session output with `[INFO]` prefix
- **When to use:** Target artifact is secondary, derived, or internal-only
- **Example:** API bumps but client SDK (auto-generated, internal-only) is not regenerated

## Advisory vs Enforced Cascades

### Advisory (Recommended)

Cascade detection emits a warning. The plan author decides whether to add target impact to their plan. Single responsibility is preserved: each plan declares its own scope.

**Behavior:**
- Detection runs after resolution completes
- Warnings are collected and displayed in session output
- No automatic modification of impact declarations or plan scope
- Plan author may choose to ignore the warning if the upstream change does not semantically affect the downstream artifact

**Why advisory is the default:**
- Not all upstream changes affect downstream artifacts (e.g., a schema comment change does not invalidate the API spec)
- Automatic scope expansion creates surprise work and harder-to-reason-about plans
- Plan authors have domain knowledge that the cascade detector lacks

### Enforced (Use Sparingly)

Cascade detection automatically adds target impact when the condition fires. Only appropriate when the downstream artifact is mechanically derived and staleness is always a defect.

**When enforced is appropriate:**
- The downstream artifact is a compiled or generated output with no human-authored content
- Every change to the source artifact deterministically invalidates the target
- There is no scenario where ignoring the cascade is correct

**When enforced is NOT appropriate:**
- The downstream artifact contains human-authored content mixed with generated content
- Semantic analysis is needed to determine whether the source change affects the target
- The cost of unnecessary regeneration is high

## Detection Algorithm

```
INPUT: resolved_targets (from resolution loop), cascade_rules

AFTER all artifact targets are computed:
  warnings = []

  FOR EACH rule in cascade_rules:
    source = resolved_targets[rule.source]
    target = resolved_targets[rule.target]

    IF source.target != source.latest:          # source is bumping
      AND target has no planned impact:          # target not explicitly covered
        warning = {
          rule_id: rule.id,
          severity: rule.severity,
          message: interpolate(rule.message_template, source, target)
        }
        warnings.append(warning)

  RETURN warnings
```

## Integration with Drift Detection

Cascade staleness and drift detection are complementary mechanisms that operate at different levels.

| Aspect | Cascade Staleness | Drift Detection |
|--------|------------------|-----------------|
| **Level** | Version-level | Content-level |
| **Question** | Does the artifact need regeneration? | What specifically changed? |
| **Trigger** | Upstream version bump | Source file modification |
| **Scope** | Across artifacts | Within a single artifact |
| **Output** | Advisory warning with suggested action | Detailed diff or change report |

**How they work together:**
1. Cascade detection fires when an upstream artifact bumps version, emitting a warning that a downstream artifact may be stale
2. Drift detection scripts (e.g., source change detectors) can confirm whether the specific changes in the upstream artifact actually affect the downstream artifact
3. Neither mechanism auto-modifies plan scope; both inform the plan author

## Progressive Disclosure

### Tier 0: Compact Summary (Single Line)

```
Cascade: 2 warnings (Schema bump may affect API, UIKit)
```

Use in status bars and compact reports.

### Tier 1: Per-Warning Detail

```
### Cascade warnings
- [WARNING] Schema bumping v2.3.0 -> v3.0.0: API spec api-v1.5.2 was generated
  from Schema v2.3.0. Consider regenerating API spec.
- [WARNING] Schema bumping v2.3.0 -> v3.0.0: UI kit kit-1.0.0 was generated
  from Schema v2.3.0. Consider regenerating UI kit.
```

Default output for orchestration sessions.

### Tier 2: Full Cascade Graph

```
### Cascade graph
SCHEMA -> API:        WARNING (Schema bumping, API not covered)
SCHEMA -> UIKIT:      WARNING (Schema bumping, UIKit not covered)
API    -> CLIENT_SDK:  OK (API not bumping)
```

Shows all source-target relationships including those with no active warnings. Available on demand for debugging and audit.

## Worked Examples

### Example A: Upstream Bump, Downstream Not Covered

Plans: Plan 42 (`SCHEMA:major`)

- SCHEMA target: v3.0.0 (bumping from v2.3.0)
- API: no API:* impact declared
- Cascade C-1 fires: `[WARNING] API spec api-v1.5.2 was generated from Schema v2.3.0. Consider regenerating.`

### Example B: Both Covered

Plans: Plan 42 (`SCHEMA:major`), Plan 43 (`API:minor`)

- SCHEMA target: v3.0.0 (bumping)
- API: API:minor impact declared (explicitly covered)
- Cascade C-1 does NOT fire: target has planned impact

### Example C: No Upstream Bump

Plans: Plan 43 (`API:minor`)

- SCHEMA target: v2.3.0 (no bump)
- Cascade C-1 does NOT fire: source is not bumping

## See Also

- [multi-artifact-version-resolution](multi-artifact-version-resolution.md) -- the resolution algorithm that cascade detection hooks into
- [progressive-disclosure](progressive-disclosure.md) -- general progressive disclosure pattern
