# Dual-Block Frontmatter Schema

Reference schema for every authored artifact under `docs/` in projects using
the `docs-retrieval` module. Derived from ADR-142 (state/signature
separation) and ADR-141 (multi-axis retrieval).

## Block 1 — State (orchestration-managed)

Fields written by orchestration or by the author as the artifact moves
through its lifecycle. Exact enumeration, single writer per field.

```yaml
---
id: <KIND>-<NUMBER>          # e.g., PLAN-214, ADR-141, TS-123, LL-065, AVR-001
kind: <plan|adr|ddr|test-spec|lesson|axis-value-record>
status: <enum per kind>      # plan: planned|pending|completed|deferred|archived
                             # adr:  proposed|accepted|deprecated|superseded
                             # etc.
created: YYYY-MM-DD
last_touched: YYYY-MM-DD     # optional; written by orchestration
supersedes: <optional ID>    # when applicable
superseded_by: <optional ID>
```

## Block 2 — Axes (signature)

Author-written. Tags the artifact on the five orthogonal retrieval axes.
Values must come from the project's `docs/axes/registry.yaml` (generated
from AVRs).

```yaml
axes:
  stage: <single value>             # lifecycle — when
  depth: <single value>             # abstraction — how deep (D0..D3)
  layer: [<list>]                   # which layer(s) — what
  concern: [<list>]                 # topics — about what
  persona: [<list>]                 # audience — for whom
```

Baseline axes (`stage`, `depth`) are universal; project axes (`layer`,
`concern`, `persona`) are seeded via project-specific AVRs.

## Block 3 — Relational (optional)

```yaml
depends: [<IDs>]                    # hard dependencies
related: [<IDs>]                    # soft cross-references
pattern_refs: [<pattern slugs>]     # claude-harness patterns cited
---
```

## Validator rules (see `validate_frontmatter.py`)

- **R1** — schema conformance (required fields, enum, id↔filename)
- **R2** — axis value backing (values in registry, scalar/list shape)
- **R3** — reference integrity (IDs resolve, no self-ref)
- **R4** — generated-file hash verification
- **R5** — AVR integrity (body sections, uniqueness per axis)
- **R6** — dual-block structural separation

Pre-commit runs R1, R2, R3, R6 (fast). CI runs R4, R5 (slow).
