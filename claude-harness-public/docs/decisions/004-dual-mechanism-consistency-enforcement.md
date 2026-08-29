---
status: proposed
date: 2026-03-23
---

# 004: Dual-Mechanism Consistency Enforcement Pattern

## Context and Problem Statement

The harness maintains index-like artifacts that must stay in sync with the file system: MANIFEST.md tracks source files, registry.yaml tracks modules. When these indexes drift from reality, downstream processes silently break — bootstrap activates nonexistent modules, orchestration references missing files, and hooks fire on stale paths.

MANIFEST enforcement was the first implementation (PostToolUse hook + CI script). Registry enforcement followed the same pattern independently. As the harness grows, additional index-like artifacts may emerge (skill registries, pattern indexes, contract catalogs). Without a documented convention, each new enforcement system risks diverging in behavior, UX, and error semantics.

## Decision Drivers

- Silent drift is the primary failure mode — indexes that fall out of sync produce confusing downstream errors, not immediate failures
- Real-time feedback during authoring prevents drift at the source, reducing CI-only detection lag
- Batch validation for CI catches anything that slipped past hooks (e.g., manual file moves, git merges)
- Cognitive load — one pattern for all enforcement systems reduces learning curve

## Considered Options

1. Ad-hoc scripts per artifact — each enforcement system uses its own approach (current implicit state)
2. Single generalized enforcement framework — one script parameterized for any artifact type
3. Documented convention with artifact-specific script pairs — standardize the pattern, but each artifact gets its own scripts

## Decision Outcome

Chosen option: "3 — Documented convention with artifact-specific script pairs", because it standardizes behavior and UX while allowing artifact-specific validation logic. A fully generalized framework (option 2) would add abstraction without proportional value — each artifact has distinct validation semantics.

Every index-like artifact in the harness uses the same dual-mechanism enforcement pattern:

1. **PostToolUse hook** (`check-{artifact}.sh`) — fires on Write|Edit, detects drift in real time, exits 2 with actionable message on inconsistency
2. **CI validation script** (`validate-{artifact}.sh`) — batch validation covering references, structural requirements, and asset existence; exits 1 on failure

Both mechanisms share these properties:
- Exit non-zero on inconsistency (hook: exit 2 to block; CI: exit 1 to fail)
- Actionable error messages naming the specific file and required action
- Self-contained scripts requiring no external dependencies beyond bash/jq
- Registered in `core/module.yaml` under `scripts`

### Current implementations

| Artifact | Hook Script | CI Script | Registered |
|----------|------------|-----------|------------|
| MANIFEST.md | check-manifest.sh | validate-manifests.sh | core/module.yaml |
| registry.yaml | check-registry.sh | validate-registry.sh | core/module.yaml |

### Convention for new enforcement systems

When adding a new index-like artifact:
1. Create `check-{artifact}.sh` following the PostToolUse hook contract (reads JSON stdin, exits 0/2)
2. Create `validate-{artifact}.sh` following the CI script contract (exits 0/1, prints summary)
3. Register both in `core/module.yaml` under `scripts`
4. Add hook entries to all `hooks/settings*.json.example` files
5. Document in orchestration-prompt.md Section 8 as a new subsection

### Consequences

**Positive:**
- Consistent UX — all enforcement systems behave identically
- Easy to extend — follow the convention, add two scripts
- Discoverable — Section 8 of orchestration-prompt.md is the single reference for all enforcement

**Negative:**
- Hook execution overhead — each Write/Edit fires multiple PostToolUse hooks (one per enforcement system)
- No shared runtime — each script pair is independent, meaning structural changes (e.g., changing the hook contract) require updating all scripts

**Neutral:**
- Each artifact still needs its own validation logic; the convention standardizes the shell, not the semantics

## More Information

- Related: `core/scripts/check-manifest.sh` (first implementation of the pattern)
- Related: `core/scripts/check-registry.sh` (second implementation, following the convention)
- Section 8 of `core/orchestration-prompt.md` documents both systems
