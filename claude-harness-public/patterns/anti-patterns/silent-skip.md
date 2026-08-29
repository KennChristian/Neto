# Anti-Pattern: Silent Skip

## The Pattern

A pipeline processes a collection of items (indicators, entities, categories) but silently skips some due to missing or misaligned configuration. The pipeline completes successfully with partial output, and no error or warning is raised. The missing items are only discovered when a human notices gaps in the final output.

## Symptoms

- Output artifact contains fewer items than expected
- Counts in summary reports don't match source data counts
- Some items appear in source data but not in the output
- Pipeline logs show no errors or warnings
- The issue persists across multiple generations of fixes because each fix addresses individual items rather than the structural cause

## Root Cause

The pipeline iterates over a configuration list (not the source data) and skips items that don't match. When configuration is incomplete or uses different identifiers than the source data, items fall through silently. There is no reconciliation step that compares "items processed" against "items available."

## Prevention Rules

1. **Reconciliation gate**: After processing, compare output item count against source item count. Alert on any discrepancy.
2. **Configuration coverage check**: Before processing, verify that every distinct item in the source data has a matching configuration entry.
3. **Explicit skip logging**: When an item is skipped for any reason, log it at WARNING level with the reason.
4. **Completeness assertion**: Add a post-processing assertion: `assert len(output_items) == len(source_items) - len(documented_exclusions)`

## Detection

- Grep for loops that iterate over config entries and silently `continue` on mismatch
- Look for `try/except` blocks that catch and suppress errors during item processing
- Search for processing functions that return partial results without indicating completeness
- Compare output row counts against source row counts in pipeline logs

## Origin

Extracted from downstream-project BUG-020 (4 generations). Generalized: "indicator" replaces domain-specific identifier, "entity" replaces domain-specific geographic unit.
