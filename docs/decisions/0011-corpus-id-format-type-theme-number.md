# ADR-0011: Corpus ID format — `{Type}{Theme}{Number}`

* Status: accepted
* Date: 2026-05-26
* Deciders: Janet

## Context and Problem Statement

The Phase 1 corpus generator (`scripts/generate_corpus_files.py`) emits
one `.md` + `.json` pair per source document under
`corpus/{speeches,columns,biography}/{theme_folder}/`. We need a stable
identifier for each document that:

1. Survives migration to disk, to JSON keys, to router prompts.
2. Is meaningful enough that the router (and a human operator) can read
   it without consulting a side table.
3. Encodes the type / theme / source-number triple unambiguously and
   matches a strict regex so validators can fail loudly.

The earlier 89-doc pipeline used opaque IDs like `col_2023_1023` and
`book_01_ch03`. Those were date-bound and book-position-bound, which
broke when documents were re-curated or republished.

## Decision Drivers

* **Self-describing**: a glance at `SE001` should tell the reader
  *speech, theme E (current events), number 001* — no lookup required.
* **Strict validation surface**: a regex check is cheaper and stronger
  than fuzzy matching during ingestion.
* **Filesystem-friendly**: must be safe as a filename stem and JSON
  key; no separators, no spaces, no Unicode.
* **Stable under re-curation**: the ID should not change when a
  document's date, title, or theme label changes.
* **Backward-compatible exit ramp**: if a document later genuinely
  changes theme (e.g., a column we thought was Theme C turns out to be
  Theme A), the cost of renaming is acceptable — explicit and
  inspectable.

## Considered Options

1. **`{Type}{Theme}{Number}` (chosen)** — single uppercase letter for
   type (`S` / `C` / `G`), single uppercase letter for theme (`A`-`E`),
   zero-padded 3-digit number. Regex `^[SCG][A-E]\d+$`.
2. **Opaque IDs** like `col_2023_1023` — date-stamped, source-position
   appended.
3. **UUIDs** — `550e8400-e29b-41d4-a716-446655440000`.
4. **Title-slug IDs** — `let-the-rule-of-law-reign-in-asean`.

## Decision Outcome

Chosen option: **`{Type}{Theme}{Number}`**.

The ID is itself the routing primitive. A topic-router decision like
*"this question is about ICC jurisdiction → route to docs `CA003`,
`CC003`, `SE003`"* is intelligible without dereferencing a side table.
The regex `^[SCG][A-E]\d+$` is validated at ingestion, so a malformed
`Article Code` in a CSV row fails the row with a precise reason.

The CSV's `Page` field — used in earlier drafts — is **dropped**: the
ID already carries the type and number, so a redundant `page` field
would be a second source of truth liable to drift.

### Consequences

* Good: human-inspectable. An operator reading `route_question` output
  in the dashboard sees *"primary topic: rule_of_law; docs: SA136,
  CA001, CA007"* and immediately knows: a Theme-A speech, a Theme-A
  column, a Theme-A column.
* Good: regex check at ingest catches data-entry typos (`GCO01`,
  `CA01`) before they propagate.
* Good: filenames map 1:1 to IDs — `SA136.md`, `SA136.json`,
  `SA136.txt`.
* Bad: if a document genuinely changes theme post-publication, the
  rename is a corpus-level migration (rare; acceptable cost).
* Bad: forces the curator to commit to a single theme per document.
  Multi-theme docs are routed via `topic_paths` (multiple topics, one
  doc) — see [ADR-0015](0015-topic-paths-derivation-rules.md).
* Neutral: implies a normalisation step at ingest — the generator
  applies `normalize_article_code()` to coerce common typos
  (`O`→`0`, zero-pad to 3 digits, uppercase). See
  [LL-010](../lessons/LL-010-article-code-typos-and-padding.md).

## Pros and Cons of the Options

### `{Type}{Theme}{Number}` (chosen)

* Good, because self-describing and short (5-6 chars).
* Good, because regex-validatable.
* Good, because filename = ID.
* Bad, because theme drift requires renaming.

### Opaque IDs (e.g., `col_2023_1023`)

* Good, because they encode the publication date.
* Bad, because they don't encode the theme — routing needs a side table.
* Bad, because re-curation breaks the ID if a date is corrected.
* Bad, because longer (16+ chars) and noisier in router output.

### UUIDs

* Good, because globally unique with no collision risk.
* Bad, because they say nothing — *every* lookup needs a side table.
* Bad, because router output becomes unreadable to a human operator.

### Title-slug IDs

* Good, because human-readable.
* Bad, because long, unstable under title revision.
* Bad, because regex validation is impossible — every title is unique.

## More Information

- Format documented in [PROJECT.md](../../PROJECT.md) §4.
- Normalisation logic: `scripts/generate_corpus_files.py`
  `normalize_article_code()`.
- Skipped/normalised IDs are logged in
  `reports/validation_errors.log`.
- Related: [LL-010](../lessons/LL-010-article-code-typos-and-padding.md)
  on the typo-tolerance normalisation step.
