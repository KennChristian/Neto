# PLAN-0007: Topic Map evolution process — how to add, retire, and tighten topics safely

* Status: diagnostics implemented (§4 + §5); process documented
* Phase: cross-cutting (always-on, applies whenever the corpus or
  taxonomy changes)
* Owner: curator + engineer (paired)
* Depends on: Phases 1-3 complete
* Verified by:
  [TS-002](../test-specs/TS-002-topic-map-matchers.md),
  [TS-003](../test-specs/TS-003-topic-paths-derivation.md)
* Related ADRs:
  [0011](../decisions/0011-corpus-id-format-type-theme-number.md),
  [0014](../decisions/0014-hand-curated-taxonomy-in-python-code.md),
  [0015](../decisions/0015-topic-paths-derivation-rules.md),
  [0016](../decisions/0016-theme-anchored-register-selection.md)

## 1. Goal

Define the standing process for evolving the hand-curated taxonomy
in `scripts/build_topic_map.py` and `corpus/voice/topic_map.json` as
the corpus grows or routing experience reveals gaps.

This is a **process plan**, not a feature plan. It is referenced by
every corpus-growing plan ([PLAN-0004](PLAN-0004-biography-gc001-ingestion.md),
[PLAN-0005](PLAN-0005-book-corpus-addition.md)) and by
[GUIDE-admin.md](../guides/GUIDE-admin.md).

## 2. Five operations on the taxonomy

Every taxonomy change falls into one of:

1. **Add a topic.** New subject area surfaces that didn't exist
   before.
2. **Retire a topic.** Topic has 0 docs and no plausible future docs.
3. **Tighten a matcher.** Existing topic is over-broad (claims too
   many docs).
4. **Loosen a matcher.** Existing topic is under-broad (claims too
   few docs).
5. **Split / merge topics.** One topic should be two, or two should
   be one.

Each operation has its own pre-conditions and verification.

## 3. Operation playbook

### 3a. Add a topic

**Pre-conditions:**
- At least 2 docs in the corpus genuinely belong to it
- Topic has ≥2 distinct matcher terms that don't trigger ≥30% of
  the corpus (see §4 matcher health check)
- Theme anchor and default register decided (default: inherit from
  the chosen theme; override only with rationale)

**Steps:**
1. Add a new entry to `TAXONOMY` list in `scripts/build_topic_map.py`
   in the appropriate theme block.
2. Author the entry's fields: `id`, `display_name`, `definition`,
   `tier`, `theme_anchor`, `matchers.keywords`, `matchers.entities`.
3. Run `python scripts/build_topic_map.py`.
4. Inspect `reports/topic_map_report.json` for the new topic's
   coverage.
5. Run `python scripts/apply_topic_paths.py`.
6. Spot-check 3 docs that should route to the new topic — they
   should appear in its `doc_ids`.

**Acceptance:** new topic has 2-15 docs and no doc has its `primary`
overridden in a way the curator did not expect.

### 3b. Retire a topic

**Pre-conditions:**
- Topic has 0 docs.
- Curator confirms no future docs are expected (e.g., the topic was
  speculative).

**Steps:**
1. Delete the entry from `TAXONOMY`.
2. Run build + apply scripts.
3. Confirm no doc previously routed there (would be empty for a
   zero-doc topic anyway).

**Acceptance:** topic absent from `corpus/voice/topic_map.json`.

### 3c. Tighten a matcher

**Trigger:** topic claims >25% of corpus, or routing experience
shows it as primary destination for unrelated questions.

**Steps:**
1. Inspect the topic's `top_signature_phrases` and `doc_ids` in
   `topic_map.json` to identify which matchers are firing on
   tangential docs.
2. Remove or replace over-broad terms (short generic words like
   *"judiciary"*, *"law"*).
3. Add CJP-specific markers if available
   (*"Panganiban Court"*, *"twin and inseparable"*).
4. Re-run build + apply.
5. Confirm doc count drops to the expected range.

**Acceptance:** doc count in expected range; no relevant doc lost.

### 3d. Loosen a matcher

**Trigger:** topic claims <2 docs (or 0) but curator believes more
exist.

**Steps:**
1. Spot-check 5 docs the curator expects to route there.
2. For each, identify the term that *should* have matched but
   didn't (often a phrase variation: *"climate change"* vs
   *"climate crisis"*).
