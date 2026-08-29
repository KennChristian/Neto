# Decision Guide: Data-Centric Integrity Validation

## The Decision

How should a pipeline validate that configuration-to-data alignment is correct at runtime, beyond structural schema validation?

## When This Applies

- Projects where configuration files map identifiers to labels, categories, or transformation rules
- Pipelines where configuration drift can produce plausible but incorrect output
- Systems where structural validation (schema, types, non-null) is insufficient to guarantee correctness
- Projects that have experienced configuration-data misalignment bugs

## Options

### Option A: Structural Validation Only
Validate configuration syntax, required keys, and types. Trust that values are correct.

- **When to choose**: Low-risk outputs, configuration rarely changes, values are trivially verifiable by humans
- **Pros**: Simple, fast, low maintenance
- **Cons**: Misses semantic errors. Silent failures on value drift.

### Option B: Structural + Spot-Check Assertions
Add test cases that assert specific known value→label mappings alongside structural validation.

- **When to choose**: Medium-risk outputs, configuration changes occasionally, authoritative source is accessible
- **Pros**: Catches value drift for checked entries. Low additional effort.
- **Cons**: Doesn't catch errors in unchecked entries. Coverage depends on spot-check selection.

### Option C: Full Semantic Validation Against Authoritative Source
Programmatically compare all configuration values against the authoritative source document or dataset.

- **When to choose**: High-risk outputs, configuration is large or complex, errors have significant downstream impact
- **Pros**: Complete coverage. Catches all value drift.
- **Cons**: Requires machine-readable authoritative source. Higher implementation and maintenance effort.

## Recommendation

Default to **Option B** for most projects — it provides meaningful protection with low effort. Upgrade to **Option C** when: (1) configuration has more than 50 entries, (2) the authoritative source is machine-readable, or (3) previous bugs have demonstrated that spot-checks are insufficient.

Always implement **Option A** as the minimum baseline.

## Origin

Derived from downstream-project ADR-022. Generalized: "configuration mapping" replaces domain-specific encoding mechanism.
