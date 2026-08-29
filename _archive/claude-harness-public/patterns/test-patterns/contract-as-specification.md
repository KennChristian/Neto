# Test Pattern: Contract-as-Specification

## Purpose

Use data contracts (ODCS or similar) as executable test specifications. Each contract property becomes a test assertion, ensuring the contract is not just documentation but a living, verified specification.

## When to Use

- Projects with ODCS data contracts governing output artifacts
- Any system where a schema definition should be actively enforced, not just documented
- Post-implementation verification of output correctness
- CI pipeline validation of output conformance

## Methodology

### Step 1: Extract Assertions from Contract

For each contract, generate test assertions from:
- `schema.properties` → column existence and type checks
- `schema.required` → non-null checks
- `quality` rules → row count bounds, uniqueness, referential integrity, value ranges
- `slaProperties` → freshness, availability checks

### Step 2: Automate Verification

For each assertion:
1. Load the output artifact (CSV, DB query, API call)
2. Apply the assertion (column check, null count, distinct values, etc.)
3. Report pass/fail with specific evidence (actual vs expected)

### Step 3: Integrate into Pipeline

- Run contract tests after every output regeneration
- Include in CI pipeline as a blocking gate
- Run as part of verification audit after plan completion

## Key Principles

- **Contracts are truth**: If the contract says a column exists, the test asserts it exists. If the output disagrees, the output is wrong (or the contract needs updating).
- **No silent drift**: Every contract property must have a corresponding test. Untested properties are unenforceable.
- **Evidence-based**: Test results include concrete values (actual row count: 150, expected: ≥100), not just pass/fail.

## Implementation Notes

- For CSV outputs: parse headers, count rows, check distinct values per column
- For DB tables: query `information_schema.columns`, run COUNT/DISTINCT queries
- For API responses: make a test request, validate response body against contract schema
- Use the contract's `quality` rules catalog to select which rules to enforce

## Origin

Generalized from downstream project test specifications. Applicable to any ODCS-governed pipeline.
