# LL-011: A4 (JMSU) smoke routed to `supreme_court_history` instead of `eez_resource_sovereignty`

* Date: 2026-05-26
* Severity: low (1 of 25 in-corpus routing misses; system YELLOW, not RED)
* Related: [LL-009](LL-009-substring-matching-overbroad.md),
  [ADR-0015](../decisions/0015-topic-paths-derivation-rules.md),
  [PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md)

## Symptom

The TS-006 smoke test, question A4:

> *"Why did the Supreme Court void the JMSU agreement?"*

Expected primary ∈ `{eez_resource_sovereignty,
international_law_disputes, constitutional_doctrine}`.

Actual primary: `supreme_court_history` with secondaries
`[constitutional_doctrine, judicial_activism_and_political_question]`.

Router reasoning: *"Question concerns a specific SC decision; lacks
doctrinal anchor to map cleanly onto CJP's corpus themes."*

## 5 Whys

1. **Why did Haiku pick `supreme_court_history`?** The phrase
   *"Supreme Court void"* triggered the topic's institutional matchers
   (the topic now claims 33 of 79 docs — 42% of corpus).
2. **Why does `supreme_court_history` claim 42% of the corpus?**
   Because its matchers — even after tightening per LL-009 — still
   include high-frequency terms (`panganiban court`, `ponente`,
   `ponencia`, `21st chief justice`) that legitimately appear in many
   documents about the SC.
3. **Why didn't the matcher-health diagnostic prevent this?** The
   over-broad warning DID fire on `supreme_court_history` (32% over
   the 25% threshold). The diagnostic surfaced the problem; we
   haven't yet acted on it. PLAN-0007 §3c describes the tightening
   workflow.
4. **Why didn't `eez_resource_sovereignty` win?** Its matchers
   (`full control and supervision`, `60-40`, `regalian doctrine`,
   `joint development`, `memorandum of understanding`, `mou with
   china`) require the user to use specific vocabulary that A4 does
   not — A4 says *"JMSU"* but none of those phrases. The router
   would have to *infer* the topic from JMSU alone.
5. **Why is JMSU not a matcher in any topic?** Because the term is
   used as an entity (Joint Marine Seismic Undertaking) in
   `international_law_disputes` but only as a `keywords` term —
   which the router consumes from the topic definition, not as a
   word-boundary trigger that Haiku would pattern-match.

## Root Cause

`supreme_court_history` is still over-broad relative to its
specificity-targeted siblings. Topics with broader matchers
out-compete topics with narrower matchers on questions that mention
the broader topic's tokens — even when the narrower topic is the
better doctrinal fit.

The matcher-health diagnostic surfaces this; the curator workflow
(PLAN-0007) is the response — but neither has been applied to this
specific over-broad topic yet.

## Fix Recommended (NOT applied)

Per PLAN-0007 §3c, tighten `supreme_court_history`:

- Drop `panganiban court` (already specific enough on its own — but
  fires on many DOC summaries that just mention the era).
- Drop `ponente` and `ponencia` (they're case-doctrine markers, not
  institutional-history markers).
- Add `JMSU` as a matcher term to `eez_resource_sovereignty`
  (and ideally `arbitral award` as a stronger anchor in
  `international_law_disputes`).
- Add `void`, `ruling voids`, or `nullification` patterns to
  `international_law_disputes` to catch outcome-focused questions.

Followed up via a curator pass; verified by re-running
`scripts/run_smoke_test.py --filter A4`.

## Generalizable Lesson

A smoke test's *routing-miss anatomy* is more informative than its
overall pass rate. When a miss happens:

1. Look at the Haiku reasoning string — it tells you *why* the
   router picked what it did, in its own words.
2. Compare matcher coverage between the actual and expected primary
   topics. The matcher-health diagnostic (PLAN-0007 §4) is the
   right artefact to consult.
3. Ask whether the user's natural vocabulary matches the expected
   topic's matchers. If not, the matcher list needs to expand to
   include the user-natural terms.

In a system like this, the router is not "wrong" — it's faithfully
executing the matcher rules. Misses are evidence that the rules
under-cover real user vocabulary. The fix is matcher curation, not
router prompt engineering.

## Bonus finding — fidelity check is doing its job

The smoke test also exposed that the fidelity check correctly
flagged sub-judice violations on three questions (A3 Duterte/ICC, E2
Israel-Gaza ICJ, S1 Sara Duterte impeachment). Each fell through to
`SAFE_OOC_FALLBACK` after a failing retry. This is the designed
PLAN-0001 §E behaviour — not a bug. Worth noting because the YELLOW
verdict overall is *not* a fidelity failure; it's a single routing
miss with the safety net catching the rest.
