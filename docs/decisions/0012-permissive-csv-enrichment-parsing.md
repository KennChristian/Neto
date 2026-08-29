# ADR-0012: Permissive enrichment-cell parsing — JSON first, semicolon fallback, warn don't skip

* Status: accepted
* Date: 2026-05-26
* Deciders: Janet

## Context and Problem Statement

The Phase 1 generator reads three curated CSVs under `data/csv/`. Ten
columns are documented as "JSON-encoded strings" (`Keyword/s`,
`primary_topics`, `sub_topics`, `signature_phrases`, `entities`,
`stances`, `notable_anecdotes`, `target_audience`, `register_markers`,
`decision_framework_signals`).

In practice, the curator used **mixed representations**: some cells
are valid JSON arrays (`["a","b","c"]`), some are
semicolon-separated strings (`"a; b; c"`), some are free prose
describing the contents, and some are empty. The first generator
implementation enforced strict JSON parsing and skipped any row with a
non-JSON cell — 22 of 64 column rows were rejected.

Rejecting those rows means the corpus loses 30% of its column-volume
coverage. The strict-validation behaviour was technically correct per
the schema spec but pragmatically catastrophic.

## Decision Drivers

* **Coverage**: we need every CSV row with a valid `id`, `title`, and
  `date` to ship.
* **Traceability**: deviations from the schema must be visible in
  `reports/validation_errors.log`, not silent.
* **Forward fidelity**: future curation passes should be able to
  re-enrich the malformed cells without re-running ingestion of
  unaffected rows.
* **Failure-mode boundary**: a *missing* `date` is fatal because it
  corrupts runtime temporal reasoning
  ([ADR-0013](0013-strict-date-validation-no-placeholders.md)). A
  *malformed* enrichment cell is recoverable because the resulting
  list-of-strings still routes; only the structured granularity is
  lost.

## Considered Options

1. **Strict JSON, skip on failure (original)** — every cell must parse
   as JSON or the row is dropped.
2. **JSON-first with semicolon fallback + WARN (chosen)** — try JSON;
   on failure, split on `;` (for list-typed cells) or fall back to the
   default empty value (for object-typed cells like `entities`); log a
   WARN line; continue with the row.
3. **Best-effort coercion silently** — try JSON, try semicolons, try
   pyparsing, do whatever it takes; no warning emitted.
4. **Pre-flight repair**: a separate `scripts/repair_csv.py` step that
   normalises every cell to JSON before ingestion.

## Decision Outcome

Chosen option: **JSON-first with semicolon fallback + WARN**.

The generator's `safe_json_parse()` accepts an `expect` hint
(`"list" | "object" | "list_of_strings"`). On `JSONDecodeError`:
- For list-typed columns: split the cell on `;`, trim, return a list
  of strings.
- For object-typed columns (`entities`): return the default empty
  object.
- Always emit a `WARN` line in `validation_errors.log` naming the
  column and the parse-error location.

The row is **not skipped**. It is written with reduced fidelity — the
structured granularity of `signature_phrases[*].voice_marker` or
`stances[*].rhetorical_move` is lost, but the doc still gets routed by
its keywords and `primary_topics`.

### Consequences

* Good: corpus coverage jumps from 41 of 64 to 64 of 64 column rows.
* Good: every fallback is logged with the source line — re-curation
  can target the exact rows that need fixing.
* Good: the rule has a clear failure boundary — date errors still
  skip, enrichment errors don't.
* Bad: routing quality is mildly degraded for fallback rows
  (`stances` and `notable_anecdotes` fall back to single-element
  lists instead of structured objects); the Sonnet composition step
  has less to work with on those docs.
* Bad: the schema spec in PROJECT.md is now "what we'd like" rather
  than "what we enforce"; readers must consult both the spec and
  `validation_errors.log` to know actual fidelity.
* Neutral: the `safe_json_parse` signature changed from
  `(cell, default) -> (value, error_or_None)` to `(cell, default,
  expect) -> (value, warning_or_None)`. The semantic shift — *error
  → warning* — is load-bearing and is reflected in the function name's
  contract.

## Pros and Cons of the Options

### Strict JSON, skip on failure (original)

* Good, because the rule is unambiguous.
* Good, because skipped rows are a strong signal to re-curate.
* Bad, because 22 of 64 column rows lost — catastrophic coverage.
* Bad, because no fidelity gradient: a row with one bad cell loses
  *all* of its other valid cells.

### JSON-first + semicolon fallback + WARN (chosen)

* Good, because coverage stays at 100%.
* Good, because the WARN-not-FAIL distinction surfaces curation debt
  without blocking the build.
* Good, because the fallback rule is mechanical (semicolon split) —
  no ambiguity in what got produced.
* Bad, because the JSON schema is no longer a tight contract.

### Silent best-effort coercion

* Good, because zero noise in the log.
* Bad, because curation debt is invisible — bad cells silently degrade
  routing quality forever.

### Pre-flight repair step

* Good, because ingestion stays strict.
* Bad, because doubles the maintenance surface — every schema change
  needs the repair script updated too.
* Bad, because semantic intent of cells like *"FLP scholars from 2025
  including Acidre, Caliosan, …"* is not mechanically repairable to
  JSON without a curator-in-the-loop — and at that point the WARN is
  the same signal.

## More Information

- Implementation: `scripts/generate_corpus_files.py`
  `safe_json_parse()`.
- See [LL-006](../lessons/LL-006-mixed-csv-cell-formats.md) for the
  surprise that drove this decision.
- Related: [ADR-0013](0013-strict-date-validation-no-placeholders.md)
  on the opposite policy for the `date` field (strict, no fallback).
