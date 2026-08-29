# Plan-005: Registry and Routing

## Objective

Build `registry.yaml` and rewrite bootstrap for 3-stage module-aware pipeline.

## Dependencies

- ADR-002 (Weighted Relevance Routing)
- Plan-001 (Core Module Extraction)
- Plan-002 (Data Contracts Module)
- Plan-003 (Verification Module)

## Scope

1. Create `registry.yaml` listing core module, optional modules, pattern directories, and skills
2. Rewrite `core/bootstrap-prompt.md` with 3-stage pipeline:
   - **Stage 1 — ANALYZE**: Project profile detection (existing Phase 1)
   - **Stage 2 — ROUTE**: Read registry.yaml, evaluate module signals, present routing table, user confirms
   - **Stage 3 — EXECUTE**: Core phases + activated module phases in `phase_order` + wire patterns
3. Document routing algorithm in bootstrap prompt
4. Update `core/orchestration-prompt.md` Section 10 for module-aware routing

## Verification Criteria

- [ ] `registry.yaml` is valid YAML listing core + 2 modules + patterns + 3 skills
- [ ] Bootstrap has 3 clearly labeled stages
- [ ] Routing algorithm documented with score/threshold/decision table
- [ ] Edge cases handled: missing registry → fallback, module.yaml error → skip + warn, all modules score 0 → core-only
