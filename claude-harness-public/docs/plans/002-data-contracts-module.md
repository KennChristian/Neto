# Plan-002: Data Contracts Module

## Objective

Package data-contracts as a self-contained module in `modules/data-contracts/`.

## Dependencies

- ADR-001 (Modular Architecture)
- Plan-001 (Core Module Extraction)

## Scope

1. Create `modules/data-contracts/module.yaml` with relevance scoring signals
2. Copy `data-contracts-prompt.md` → `modules/data-contracts/prompt.md` (update template paths)
3. Copy 6 ODCS templates → `modules/data-contracts/templates/`
4. Copy `check-contract-drift.sh` → `modules/data-contracts/scripts/`
5. Create `modules/data-contracts/hooks/settings-fragment.json`
6. Create `modules/data-contracts/test-patterns/contract-validation.md` (generalized, zero domain terms)
7. Create `modules/data-contracts/lessons/anti-patterns.md` (generalized from downstream bugs)

## Verification Criteria

- [ ] module.yaml validates against TS-001 schema
- [ ] All 10+ files exist in module directory
- [ ] `prompt.md` has no references to old `templates/` paths
- [ ] `contract-validation.md` contains zero domain-specific terms
- [ ] Manual relevance score against a data pipeline project ≥ 8/16

## Edge Cases

- Project with CSV outputs but no DB → score = 3 (below threshold 4) → SUGGEST, not ACTIVATE
- Python project with pandas only → score = 1 → SKIP
