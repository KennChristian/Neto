# Plan-003: Verification Module

## Objective

Package verification-audit-agent as a self-contained module in `modules/verification/`.

## Dependencies

- ADR-001 (Modular Architecture)
- Plan-001 (Core Module Extraction)

## Scope

1. Create `modules/verification/module.yaml` with relevance scoring signals
2. Copy `verifier-creator.md` → `modules/verification/prompt.md` (update template paths)
3. Copy 2 agent templates → `modules/verification/templates/`
4. Create `modules/verification/test-patterns/verification-audit-test-cases.md`
5. Create `modules/verification/lessons/anti-patterns.md` (generalized from downstream experiences)

## Verification Criteria

- [ ] module.yaml validates against TS-001 schema
- [ ] All 5+ files exist in module directory
- [ ] `prompt.md` references correct template paths
- [ ] Relevance score against a project with tests + plans ≥ 5/8
