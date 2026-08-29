# TS-002: Routing Accuracy

## Model

Decision-table testing across known project profiles. Validates that the weighted relevance routing algorithm (ADR-002) produces correct ACTIVATE/SUGGEST/SKIP decisions.

## Test Cases

| ID | Profile | Module | Expected | Rationale |
|----|---------|--------|----------|-----------|
| T1 | Data pipeline (CSV + PostgreSQL + dashboard tool + pandas + pytest) | data-contracts | ACTIVATE (≥8/16) | Strong multi-signal: CSV(3) + SQL DDL(3) + dashboard(2) + PostgreSQL(2) + pandas(1) = 11 |
| T2 | Data pipeline (same as T1) | verification | ACTIVATE (≥5/8) | Plan index(3) + tests(2) + pytest(1) = 6 |
| T3 | React SPA (no CSV, no DB) | data-contracts | SKIP (0/16) | No file, code, or tech signals match |
| T4 | React SPA (jest tests, plan index) | verification | ACTIVATE (≥3/8) | Plan index(3) + tests(2) + jest(1) = 6 |
| T5 | Python API (PostgreSQL, no CSV outputs) | data-contracts | SUGGEST (2-3/16) | PostgreSQL(2) + possible SQL DDL(3) but no CSV/parquet = 2-5, may be below or above threshold depending on DDL |
| T6 | Empty project (no files) | all modules | SKIP (0) | No signals matched |
| T7 | Full-stack (React + Python + PostgreSQL + CSV) | data-contracts | ACTIVATE (≥6/16) | CSV(3) + PostgreSQL(2) + SQL DDL(3) possible = ≥5 |
| T8 | Python ML (pandas + parquet, no DB) | data-contracts | SUGGEST (3/16) | parquet(2) + pandas(1) = 3, below threshold 4 |

## Verification Method

For each test case:
1. Simulate the project profile (list of files, code patterns, tech stack)
2. Run the routing algorithm from ADR-002 against each module's `module.yaml` signals
3. Calculate score
4. Assert decision matches expected column

## Edge Cases

- **T5 boundary**: Score depends on whether SQL DDL patterns are found. If only PostgreSQL tech signal matches → 2 (SUGGEST). If CREATE TABLE found → 5 (ACTIVATE). Both are acceptable.
- **Multiple modules**: When both modules are evaluated, their scores are independent. One ACTIVATE and one SKIP is valid.
- **Threshold exactly met**: Score = threshold → ACTIVATE (≥ threshold).

## Routing Table Format

Bootstrap Stage 2 should present results in this format:

```
| Module          | Score  | Threshold | Decision | Top Signals               |
|-----------------|--------|-----------|----------|---------------------------|
| data-contracts  | 11/16  | 4         | ACTIVATE | CSV + SQL DDL + PostgreSQL |
| verification    | 6/8    | 3         | ACTIVATE | plan-index + tests + pytest|
```
