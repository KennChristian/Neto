# PLAN-0004: Biography `GC001` ingestion — resolve the date question, ingest, route

* Status: draft
* Phase: 7a
* Owner: TBD (curation), with engineer support
* Depends on: Phase 1 complete; curator + project lead agreement on
  the date resolution path
* Verified by:
  [TS-001](../test-specs/TS-001-corpus-generator-contract.md) once a
  date is supplied
* Related ADRs:
  [0013](../decisions/0013-strict-date-validation-no-placeholders.md)
  (why GC001 is currently skipped)

## 1. Goal

Bring `GC001` (*"Liberty and Prosperity: The Making of Chief Justice
Artemio Villaseñor Panganiban Jr."*, by Reginald T. Yu) into the
corpus. Currently the row in `data/csv/cjp_biography_curated.csv`
has an empty `Date` cell, and the strict date rule
([ADR-0013](../decisions/0013-strict-date-validation-no-placeholders.md))
skips it.

## 2. Three resolution paths (decision pending)

Option A — **Pick a single anchor date.** Curator agrees on one of:
- Manuscript completion date
- Manuscript signing date (Reginald T. Yu's hand-off)
- Project intake date (when the biography was committed to the FLP
  corpus pipeline)
- Date of CJP's 75th birthday (Dec 7, 2011 — FLP's founding day —
  rhetorically natural)

Option B — **Extend the schema with a `date_range`.** Author a new
ADR introducing `date_range: [earliest, latest]` as an alternative
to `date`. Books and multi-decade biographies use the range; columns
and speeches keep the single date. Runtime composer treats range as
"this work was written between X and Y" rather than a single anchor.

Option C — **Treat biographies as a third schema type** with no
date field at all, just `year_of_subject_range` (covering CJP's
lifespan). Removes the temporal anchor altogether for biographies;
the composer never says "as I wrote in 19xx" for biography sources.

## 3. Recommendation

**Start with Option A** (manuscript completion date). It is the
cheapest, requires no schema or runtime change, and is in keeping
with the "single anchor per document" rule that the rest of the
corpus uses.

If A is rejected by the curator on grounds that no single date is
accurate, escalate to Option B with a new ADR.

## 4. Workstream A — Date acquisition (curator)

1. Curator (with project lead) decides on a single date.
2. Update `data/csv/cjp_biography_curated.csv` row for `GCO01` —
   also fix the typo `GCO01` → `GC001`
   ([LL-010](../lessons/LL-010-article-code-typos-and-padding.md))
   if the normalisation isn't going to do it (the generator's
   normaliser will handle it; the CSV can stay `GCO01`).
3. Add a `provenance_note` line documenting the date choice in
   `data/text/GC001.txt`'s header block (the file's `Date:` line
   currently reads `[Not specified]`).

## 5. Workstream B — Generation

Re-run:

```
python scripts/generate_corpus_files.py --with-topic-paths
```

The biography row now generates:
- `corpus/biography/C_biographical_personal/GC001.md`
- `corpus/biography/C_biographical_personal/GC001.json`

`topic_paths` gets populated by `apply_topic_paths.py`. Given the
biography's content (life arc, faith journey, family, mentors,
constitutional rescue moments at EDSA 2, post-judicial FLP work),
expected primary topics:
- `family_and_marriage` and/or `mentors_and_legal_lineage` and/or
  `faith_journey` are likely candidates.

If the doc has unusually high keyword density that triggers ≥5
topic hits, consider whether a *biography-specific* threshold tweak
is warranted — captured in
[PLAN-0007](PLAN-0007-topic-map-evolution-process.md) as a "biography
ingest follow-up" item.

## 6. Workstream C — Routing validation

After ingest, run the spot-check from
[GUIDE-reviewer.md](../guides/GUIDE-reviewer.md) §"Validating
topic_paths on a new document":

1. Read GC001's `topic_paths.primary` + `.secondary`.
2. Confirm each routed topic is *evidenced* in the biography body.
3. Spot-check: ask the router a biography-anchored question (e.g.,
   *"What did Salonga say to you before the 1960 bar exam?"*); does
   the router include `GC001` in its top 3 docs?

## 7. Failure modes

| Failure mode | Detection | Response |
|---|---|---|
| Date still unset after Workstream A | Re-run skips it | Curator escalates to Option B (`date_range` ADR) |
| Generated body still has the `Date: [Not specified]` header text leaking through normalisation | Manual inspection | Add `[Not specified]` to the header-key regex in `normalize_body()` — small follow-up issue |
| `topic_paths.primary` empty after backfill | `apply_topic_paths.py` warns | Strengthen taxonomy matchers for biographies (PLAN-0007) |
| Biography touches a topic with no current matcher coverage (e.g., `judicial_compensation`) | Reviewer spot-check | File new topic via PLAN-0007 process |

## 8. Edge cases

- **Biographer adds a 2nd volume later.** The second volume's `id`
  would be `GC002` (or theme-different `GA001` if it covers Theme A
  topics in depth). Theme-letter choice is a curator decision.
- **Biography is published commercially with an ISBN.** The
  `source_url` field could point to the publisher page or remain
  empty; either is acceptable per current schema.
- **Body contains long verbatim quotes from CJP's own speeches.** The
  voice card's "Never invent quotes" rule
  ([voice_card.md](../../corpus/voice/voice_card.md) §"Out-of-corpus
  reasoning policy") covers this — the composer will quote the
  biography's verbatim CJP material if and only if it appears in the
  context block.

## 9. Acceptance

- `data/csv/cjp_biography_curated.csv` has a non-empty, parseable
  `Date`.
- `corpus/biography/C_biographical_personal/GC001.md` and `.json`
  exist with valid frontmatter and at least one primary topic_path.
- `reports/generation_report.json` shows `successful_generations:
  80, skipped_rows: 0`.
- A biography-anchored question routes to include `GC001` in the
  context block.

## 10. Out-of-scope discoveries to surface

- If the date choice surfaces an interesting principle ("which date
  do we use when there isn't one?"), file a new ADR. The decision
  isn't only about GC001 — it sets precedent for book chapters
  ([PLAN-0005](PLAN-0005-book-corpus-addition.md)).
