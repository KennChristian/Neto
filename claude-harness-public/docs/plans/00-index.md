# Claude Harness — Implementation Plans

## Overview

Plans for the modular restructuring of claude-harness. Each plan follows separation of concerns with clear dependency chains.

## Plan Status Key

| Status | Meaning |
|--------|---------|
| `completed` | Fully implemented and verified |
| `pending` | Currently being implemented |
| `planned` | Not yet started |

## Plans

| # | Plan | Status | Scope | Depends On |
|---|------|--------|-------|------------|
| 001 | [Core Module Extraction](./001-core-module-extraction.md) | `planned` | Extract core module | ADR-001 |
| 002 | [Data Contracts Module](./002-data-contracts-module.md) | `planned` | Package data-contracts module | ADR-001, Plan-001 |
| 003 | [Verification Module](./003-verification-module.md) | `planned` | Package verification module | ADR-001, Plan-001 |
| 004 | [Pattern Library Extraction](./004-pattern-library-extraction.md) | `planned` | Extract patterns from downstream | ADR-003, Plan-001 |
| 005 | [Registry and Routing](./005-registry-and-routing.md) | `planned` | registry.yaml + 3-stage bootstrap | ADR-002, Plans 001-003 |
| 006 | [Backward Compatibility](./006-backward-compatibility.md) | `planned` | Symlinks, migration guide | Plans 001-005 |
| 007 | [Skill Routing](./007-skill-routing.md) | `planned` | Skill relevance in registry | Plan-005 |
| 008 | [Consistency Enforcement Restructuring](./008-consistency-enforcement-restructuring.md) | `planned` | Orchestration Section 8 restructure | ADR-004 |
| 009 | [Planning Module Integration](./009-planning-module-integration.md) | `planned` | Orchestration Section 4.3, 10.1 | Plan-008 |
| 010 | [Bootstrap Enforcement & Phase Updates](./010-bootstrap-enforcement-phase-updates.md) | `planned` | Bootstrap Phase 8, module table | Plans 008, 009 |

## Dependency Graph

```
ADR-001 ─────────────────────────┐
ADR-002 ─────────────────────────┤
ADR-003 ────────────────────┐    │
                            │    │
Plan-001 (core) ◄───────────┼────┘
    │                       │
    ├──► Plan-002 (data-contracts)
    │
    ├──► Plan-003 (verification)
    │
    ├──► Plan-004 (patterns) ◄──┘
    │
    └──► Plan-005 (registry+routing) ◄── 002, 003
              │
              ├──► Plan-006 (backward compat)
              └──► Plan-007 (skill routing)

ADR-004 ──► Plan-008 (enforcement restructure)
                │
                ├──► Plan-009 (planning integration)
                │
                └──► Plan-010 (bootstrap updates) ◄── 009
```
