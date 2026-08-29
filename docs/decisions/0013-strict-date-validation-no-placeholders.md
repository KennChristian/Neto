# ADR-0013: Strict date validation — skip rows with missing/unparseable `Date`; reject placeholders

* Status: accepted
* Date: 2026-05-26
* Deciders: Janet

## Context and Problem Statement

The Phase 1 corpus has temporal semantics baked into its
persona-modelling layer. CJP's voice routinely references time
explicitly: *"last year I wrote about…"*, *"during my term as Chief
Justice…"*, *"ten years ago at the Global Forum…"*. The Sonnet
composition step at runtime computes relative phrasing from each
document's `date` field.

If a `date` is missing, ambiguous, or fabricated, the model has two
failure modes:
1. **Silent drift**: it speaks of a 2026 column as if it were 2006.
2. **Loud invention**: it confabulates a date to anchor the temporal
   phrasing.

The biography row (`GC001`) arrived with `Date: ""` in CSV — a
biographer's text spans CJP's whole life and has no single publication
anchor.

## Decision Drivers

* **Runtime correctness**: temporal phrasing must be true or unsayable,
  never plausibly wrong.
* **Detectability of drift**: a missing date should announce itself
  loudly (`skipped_rows` in `reports/generation_report.json`),
  never get masked.
* **Reversibility**: a row skipped today should be trivially
  ingestible tomorrow once the curator agrees on a date — no migration
  step required.
* **Symmetry boundary**: the date rule is strict precisely because the
  enrichment-cell rule is permissive
  ([ADR-0012](0012-permissive-csv-enrichment-parsing.md)). The two
  rules together form a clear contract: *"corrupting metadata is OK;
  corrupting time is not."*

## Considered Options

1. **Strict — skip on missing/invalid date (chosen)** — row is logged
   and dropped; no .md or .json written.
2. **Placeholder date** — substitute a sentinel (`9999-12-31`, today's
   date, the project's start date).
3. **Type-conditional**: strict for columns/speeches, permissive for
   biographies / book chapters (date-less by nature).
4. **Soft-skip with manual override flag** —
   `--allow-undated-biography` produces the file with a flag indicating
   the date is synthetic.

## Decision Outcome

Chosen option: **Strict — skip on missing/invalid date**.

A row whose `Date` cell fails the parser is recorded in
`reports/validation_errors.log` with a precise reason and **excluded
from output**. The skip is loud in the run summary (`skipped_rows: N`
in `generation_report.json`).

### Consequences

* Good: no document can enter the corpus with a corrupted temporal
  anchor.
* Good: re-running after the curator supplies a date generates the
  missing file without any other state change.
* Good: the skip is the contract — *"corpus completeness implies
  temporal trustworthiness."*
* Bad: GC001 (biography) is currently absent from the corpus. A book
  spanning decades has no natural single date. Handled in
  [PLAN-0004](../implementation-plans/PLAN-0004-biography-gc001-ingestion.md)
  — either the curator agrees a publication / signing date, or the
  schema gets a date-range field added in a future ADR.
* Bad: if the date column gets ambient-malformed in a curation pass
  (e.g., `October 32, 2023`), the whole row drops and the file
  disappears on the next idempotent re-run. Detectable from the
  report; not silent. Acceptable.
* Neutral: `parse_date()` accepts a small set of formats
  (`%Y-%m-%d`, `%B %d, %Y`, `%b %d, %Y`, etc.). Adding a format is a
  one-line code change.

## Pros and Cons of the Options

### Strict skip (chosen)

* Good, because no false-time documents possible.
* Good, because the rule is mechanical and reversible.
* Bad, because the biography is out until its date is decided.

### Placeholder date

* Good, because the file always exists.
* Bad, because the placeholder propagates: the .md frontmatter gets
  `date: 9999-12-31`, the .json gets `year: 9999`, and the Sonnet
  composer happily emits *"as I wrote in the year 9999…"*
- Bad, because a placeholder is indistinguishable from a real date at
  runtime — failure is silent.

### Type-conditional permissive

* Good, because biographies / book chapters get through.
* Bad, because adds branching in `process_row()` — two contracts to
  reason about.
* Bad, because at runtime, the consumer of date data must also branch.
  Cleaner to handle date-less documents in a future schema (range
  fields) than to make the existing field optional.

### Soft-skip with override flag

* Good, because curator can ship date-less rows under protest.
* Bad, because the flag becomes the persistent escape hatch; the
  "strict by default" guarantee weakens over time.
* Bad, because every consumer of the `.json` would need to check an
  `is_undated` flag.

## More Information

- Implementation: `scripts/generate_corpus_files.py` `parse_date()`
  + the early-return in `process_row()`.
- Current effect: `GC001` is the only row currently skipped under
  this rule (1 of 80 inputs).
- Symmetric counterpart:
  [ADR-0012](0012-permissive-csv-enrichment-parsing.md).
- Future evolution path:
  [PLAN-0004](../implementation-plans/PLAN-0004-biography-gc001-ingestion.md)
  proposes either a curator-decided date or a `date_range` schema
  field. The escape hatch lives in the plan, not the code.
