# Test Pattern: Frontmatter Schema Validator

## The Pattern

Validate YAML frontmatter blocks across a corpus of artifacts against a declared schema. Cover required-field presence, enum membership, reference resolution, and cross-file consistency.

## When To Use

Any project where artifacts carry structured frontmatter that is read by orchestration, generators, or agents. Validation catches schema violations before they reach downstream consumers that assume conformance.

## Rule Categories

### R1 — Schema Conformance

For every authored artifact in scope:
- Frontmatter block is delimited correctly (e.g., `---` fence)
- Required state fields are present: `id`, `kind`, `status`, `created`
- `id` matches the filename stem (e.g., `PLAN-214-foo.md` has `id: PLAN-214`)
- `kind` matches the artifact's directory or file prefix
- `status` is a valid enum value for the artifact's kind

### R2 — Closed Vocabulary Membership

For every field whose value must come from a closed vocabulary (axis values, status enums, kind enum):
- The value exists in the registry/enum
- The registry entry is currently `active` (not deprecated)
- Scalar vs. list shape matches the schema (e.g., some axes are single-valued, others multi-valued)

### R3 — Reference Integrity

For every field containing references to other artifacts (`related`, `depends`, `pattern_refs`, `supersedes`):
- The referenced ID resolves to an existing file
- Cross-kind references are allowed per the schema (PLAN→ADR, TS→PLAN, etc.)
- Self-reference is rejected
- Circular dependencies in `depends` are warned (not failed) to allow co-dependent artifacts

### R4 — Generated-File Hash Verification

For every file declared as generated (via hash header comment):
- The header is parseable
- Recomputed source hash matches the declared value, OR the file is explicitly marked stale
- A file with a generator header but an unparseable hash is an error

### R5 — Vocabulary Record Integrity

For every vocabulary-governance record (e.g., Axis Value Records):
- Required fields present
- `value` is unique within its axis for currently active records
- Record lives in the declared governance directory, not co-located with domain records

### R6 — Structural Block Separation

- Frontmatter contains the required logical blocks (state, signature, relational)
- Blocks are visually separated per the declared convention

## Exit Code Discipline

- `0` — all validations pass
- `1` — input error (schema missing, registry missing)
- `2`–`7` — one rule category failed (specific codes per R1…R6)
- `10` — multiple categories failed

Deterministic exit codes enable selective re-runs (`--rules R1,R2` for fast pre-commit).

## CI vs. Pre-Commit Split

- **Pre-commit (fast):** R1, R2, R3, R6 — structural rules that complete in under 3 seconds on a 500-file corpus
- **CI (slow):** R4 (full hash verification across generated files), R5 (governance consistency across all vocabulary records)

The split balances local feedback speed against full correctness guarantees.

## Implementation Language

Any language is fine. Language-neutrality is preserved by keeping rule definitions declarative (schema + registry) rather than imperative. Python with stdlib + a YAML library is a common choice for reference implementations because validators handle data, not orchestration.

## Origin

`rev1_2` (Plan 233). Rules R1–R6 are the project's validator specification, generalized for harness consumption.

## Related

- `decision-guides/frontmatter-as-single-source.md` — why frontmatter carries the state this validator checks
- `test-patterns/generated-artifact-freshness.md` — R4's detailed mechanism
- `test-patterns/axis-coverage.md` — complementary coverage check
