# Test Pattern: Contract-as-Specification Validation

## Purpose

Validate that ODCS data contracts accurately describe the actual output artifacts they govern. Contracts serve as executable specifications — any drift between contract and reality indicates either an undocumented schema change or a stale contract.

## When to Use

- After generating or updating data contracts
- After modifying output schemas (adding/removing/renaming columns)
- As part of CI pipeline validation
- During post-implementation verification audits

## Universal Test Cases

### TC-1: Schema Completeness
Every column/field in the actual output must appear in the contract's `schema.properties`. No undocumented columns.

**Verification**: Compare output file headers (or DB table columns) against contract schema keys.

### TC-2: Schema Accuracy
Each column's declared type in the contract must match the actual data type in the output.

**Verification**: Read a sample of output rows, infer types, compare against contract declarations.

### TC-3: Required Fields Present
Every field marked `required: true` in the contract must be non-null in every output row.

**Verification**: Count nulls per required column; assert zero.

### TC-4: Enum Value Coverage
For fields with `enum` constraints in the contract, every actual value must be within the declared set.

**Verification**: Extract distinct values per enum column, assert subset of declared values.

### TC-5: Row Count Bounds
If the contract declares `minRows` or `maxRows` quality rules, the output must comply.

**Verification**: Count output rows, assert within bounds.

### TC-6: Primary Key Uniqueness
If the contract declares a primary key or unique constraint, no duplicates may exist.

**Verification**: Group by PK columns, assert max group size = 1.

### TC-7: Foreign Key Referential Integrity
If the contract declares foreign key relationships, every FK value must exist in the referenced table/file.

**Verification**: Left-join FK column to referenced source, assert zero orphans.

### TC-8: Freshness SLA
If the contract declares `slaProperties.freshness`, the output's last-modified timestamp must be within the declared window.

**Verification**: Compare output file mtime (or table's max timestamp column) against freshness window.

## Implementation Notes

- Test cases TC-1 through TC-6 apply to all archetypes (CSV, DB table, API response, in-memory config)
- TC-7 applies only when foreign key relationships are declared
- TC-8 applies only when freshness SLAs are declared
- For CSV outputs, use the header row for schema extraction
- For DB tables, query `information_schema.columns` or equivalent
- For API responses, use a sample response payload

## Origin

Generalized from downstream project contract validation test specs. Applicable to any ODCS-governed data pipeline.
