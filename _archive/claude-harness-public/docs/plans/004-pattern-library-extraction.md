# Plan-004: Pattern Library Extraction

## Objective

Extract reusable patterns from downstream projects into `patterns/`.

## Dependencies

- ADR-003 (Cross-Project Pattern Library)
- Plan-001 (Core Module Extraction)

## Scope

1. Create `patterns/README.md` (index linking all patterns)
2. Create 4 anti-patterns: silent-skip, stale-output, config-data-misalignment, silent-substitution
3. Create 4 decision guides: data-centric-integrity, output-regeneration, progressive-disclosure, data-provenance
4. Create 2 test patterns: contract-as-specification, ground-truth-comparison

## Extraction Rules

- Replace ALL domain terms with generic equivalents
- Preserve structural insight (root cause + prevention rules)
- Include `## Origin` for traceability

## Verification Criteria

- [ ] Every file in `patterns/` has zero occurrences of domain-specific terms
- [ ] Every anti-pattern has all 6 required sections
- [ ] Every decision guide has all 5 required sections
- [ ] `patterns/README.md` links to all 10 files
