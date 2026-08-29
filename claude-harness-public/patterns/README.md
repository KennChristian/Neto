# Cross-Project Pattern Library

Reusable patterns extracted from downstream projects. Each pattern captures structural insights that apply across projects and tech stacks.

## Categories

### Anti-Patterns (`anti-patterns/`)

Recurring failure modes with symptoms, root cause, and prevention rules.

| File | Pattern | Origin |
|------|---------|--------|
| [silent-skip.md](anti-patterns/silent-skip.md) | Pipeline silently produces partial output on missing config alignment | BUG-020 |
| [stale-output.md](anti-patterns/stale-output.md) | Config changed but artifacts not regenerated | BUG-006/009 |
| [config-data-misalignment.md](anti-patterns/config-data-misalignment.md) | Structural validation passes but semantic validation absent | BUG-014 |
| [silent-substitution.md](anti-patterns/silent-substitution.md) | Input file replaced without identity verification | BUG-034 |
| [manifest-schema-drift.md](anti-patterns/manifest-schema-drift.md) | Hand-extended harness template drifts from true state when no writer contract exists | rev1_2 / LL-064 |
| [hand-edited-generated-artifact.md](anti-patterns/hand-edited-generated-artifact.md) | Fixes to generator output get overwritten; no hash header guard | rev1_2 / ADR-143 |
| [closed-tag-taxonomy.md](anti-patterns/closed-tag-taxonomy.md) | Single closed-tag vocabulary fails past ~100 artifacts (exclusive-membership bias, taxonomy rot) | rev1_2 / LL-065 |

### Decision Guides (`decision-guides/`)

Structured guidance for common architectural decisions.

| File | Decision | Origin |
|------|----------|--------|
| [data-centric-integrity.md](decision-guides/data-centric-integrity.md) | How to validate config-to-data alignment at runtime | ADR-022 |
| [output-regeneration.md](decision-guides/output-regeneration.md) | How to enforce output freshness after source changes | ADR-014 |
| [progressive-disclosure.md](decision-guides/progressive-disclosure.md) | How to layer docs for LLM context efficiency | ADR-011 |
| [data-provenance.md](decision-guides/data-provenance.md) | How to verify input file identity | ADR-029 |
| [multi-artifact-version-resolution.md](decision-guides/multi-artifact-version-resolution.md) | Artifact registry, per-artifact resolution loop, impact notation for projects with multiple versioned artifacts | ADR-084 |
| [artifact-cascade-staleness.md](decision-guides/artifact-cascade-staleness.md) | Directed cascade graph, advisory vs enforced warnings, integration with drift detection | ADR-085 |
| [multi-axis-vs-flat-taxonomy.md](decision-guides/multi-axis-vs-flat-taxonomy.md) | Choose multi-axis orthogonal tagging over flat closed-tag taxonomy at ≥100 artifacts | rev1_2 / ADR-141 |
| [generated-index-vs-hand-authored.md](decision-guides/generated-index-vs-hand-authored.md) | Generate index files when the same fact appears in multiple sources | rev1_2 / ADR-143 |
| [frontmatter-as-single-source.md](decision-guides/frontmatter-as-single-source.md) | Artifact frontmatter is the single writer of stateful metadata; trackers become derived views | rev1_2 / ADR-142 |

### Test Patterns (`test-patterns/`)

Reusable test strategies and methodologies.

| File | Pattern | Origin |
|------|---------|--------|
| [contract-as-specification.md](test-patterns/contract-as-specification.md) | Universal test cases for schema contract validation | TS-092 |
| [ground-truth-comparison.md](test-patterns/ground-truth-comparison.md) | Formal baseline methodology for output validation | BUG-019 |
| [frontmatter-schema-validator.md](test-patterns/frontmatter-schema-validator.md) | R1–R6 rule categories for validating YAML frontmatter (schema, vocab, references, hashes) | rev1_2 / Plan 233 |
| [generated-artifact-freshness.md](test-patterns/generated-artifact-freshness.md) | Hash-header freshness verification; pre-commit hand-edit detection | rev1_2 / ADR-143 |
| [axis-coverage.md](test-patterns/axis-coverage.md) | Closed-vocabulary coverage: every registered value has users; no unregistered values | rev1_2 / Plan 232, TS-126 |

## Contributing

See `docs/guides/harness-pattern-contributor-guide.md` for extraction rules, templates, and quality gates.
