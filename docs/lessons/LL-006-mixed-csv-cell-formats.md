# LL-006: Strict JSON parsing rejected 22 of 64 column rows whose enrichment cells used semicolon-separated text

* Date: 2026-05-26
* Severity: high (would have lost ~34% of column corpus coverage)
* Related: [ADR-0012](../decisions/0012-permissive-csv-enrichment-parsing.md)

## Symptom

First dry-run of `scripts/generate_corpus_files.py` reported
**80 rows processed, 57 successful, 23 skipped**. The
`reports/validation_errors.log` listed 22 column rows skipped with
errors like:

```
cjp_columns_curated.csv:11 SKIP JSON parse errors for CA010 —
Keyword/s: JSON parse error: Expecting value (col 1)
```

The skipped rows included whole-theme blocks (`CA010`-`CA015`,
`CB001`-`CB007`, `CC001`-`CC013`) — a third of the column corpus.

## 5 Whys

1. **Why were these rows skipped?** Because their `Keyword/s` (and
   sometimes other enrichment) cells were not valid JSON arrays.
2. **Why were they not valid JSON arrays?** Because the curator wrote
   them as semicolon-separated strings: `"arbitral award; UNCLOS Annex
   VII; nine-dash line; ..."` rather than `["arbitral award",
   "UNCLOS Annex VII", "nine-dash line", ...]`.
3. **Why did the curator use semicolons in some rows and JSON in
   others?** Because the source CSVs were assembled across multiple
   curation sessions and external tools; semicolon lists are easier to
   author in a spreadsheet cell than JSON arrays (no escaping of
   commas inside items, no opening/closing brackets to balance).
4. **Why did the schema declare JSON when the curator's natural format
   was semicolons?** Because the schema was specified before the
   curation tooling was finalised — a top-down design that the
   bottom-up curator pragma drifted away from over multiple sessions.
5. **Why was the parser written to skip-on-failure instead of fall
   back?** Because the *date* field needs strict skip-on-failure
   ([ADR-0013](../decisions/0013-strict-date-validation-no-placeholders.md))
   and the same `try/except + skip` pattern was applied uniformly
   across all required fields without distinguishing
   *semantic-critical* (date) from *fidelity-critical* (enrichment).

## Root Cause

A uniform validation strategy was applied to fields with very
different failure-mode budgets. The `date` field is
**semantic-critical** — a wrong date corrupts runtime temporal
reasoning irreversibly, so skip-on-failure is correct. The enrichment
fields are **fidelity-critical** — a wrong cell degrades router
granularity but the doc still routes by keywords; skip-on-failure
discards the rest of the row's signal for no proportionate gain.

The deeper miss: the *schema* and the *curator's natural
representation* were not reconciled during a sample pass before
ingestion ran end-to-end.

## Fix Applied

`safe_json_parse()` now accepts an `expect` hint
(`"list" | "object" | "list_of_strings"`) and falls back:
- On a list-typed cell: `;`-split, trim, return a list of strings.
- On `entities` (object-typed): return the default empty entities
  object.
- Always log a `WARN ... used fallback` line; never skip the row.

The row is written with reduced structural fidelity but full
content fidelity. Implementation: `scripts/generate_corpus_files.py`
`safe_json_parse()` and the `expect`-aware `parsed[col]` loop in
`process_row()`. See
[ADR-0012](../decisions/0012-permissive-csv-enrichment-parsing.md)
for the policy.

Result: 79 of 80 rows now generate (the single remaining skip is the
date-less biography `GC001` —
[ADR-0013](../decisions/0013-strict-date-validation-no-placeholders.md)).

## Generalizable Lesson

Before applying a uniform validation strategy across a multi-field
schema, classify each field by its *failure-mode budget*:

| Budget | Strategy |
|---|---|
| Semantic-critical (corrupts runtime if wrong) | Strict — fail loudly, skip the row, no placeholders. |
| Fidelity-critical (degrades quality if wrong, but routing still works) | Permissive — fall back, log a warning, keep the row. |

Run a curator sample-pass on 5-10 representative rows *before* you
generate the whole corpus. Compare the curator's actual cell
representations against the schema's expected formats. Disagreements
that surface in a sample are cheap to reconcile; disagreements that
surface only when the whole batch fails ingestion are expensive
because by then the rejection number is large and the fix touches the
ingestion engine, not just the schema.

Specifically: any field whose contract reads "JSON-encoded string"
should be accompanied by a 2-line curator example and an explicit
fallback rule, or the schema should be relaxed to
"list (any of JSON array | semicolon-separated string)" from day one.
