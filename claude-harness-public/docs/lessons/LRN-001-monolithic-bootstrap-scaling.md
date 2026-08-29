# LRN-001: Monolithic Bootstrap Scaling

## Symptom

Adding the data-contracts capability to claude-harness required editing `bootstrap-prompt.md` directly, inserting Phase 8.5 as a hardcoded conditional block. Each new capability addition would require editing the same core file, with increasingly fragile phase numbering (8.5, 8.6, 8.7...).

## Root Cause

The bootstrap prompt was designed for a fixed set of capabilities, not as an extensible system. There was no module discovery mechanism — capabilities could only be added by modifying the bootstrap's control flow.

## Resolution

ADR-001 introduced modular architecture with `core/`, `modules/`, and `patterns/` tiers. Modules self-describe via `module.yaml` manifests. The bootstrap discovers modules dynamically via `registry.yaml` instead of hardcoding phases.

## Prevention

When adding a capability to a framework or orchestration system, ask: **"Does this require editing an existing orchestration file?"** If the answer is yes, the system needs extension points — a registry, plugin system, or module discovery mechanism.

## Recommendation

Favor registry-based discovery over hardcoded phase lists. Each capability should be a self-contained unit that can be added or removed without modifying core files.