3. Add the variant(s) to `matchers.keywords`.
4. Re-run build + apply.

**Acceptance:** doc count rises to the expected range without
exceeding 25% of corpus.

### 3e. Split / merge

**Split trigger:** topic claims 15+ docs and routing-experience
shows it conflates two distinct sub-questions.

**Merge trigger:** two topics' doc_ids overlap >70%; they are
indistinguishable.

**Steps (split):**
1. Author 2+ replacement topics with disjoint matchers.
2. Delete the original entry.
3. Re-run build + apply.
4. Confirm the original's docs are distributed across the new topics.

**Steps (merge):**
1. Merge the matcher lists of the two topics.
2. Choose the surviving topic id (or coin a new umbrella id).
3. Delete the redundant entry.
4. Re-run build + apply.

**Acceptance:** every doc previously in either topic has a
defensible new primary.

## 4. Matcher health check (diagnostic)

Add to `scripts/build_topic_map.py` an end-of-run summary that flags:

- Topics with `doc_count == 0` — *zero-coverage* warning.
- Topics with `doc_count > 0.25 * n_docs` — *over-broad* warning.
- Topic pairs whose `doc_ids` overlap > 50% — *near-duplicate*
  warning.
- Topics where a single matcher term is firing on >80% of the
  topic's docs — *dominant-term* warning (suggests the term is
  carrying the topic alone; risk of brittleness).

Each warning links to the §3 operation playbook.

**Implementation status: in place** (commit following this plan's draft
landing). `matcher_health_check()` in
`scripts/build_topic_map.py` evaluates all four checks at the end of
every build. Warnings are printed to stdout and stored as
`health_warnings` in `reports/topic_map_report.json`.

## 5. Rebuild output hygiene

Two diagnostic improvements that fell out of Phase 1-2 lessons —
**both implemented**:

1. **First-of-each-stratum sample** — generator prints one
   `[sample]` line per type after generation, showing the first 80
   chars of the body. Helps catch parser regressions across types
   (per [LL-008](../lessons/LL-008-column-txt-no-separator.md)).
   Implementation: `RunStats.stratum_samples` populated in
   `process_csv`; printed in the `[sample]` block at end of `main`.
2. **Article-code normalisation diff log** — when
   `normalize_article_code()` actually changes the input, an
   `INFO normalised Article Code: CA01 → CA001` line is appended
   to `reports/validation_errors.log` (per
   [LL-010](../lessons/LL-010-article-code-typos-and-padding.md)).
   Implementation: the diff is detected immediately after the
   normaliser call in `process_row()`.

These are *generator* improvements, not topic-map. Captured here
because the curator's loop benefits.

## 6. Versioning / change tracking

Every taxonomy edit is a git commit. Suggested commit message
template:

```
chore(taxonomy): <add|retire|tighten|loosen|split|merge> <topic_id>

Why: <one-line reason>
Doc count before → after: <X> → <Y>
Verified: scripts/build_topic_map.py + apply_topic_paths.py + spot check
```

The `corpus/voice/topic_map.json` diff in the commit makes the
effect of the change reviewable.

## 7. Failure modes

| Failure mode | Detection | Response |
|---|---|---|
| Edit breaks a doc's primary path | apply_topic_paths warns "no primary" | Revert; tighten/loosen specifically |
| Edit cascades — many docs change primary | git diff of `topic_map.json` | Review each diff; if intended, accept |
| Curator names two topics with same id | Python KeyError on build | Fix the typo |
| Matcher term contains a regex special char that wasn't escaped | `re.escape` is applied at compile; safe by construction | Verify with TS-002 §"Special characters" |

## 8. Acceptance for each taxonomy edit PR

- `python scripts/build_topic_map.py` runs without error.
- `python scripts/apply_topic_paths.py` reports 0 docs without
  primary.
- Matcher health check produces no new warnings.
- 5+ doc routings spot-checked manually.
- Commit message uses the template from §6.

## 9. Out-of-scope discoveries to surface

- **Automated regression**: a future test spec could replay a fixed
  set of routings before/after every edit and flag changes. Not
  required for v1; captured here as future work.
- **Taxonomy v2 schema**: if matcher logic evolves (weighted scoring,
  theme-conditional scoring), a new ADR records the schema bump.
