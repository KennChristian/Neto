# LL-010: Article codes inconsistent across CSVs — `CA01` vs `CA001`, `GCO01` for `GC001`

* Date: 2026-05-26
* Severity: low (caught at ingest; tolerated by normaliser)
* Related: [ADR-0011](../decisions/0011-corpus-id-format-type-theme-number.md)

## Symptom

First dry-run of the corpus generator reported that the columns CSV
used 2-digit codes (`CA01`, `CA02`, ... `CE08`) while the speeches
CSV used 3-digit codes (`SE001`, `SD002`, ... `SA136`) and the
biography CSV used `GCO01`. The `.txt` files in `data/text/` all used
3-digit codes (`CA001.txt`, `GC001.txt`).

Two failure modes were present:

1. **Width drift.** Columns: 2 digits in CSV vs 3 digits in filenames.
2. **Typo.** Biography: `GCO01` in CSV vs `GC001` in filename (an `O`
   letter where a `0` digit belonged).

Without normalisation, the generator would have failed to match any
column CSV row to its `.txt` source, and would have rejected the
biography row outright because `GCO01` does not match
`^[SCG][A-E]\d+$`.

## 5 Whys

1. **Why are column codes 2-digit and speech codes 3-digit in the
   source CSVs?** Because they were curated in separate sessions:
   columns started small and the curator chose 2-digit padding to keep
   cells compact; speeches were authored after `SA136` was conceived
   (where 3 digits are required), so the convention was
   3-digit from the start.
2. **Why was the biography code `GCO01` instead of `GC001`?** A
   typo: the curator typed an `O` instead of a `0`. The cell was
   never visually validated against a regex.
3. **Why did the validation only catch this at generator-run time?**
   Because no pre-ingestion validator existed. The CSVs were authored
   in one tool (spreadsheet), the generator was in another tool, and
   no validation step bridged them.
4. **Why was a pre-ingestion validator not authored?** Because the
   generator itself runs cheaply (~5 seconds for 80 rows), so the
   feedback loop is *"author CSV → run generator → read
   validation_errors.log"*. The generator's per-row validator was
   considered sufficient.
5. **Why did the generator's per-row validator solve this instead of
   rejecting it?** Because tolerating common typos and padding
   inconsistencies at ingest is a much smaller user-impact than
   forcing the curator to fix every typo before any row generates.
   The normalisation step was added to bridge the gap.

## Root Cause

The CSV authoring step and the schema-validating step are owned by
different humans / tools / curation sessions, and the *width* and
*letter-vs-digit* conventions drifted across those sessions. The
schema spec exists, but no shared validator runs as part of
authoring.

This is the structural seam between *authoring* and *consuming* the
CSV. As long as authoring uses a spreadsheet (no inline schema check)
and consuming uses a regex-strict generator, drift will happen.

## Fix Applied

`normalize_article_code()` in `scripts/generate_corpus_files.py`
applies the following coercions before validating:

```python
code = raw.strip().upper()                  # whitespace, casing
type_letter, theme_letter, tail = code[0], code[1], code[2:]
if type_letter not in TYPE_FOLDERS or theme_letter not in THEME_LABELS:
    return None
tail_fixed = tail.replace("O", "0")          # letter-O → digit-0
if not tail_fixed.isdigit():
    return None
number = int(tail_fixed)
if number <= 0:
    return None
width = max(3, len(tail_fixed))              # ≥3-digit zero-pad
return f"{type_letter}{theme_letter}{number:0{width}d}"
```

This accepts `CA01`, `CA001`, `ca01`, `Ca001`, `GCO01`, `GC001`,
`gc1`, etc., and normalises them all to the canonical 3+-digit
uppercase form. The output is what gets validated against
`^[SCG][A-E]\d+$`.

Filenames in `corpus/columns/` and `corpus/speeches/` are written
using the *normalised* ID, so on disk everything is uniform.

## Generalizable Lesson

When a schema crosses an authoring/consuming seam where the authoring
tool is human-friendly (spreadsheet, prose, Notion) and the consuming
tool is regex-strict (Python, JSON Schema, code), assume:

1. **Width and zero-padding will drift.** Three different curators
   will use three different widths.
2. **Letter-digit substitutions will appear.** `O`↔`0`, `l`↔`1`,
   `I`↔`1`, `5`↔`S`. Spreadsheet font choices make these worse.
3. **Case will be inconsistent.** Lower-case slips in routinely.
4. **Trailing whitespace will appear.** Anywhere a curator might
   double-click to select a cell.

Build a normaliser at the seam — at the consumer's input boundary —
that absorbs each of these four pre-validated. Normalise first;
validate second. The normaliser is the seam's anti-corrosion coat;
the validator confirms the coat held.

Log every normalisation that *actually changed* the input string, so
the curator gets a feedback signal:

```
INFO  CA01 → CA001     (zero-padded)
INFO  GCO01 → GC001    (O→0 substitution)
```

Currently the generator silently normalises without logging the
specific transform. Adding a per-row "normalisation diff" line to the
verbose run output is a small future improvement, captured as a
rebuild-output hygiene item in
[PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md).
