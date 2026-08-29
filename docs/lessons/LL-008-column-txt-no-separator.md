# LL-008: Column `.txt` files have no `---` block separator; body normaliser left header lines in the body

* Date: 2026-05-26
* Severity: moderate (every column .md had its body polluted with header lines)

## Symptom

After the first generation run, spot-checking
`corpus/columns/A_liberty_rule_of_law/CA001.md` showed the body
section starting with leftover metadata lines:

```markdown
# Let the rule of law reign in Asean

Let the rule of law reign in Asean
Date:       2023-10-23
Publisher:  Philippine Daily Inquirer (Inquirer Opinion)
Source:     https://opinion.inquirer.net/167388/let-the-rule-of-law-reign-in-asean

By: Artemio V. Panganiban | 04:30 AM October 23, 2023
This column is a shortened version of the address I delivered ...
```

The title and four header lines appeared duplicated as body content
immediately after the `#`-prefixed canonical title. Every column was
affected; speeches were clean.

## 5 Whys

1. **Why did the column bodies still contain header lines?** Because
   the `normalize_body()` function split on `^---\s*$` and returned
   everything after that line. Columns have no `---` line.
2. **Why do columns have no `---` separator when speeches do?** Because
   the two source-text conventions evolved separately: speech `.txt`
   files were extracted from `cjpanganiban.com` and follow a
   "metadata block, `---`, body" template; column `.txt` files were
   extracted from the *Inquirer* archive and follow a "metadata
   key:value lines, blank, body" template.
3. **Why did the normaliser assume a single template?** Because the
   first three documents I read by hand to design the function
   (`SA136.txt`, `CA001.txt`, `GC001.txt`) happened to have the `---`
   only on speeches, but the regression in the column output looked
   identical to the input — easy to miss in a 245-file run.
4. **Why was the assumption not caught at build time?** Because the
   generator emits 79 `.md` files in a single run with no per-file
   review step. Visual inspection was reserved for an opening sample,
   which used a speech (`SA136.md`) — the clean one.
5. **Why did manual sanity checking land on a clean sample first?**
   Because the speech file was the worked example used in
   [PROJECT.md](../../PROJECT.md) §7, which set the reviewer's
   mental model. Columns weren't inspected until after they'd been
   committed for review.

## Root Cause

A single-template assumption was baked into `normalize_body()` from
inspection of a small biased sample. The biased sample happened to
miss the document-type heterogeneity between speeches and columns.

## Fix Applied

`normalize_body()` now handles both formats:

- If a `^---\s*$` separator line is present (speech / biography
  convention), split on it and return everything after.
- Otherwise (column convention), walk the leading lines: skip blank
  lines, skip an optional title line that matches the supplied
  `title` argument, then consume `^(Date|Publisher|Source|By|Title|
  Author|Venue|Occasion)\s*:` header lines until the first non-header
  non-blank line. Body starts there.

The `title=` argument was added to `normalize_body()` and threaded
through `process_row()`. Implementation: `scripts/generate_corpus_files.py`
`normalize_body()` and `_HEADER_KEY_RE` constant.

After the fix, `CA001.md` body starts with *"This column is a
shortened version of the address I delivered..."*, exactly as
intended.

## Generalizable Lesson

When designing a parser/normaliser to handle multiple document types,
**read at least one example of every type before writing the function**,
not just "a few." The variance you have to handle is in the *cross-type*
diff, which can hide entirely inside a uniform-looking single-type
sample.

Two operational rules:

1. **Type-stratified sampling.** Pick samples by stratum (one column,
   one speech, one biography, one of every type you ingest) before
   designing any text-cleaning step. The strata themselves are the
   variance source.
2. **Spot-check across all strata after running.** The first 3-5
   files generated for each document type, opened side-by-side, will
   surface this class of bug in 30 seconds. A cross-stratum sanity
   check is cheaper than the bug it catches.

For generators that emit many files at once, a useful pattern is to
emit a "first-of-each-stratum sample" summary at the top of the run:

```
[sample] SA015.md (first speech, theme A): body begins with "..."
[sample] CA001.md (first column, theme A): body begins with "..."
[sample] GC001.md (biography):            body begins with "..."
```

That output is glance-checkable and would have surfaced this miss.
Adding a deterministic sample line to the generator's run output is a
small future improvement; it appears in
[PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md)
as a related rebuild-output hygiene item.
