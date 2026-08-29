# PLAN-0005: Book corpus addition — *A Centenary of Justice* (25 sections)

* Status: draft
* Phase: 7b
* Owner: TBD (curation + engineer)
* Depends on:
  [PLAN-0004](PLAN-0004-biography-gc001-ingestion.md) (date-handling
  precedent set there is reused here)
* Verified by:
  [TS-001](../test-specs/TS-001-corpus-generator-contract.md) for
  generator contract, plus per-book sanity checks in
  [GUIDE-reviewer.md](../guides/GUIDE-reviewer.md)
* Related ADRs:
  [0011](../decisions/0011-corpus-id-format-type-theme-number.md)
  (ID format implications for book sections),
  [0013](../decisions/0013-strict-date-validation-no-placeholders.md)

## 1. Goal

Ingest *A Centenary of Justice* (the published book authored / edited
by CJP, also referred to as the *obra maestra*) — 19 chapters, 4
appendices, front-matter, and copyright = **24-25 sections**. Each
section becomes a corpus document the runtime can route to.

The book is currently absent from this corpus. An earlier pipeline
(`corpus/analysis/topics/book_01_*.json` in the prior 89-doc
artifacts) had its own ingestion; we're not reusing those files —
they pre-date the
[ADR-0011](../decisions/0011-corpus-id-format-type-theme-number.md)
ID format.

## 2. Scope

**In scope**
1. ID convention for book sections under the
   `^[SCG][A-E]\d+$` format.
2. Source-text preparation: 24-25 `.txt` files (one per section) in
   `data/text/`, named to match their normalised IDs.
3. CSV row authoring for each section in a new
   `data/csv/cjp_book_centenary_curated.csv`.
4. Generator support for a 4th type if needed (book vs biography
   distinction — decision point in §3).
5. `topic_paths` backfill via the existing matcher engine.
6. Reviewer spot-check pass.

**Out of scope**
- Embedding audit of the expanded corpus
  ([PLAN-0003](PLAN-0003-embedding-audit-offline.md)).
- Multi-book ingestion (this plan covers exactly *A Centenary of
  Justice*; the *With Due Respect* book series is a separate plan).

## 3. Key decision — Book section ID convention

The current type-letter set is `S` (speech), `C` (column), `G`
(biography). A book chapter doesn't fit cleanly.

Three options:

1. **Use `G` (biography/general) for book sections.** Treats books
   as a kind of long-form authored work alongside biographies.
   IDs like `GA001` for a Theme-A book chapter.
2. **Introduce a new type letter `B` (book section).** IDs like
   `BA001`, `BA002`, ...
3. **Treat each book section as a *speech* or *column* by content
   type** — e.g., the *Estrada v. Desierto* chapter is essentially a
   long-form column → `C` type with a 3-digit number in a reserved
   range (e.g., `CA901`-`CA999`).

Open question: which encoding is least disruptive long-term?

**Recommendation: Option 2** — introduce `B` as a new type letter.
The `^[SCG][A-E]\d+$` regex becomes `^[SCGB][A-E]\d+$`. Generator's
`TYPE_FOLDERS` / `TYPE_LABELS` get a `"B"` entry mapping to a new
`corpus/books/` directory. Cleanest separation; no namespace
collisions; obvious provenance.

This change is **schema-affecting** and warrants a new ADR
(`ADR-0017+`) before implementation.

## 4. Workstream A — ADR + schema migration

1. Author new ADR documenting the type-letter extension (`B` → book
   section).
2. Update `scripts/generate_corpus_files.py`:
   - Extend `TYPE_FOLDERS` and `TYPE_LABELS` with `B`.
   - Extend `ID_REGEX`.
   - Add a `corpus/books/` directory tree mirroring the existing
     `corpus/columns/` per-theme folders.
3. Update `corpus/voice/topic_map.json` builder to recognise the new
   type in stats.
4. Update [PROJECT.md](../../PROJECT.md) §4 (ID convention) and §7
   (directory layout) with the new type.

## 5. Workstream B — Source text preparation

Each section gets a `.txt` file in `data/text/`. Section IDs
(under Option 2 above):

