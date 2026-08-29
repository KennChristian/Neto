# Quality Rules Catalog — ODCS v3.1.0

> **Usage:** When generating data contracts, select applicable rules from this catalog.
> Substitute `{col}` with the actual column name and `{table}` with the table/schema name.
> Each rule includes an ODCS YAML snippet and guidance on when to apply it.

---

## 1. Completeness

Rules that ensure data is present and not missing.

### qr-row-count — Minimum row count

**When to apply:** Every tabular artifact (CSV, DB table). Set threshold based on expected data volume.

```yaml
- id: qr-row-count
  name: Minimum row count
  type: library
  dimension: completeness
  severity: error
  description: Output must have at least {MIN} rows
  customProperties:
    - property: metric
      value: rowCount
    - property: operator
      value: ">="
    - property: value
      value: {MIN}
```

### qr-{col}-not-null — Column not null

**When to apply:** Any required column that must never be null. Use on primary keys, foreign keys, and business-critical fields.

```yaml
- id: qr-{col}-not-null
  name: "{col} not null"
  type: library
  dimension: completeness
  severity: error
  customProperties:
    - property: metric
      value: nullValues
    - property: operator
      value: "=="
    - property: value
      value: 0
```

### qr-{entity}-present — Entity presence check

**When to apply:** When specific entities (e.g., all regions, all indicator IDs) must appear in the output.

```yaml
- id: qr-{entity}-present
  name: "{entity} present"
  type: sql
  dimension: completeness
  severity: error
  description: Every expected {entity} must have at least one row
  customProperties:
    - property: query
      value: "SELECT COUNT(DISTINCT {entity_col}) FROM {table}"
    - property: operator
      value: ">="
    - property: value
      value: {EXPECTED_COUNT}
```

### qr-dimension-coverage — Dimension completeness

**When to apply:** When every combination of key dimensions must be represented (e.g., every indicator × year × place must have an 'all' dimension).

```yaml
- id: qr-dimension-coverage
  name: "{dimension} coverage"
  type: sql
  dimension: completeness
  severity: error
  description: Every {parent_key} must have a row for {dimension_value}
  customProperties:
    - property: query
      value: "SELECT COUNT(*) FROM {table} WHERE {dimension_col} = '{dimension_value}'"
    - property: operator
      value: ">="
    - property: value
      value: 1
```

---

## 2. Accuracy

Rules that ensure values are correct and within expected ranges.

### qr-{col}-non-negative — Non-negative values

**When to apply:** Columns representing counts, proportions, or measures that cannot be negative.

```yaml
- id: qr-{col}-non-negative
  name: "{col} non-negative"
  type: sql
  dimension: accuracy
  severity: error
  description: "{col} must be >= 0"
  customProperties:
    - property: query
      value: "SELECT COUNT(*) FROM {table} WHERE {col} < 0"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

### qr-{col}-range — Value range check

**When to apply:** Columns with known valid ranges (e.g., percentages 0–100, proportions 0–1, years 1900–2100).

```yaml
- id: qr-{col}-range
  name: "{col} in range [{MIN}, {MAX}]"
  type: sql
  dimension: accuracy
  severity: error
  description: "{col} must be between {MIN} and {MAX}"
  customProperties:
    - property: query
      value: "SELECT COUNT(*) FROM {table} WHERE {col} < {MIN} OR {col} > {MAX}"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

### qr-{col}-sum — Column sum check

**When to apply:** When column values must sum to a known total (e.g., percentage distribution summing to 100).

```yaml
- id: qr-{col}-sum
  name: "{col} sum check"
  type: sql
  dimension: accuracy
  severity: warning
  description: "Sum of {col} grouped by {group_col} should equal {EXPECTED_SUM}"
  customProperties:
    - property: query
      value: "SELECT COUNT(*) FROM (SELECT {group_col}, ABS(SUM({col}) - {EXPECTED_SUM}) AS diff FROM {table} GROUP BY {group_col} HAVING ABS(SUM({col}) - {EXPECTED_SUM}) > 0.01) t"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

### qr-cross-field-consistency — Cross-field validation

**When to apply:** When two or more columns have a mathematical or logical relationship (e.g., `gap = top_value - bottom_value`).

```yaml
- id: qr-cross-field-consistency
  name: Cross-field consistency ({field_a} vs {field_b})
  type: sql
  dimension: accuracy
  severity: error
  description: "{RELATIONSHIP_DESCRIPTION}"
  customProperties:
    - property: query
      value: "SELECT COUNT(*) FROM {table} WHERE ABS({field_a} - ({EXPRESSION})) > 0.001"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

---

## 3. Conformity

Rules that ensure values match expected formats and domains.

### qr-{col}-format — Format validation

**When to apply:** String columns with a defined format (dates, codes, identifiers).

```yaml
- id: qr-{col}-format
  name: "{col} format"
  type: library
  dimension: conformity
  severity: warning
  description: "{col} must match pattern {PATTERN}"
  customProperties:
    - property: metric
      value: invalidValues
    - property: operator
      value: "=="
    - property: value
      value: 0
```

### qr-{col}-enum — Enumerated values

**When to apply:** Columns restricted to a known set of valid values (e.g., status codes, category labels).

