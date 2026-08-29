# Anti-Pattern: Config-Data Misalignment

## The Pattern

A configuration mapping (e.g., integer codes to labels, category IDs to names) passes structural validation — valid syntax, all required keys present, correct types — but contains semantic errors. The mapped values don't correspond to reality: wrong labels, transposed entries, or values from a different version of the data.

## Symptoms

- Output artifacts display plausible but incorrect labels or categories
- Downstream consumers show wrong information without raising errors
- Automated tests pass because they validate structure (schema, types, non-null) but not semantics (correctness of values)
- The issue recurs across multiple fix attempts because each fix corrects individual values rather than adding systematic validation

## Root Cause

Validation checks structure but not semantics. There is no ground-truth comparison step that verifies mapped values against an authoritative source. The configuration is treated as self-evidently correct once it parses successfully.

## Prevention Rules

1. **Semantic validation**: Compare configuration mapping values against an authoritative source document or dataset. Assert specific known mappings.
2. **Spot-check assertions**: Include test cases that assert specific known value→label mappings from the domain authority.
3. **Bidirectional coverage**: Verify that every value in the data has a mapping entry AND every mapping entry has a corresponding value in the data.
4. **Version pinning**: Pin configuration mappings to a specific version of the authoritative source. Alert when the source version changes.

## Detection

- Grep for validation code that checks `is not None`, `len() > 0`, or schema conformance without comparing actual values
- Look for configuration files that are tested only by parsing, not by content assertion
- Search for mapping lookups that use `.get(key, default)` with a silent default rather than raising on missing keys
- Look for test files that validate configuration structure but contain no assertions about specific values

## Origin

Extracted from downstream-project BUG-014 (3 generations). Generalized: "configuration mapping" replaces domain-specific encoding mechanism.
