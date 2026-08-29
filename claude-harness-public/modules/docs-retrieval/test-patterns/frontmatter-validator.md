# Test Pattern: Frontmatter Validator (R1..R6)

Generic validator pattern for projects using the `docs-retrieval` module.
Covers the 6 rule categories from the project-side Plan 233 spec,
generalized.

## Rule categories

### R1 — Schema conformance
- Required state fields present: `id`, `kind`, `status`, `created`
- `id` matches filename stem
- `kind` matches directory
- `status` is in the enum for that kind

### R2 — Axis value backing
- Every axis value in `axes:` exists in `docs/axes/registry.yaml`
- Registry entry has `status: active`
- Multi-valued axes carry lists; single-valued axes carry scalars

### R3 — Reference integrity
- IDs in `related:`, `depends:`, `pattern_refs:` resolve to existing files
- No self-reference
- Cross-kind references allowed (PLAN→ADR, TS→PLAN, etc.)

### R4 — Generated-file hash verification
- Files declared generated carry a parseable hash header
- Recomputed `source-sha` matches declared value
- Files with unparseable or missing generator tag fail

### R5 — AVR integrity (docs/axes/records/)
- AVRs carry `axis`, `value`, and the 5 required body sections
- `value` is unique per `axis` across all active AVRs
- AVRs live under the designated directory, not mixed into decisions

### R6 — Dual-block structure
- Frontmatter contains state block, axes block, relational block
- Blocks visually separated per convention

## Exit codes
- 0 — all validations pass
- 1 — input error
- 2..7 — single rule category failed (R1..R6 respectively)
- 10 — multiple categories failed

## Pre-commit vs. CI split
- **Pre-commit (fast, <3s on 500 files):** R1, R2, R3, R6
- **CI (slow):** R4 (full hash recomputation), R5 (cross-AVR uniqueness)

## Reference implementation

See `../scripts/validate_frontmatter.py` for the canonical implementation.
Single-file, stdlib + pyyaml (ADR-145 compliance).

## Origin

Extracted from `rev1_2` / Plan 233. Rules R1–R6 are the project's validator
specification generalized for harness consumption.