```yaml
- id: qr-{col}-enum
  name: "{col} valid values"
  type: sql
  dimension: conformity
  severity: error
  description: "{col} must be one of: {VALID_VALUES}"
  customProperties:
    - property: query
      value: "SELECT COUNT(*) FROM {table} WHERE {col} NOT IN ({VALID_VALUES_QUOTED})"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

### qr-{col}-valid-json — JSON validity

**When to apply:** String columns that contain serialized JSON (arrays, objects).

```yaml
- id: qr-{col}-valid-json
  name: "{col} valid JSON"
  type: custom
  dimension: conformity
  severity: error
  description: Every {col} value must parse as valid JSON
```

### qr-{col}-regex — Regex pattern match

**When to apply:** Columns with complex format patterns not covered by simple format rules.

```yaml
- id: qr-{col}-regex
  name: "{col} regex"
  type: sql
  dimension: conformity
  severity: warning
  description: "{col} must match regex: {REGEX}"
  customProperties:
    - property: query
      value: "SELECT COUNT(*) FROM {table} WHERE {col} !~ '{REGEX}'"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

---

## 4. Consistency

Rules that ensure agreement between related datasets.

### qr-fk-integrity — Foreign key integrity

**When to apply:** Columns referencing dimension/lookup tables. Every value must exist in the referenced table.

```yaml
- id: qr-fk-integrity
  name: FK integrity ({col} → {ref_table})
  type: sql
  dimension: consistency
  severity: error
  description: Every {col} value must exist in {ref_table}.{ref_col}
  customProperties:
    - property: query
      value: "SELECT COUNT(*) FROM {table} t LEFT JOIN {ref_table} r ON t.{col} = r.{ref_col} WHERE r.{ref_col} IS NULL"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

### qr-cross-artifact — Cross-artifact consistency

**When to apply:** When two output artifacts share overlapping data that must agree (e.g., summary table totals match detail table sums).

```yaml
- id: qr-cross-artifact
  name: Cross-artifact consistency ({artifact_a} vs {artifact_b})
  type: custom
  dimension: consistency
  severity: error
  description: "{CONSISTENCY_DESCRIPTION}"
```

### qr-temporal-monotonic — Temporal monotonicity

**When to apply:** Time-series data where values should only increase (or only decrease) over time.

```yaml
- id: qr-temporal-monotonic
  name: Temporal monotonicity ({col})
  type: sql
  dimension: consistency
  severity: warning
  description: "{col} should not decrease across consecutive time periods"
  customProperties:
    - property: query
      value: "SELECT COUNT(*) FROM (SELECT {col}, LAG({col}) OVER (PARTITION BY {entity_col} ORDER BY {time_col}) AS prev FROM {table}) t WHERE {col} < prev"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

---

## 5. Timeliness

Rules that ensure data is current and up-to-date.

### qr-freshness — Output freshness

**When to apply:** Any output that must be regenerated after source changes. Define the maximum staleness.

```yaml
# Use as an slaProperties entry, not a schema quality rule:
slaProperties:
  - property: freshness
    description: "Output must be regenerated within {HOURS}h of source data change"
    customProperties:
      - property: gate
        value: "{GATE_COMMAND}"
```

### qr-timestamp-recent — Recent timestamp check

**When to apply:** Tables with a `created_at` or `updated_at` column that should have recent entries.

```yaml
- id: qr-timestamp-recent
  name: Recent {col} timestamp
  type: sql
  dimension: timeliness
  severity: warning
  description: "Most recent {col} must be within {DAYS} days"
  customProperties:
    - property: query
      value: "SELECT CASE WHEN MAX({col}) >= NOW() - INTERVAL '{DAYS} days' THEN 0 ELSE 1 END FROM {table}"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

---

## 6. Uniqueness

Rules that ensure no unwanted duplicates exist.

### qr-pk-unique — Primary key uniqueness

**When to apply:** Every table/dataset with a defined primary key or natural key.

```yaml
- id: qr-pk-unique
  name: Primary key uniqueness
  type: sql
  dimension: uniqueness
  severity: error
  description: "({PK_COLUMNS}) must be unique"
  customProperties:
    - property: query
      value: "SELECT COUNT(*) - COUNT(DISTINCT ({PK_COLUMNS})) FROM {table}"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

### qr-{col}-unique — Column uniqueness

**When to apply:** Non-PK columns that should still be unique (e.g., email, slug, external ID).

```yaml
- id: qr-{col}-unique
  name: "{col} uniqueness"
  type: sql
  dimension: uniqueness
  severity: error
  description: "{col} values must be unique"
  customProperties:
    - property: query
      value: "SELECT COUNT(*) - COUNT(DISTINCT {col}) FROM {table}"
    - property: operator
      value: "=="
    - property: value
      value: 0
```

### qr-no-duplicates — Full row deduplication

**When to apply:** When entire rows should never be duplicated (e.g., event logs, immutable records).

```yaml
- id: qr-no-duplicates
  name: No duplicate rows
  type: sql
  dimension: uniqueness
  severity: error
  description: No two rows should be identical across all columns
  customProperties:
    - property: query
      value: "SELECT COUNT(*) FROM (SELECT *, COUNT(*) AS cnt FROM {table} GROUP BY {ALL_COLUMNS} HAVING COUNT(*) > 1) t"
    - property: operator
      value: "=="
    - property: value
      value: 0
```
