# Decision Guide: Output Regeneration Enforcement

## The Decision

How should a project enforce that output artifacts are regenerated when their source dependencies change?

## When This Applies

- Projects where output artifacts (reports, exports, dashboards) are generated from source files
- Pipelines where source changes don't automatically trigger output regeneration
- Systems where stale outputs have caused incorrect downstream analysis or decisions
- Projects with multiple contributors who may not know which outputs depend on which sources

## Options

### Option A: Manual Regeneration with Documentation
Document the source→output dependency graph. Rely on developers to regenerate manually after source changes.

- **When to choose**: Small team, few outputs, infrequent source changes
- **Pros**: Simple. No tooling required.
- **Cons**: Error-prone. Scales poorly. New contributors won't know the dependencies.

### Option B: Freshness Check Script (CI or Hook)
Implement a script that compares output mtimes against source mtimes. Run as CI gate, pre-commit hook, or manual check.

- **When to choose**: Medium projects, need enforcement without full build system
- **Pros**: Automated detection. Low implementation effort. Can be CI gate or advisory.
- **Cons**: Timestamp-based (can be fooled by touch). Doesn't handle transitive dependencies well.

### Option C: Build System Integration (Make, Bazel, etc.)
Model source→output dependencies in a build system. Output regeneration is automatic.

- **When to choose**: Large projects, complex dependency graphs, outputs are expensive to regenerate
- **Pros**: Automatic regeneration. Handles transitive dependencies. Incremental rebuilds.
- **Cons**: Higher setup effort. Requires build system adoption. May be overkill for simple pipelines.

## Recommendation

Default to **Option B** — a freshness check script provides 80% of the value with 20% of the effort. Implement as a CI gate that blocks merges when outputs are stale.

Upgrade to **Option C** when: (1) the dependency graph has more than 10 source→output relationships, (2) transitive dependencies exist, or (3) regeneration takes more than a few minutes.

## Origin

Derived from downstream-project ADR-014. Generalized: "output artifact" replaces domain-specific visualization format.