| Section | Likely theme | ID |
|---|---|---|
| Front-matter | A | `BA001` |
| Ch.01 *A Renaissance in the Judiciary* | A | `BA002` |
| Ch.02 *Old Doctrines and New Paradigms* | A | `BA003` |
| Ch.03 *Obra Maestra* | A | `BA004` |
| Ch.04 *The Centenary and the Academe* | A | `BA005` |
| Ch.05 *Mediation* | A | `BA006` |
| Ch.06 *A Meaningful Centenary* | A | `BA007` |
| Ch.07 *Employee Participation* | A | `BA008` |
| Ch.08 *The Inspiration of the Judiciary* | A | `BA009` |
| Ch.09 *Benchbook for Judicial Excellence* | A | `BA010` |
| Ch.10 *Ready for the Bio Age* | A | `BA011` |
| Ch.11 *E-Values for Lawyers* | A | `BA012` |
| Ch.12 *Even the SC Needs Public Relations* | A | `BA013` |
| Ch.13 *Estrada v. Desierto* | A | `BA014` |
| Ch.14 *Death Penalty Cases* | A | `BA015` |
| Ch.15 *Cruz v. Sec. of Environment (IPRA)* | A | `BA016` |
| Ch.16 *Ang Bagong Bayani* | A | `BA017` |
| Ch.17 *Perez v. Estrada* (live coverage) | A | `BA018` |
| Ch.18 *Firestone Ceramics* | A | `BA019` |
| Ch.19 *Bengson* (citizenship repatriation) | A | `BA020` |
| Appendix A *Salute to My Mentor* | C | `BC001` |
| Appendix B *Justice Is God's Work* | C | `BC002` |
| Appendix C *Prelude to Paperless Courts* | A | `BA021` |
| Appendix D *MPGR* | A | `BA022` |

(Theme assignments above are guesses pending curator review.
Appendix A and B obviously personal → Theme C; the rest plausibly
Theme A by content.)

## 6. Workstream C — Curator authoring

For each section, the curator authors a CSV row in
`data/csv/cjp_book_centenary_curated.csv` matching the 15-column
schema (same as columns). The book's publication date applies to
every section; CJP's lead author / editor role is documented in the
ADR.

Provenance note in each `.txt`: confirm the section came from the
canonical 2002 / 2006 / whatever edition of the book. The book has
multiple printings; pin the source.

## 7. Workstream D — Generation + topic_paths

After CSV + .txt files are in place, run the standard pipeline:

```
python scripts/generate_corpus_files.py --with-topic-paths
```

Expected results:
- 24-25 new `corpus/books/{theme}/BX###.{md,json}` files.
- `corpus/voice/topic_map.json` regenerated with expanded
  `doc_count` per topic — every existing matcher's coverage may
  grow.
- Some topics that currently have 1-2 docs (e.g.,
  `death_penalty_and_echegaray`) may suddenly have 3-5 — a positive
  signal that the corpus is more reflective of CJP's published
  emphasis.

## 8. Workstream E — Routing-quality follow-up

The book is highly doctrinal. Adding 22+ Theme-A book chapters at
once *will* shift the corpus's centre of mass:

- Topic `supreme_court_history` (current count 33) might rise to
  55+. If it crosses ~50%, file a [PLAN-0007](PLAN-0007-topic-map-evolution-process.md)
  taxonomy edit to split it.
- Topic `judicial_reform` may need sub-topics for the chapter-level
  themes (e.g., `four_ins_doctrine`, `acid_problems_specifically`).
- New topics may appear (e.g., `mediation_alternative_dispute`,
  `judicial_public_relations`, `bio_age_technology`) — book sections
  are book-shaped and the existing 35-topic taxonomy was authored
  before they were ingested.

Treat this as an iterative pass:
1. Ingest the book.
2. Run matcher health check (per PLAN-0007 §"Matcher diagnostics").
3. Identify topics now over-broad / new topics needed.
4. Edit `TAXONOMY` in `build_topic_map.py`.
5. Re-run `--with-topic-paths`.

## 9. Failure modes

| Failure mode | Detection | Response |
|---|---|---|
| New type-letter `B` regression in normalisation | Generator tests | Update test spec |
| Book section IDs collide with existing IDs | Build-time uniqueness check | Renumber per curator |
| Section dates resolve to book publication year, not section authorship year | Reviewer spot-check | Document decision in book-ingest ADR; consider per-section overrides |
| Body bodies are exceptionally long (book chapters are 5,000+ words) | Token-budget check at retrieval | Sonnet composer may need a per-chapter summary field; surface as new PLAN |

## 10. Edge cases

- **A chapter splits across themes** (legal analysis + personal
  reflection). Resolution: pick the dominant theme; let the
  `topic_paths.secondary` carry the other.
- **Appendices share material with columns already ingested.**
  Resolution: ingest both; let `topic_paths` route to both copies.
  The composer will deduplicate based on overlapping content; this
  is a known runtime concern.
- **A chapter cites a 2026 Supreme Court ruling** (i.e., is updated
  in a new edition). Resolution: pin the `date` to the edition's
  publication date.

## 11. Acceptance

- 24-25 `.md` + `.json` pairs in `corpus/books/`.
- Every section ID matches `^[SCGB][A-E]\d+$`.
- `corpus/voice/topic_map.json` regenerated; no topic claims >50% of
  total corpus.
- Six build-kit sanity questions still route correctly; at least one
  routes to include a book chapter in the context block.

## 12. Out-of-scope discoveries to surface

- *With Due Respect I, II, III* book series is a separate plan.
- If the book ingest motivates a 36th topic or splits an existing
  one, file via [PLAN-0007](PLAN-0007-topic-map-evolution-process.md).
- Voice-card adjustments may be needed if the book's authorial voice
  is subtly distinct from the column voice (the book has chapter
  intros that read more formally than columns).
