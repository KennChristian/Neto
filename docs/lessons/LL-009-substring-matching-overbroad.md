# LL-009: Substring topic matching let `supreme_court_history` claim 60 of 79 documents

* Date: 2026-05-26
* Severity: high (would have made routing useless — 76% of docs share an "anchor")
* Related: [ADR-0015](../decisions/0015-topic-paths-derivation-rules.md)

## Symptom

First build of `corpus/voice/topic_map.json` reported per-topic doc
counts:

```
supreme_court_history    core      60
asean_law_association    subordinate 47
flp_donors_and_partners  subordinate 38
bar_exam_and_legal_education subordinate 34
friendships_and_civic_circles subordinate 28
early_life_sampaloc      subordinate 28
```

`supreme_court_history` claiming 60 of 79 docs (76%) makes it useless
as a routing destination — almost every question routes there.
`asean_law_association` claiming 47 was obviously absurd; ALA appears
in maybe 4 documents end-to-end.

## 5 Whys

1. **Why did `supreme_court_history` match 60 docs?** Its matchers
   included words like `"magistrate"`, `"judiciary"`, `"ponente"`,
   `"ponencia"`, `"supreme court"`, `"chief justice"` — used in
   passing across most legal columns.
2. **Why did `asean_law_association` match 47 docs?** Its matchers
   included `"ala"` as a 3-letter keyword. As a plain-substring match,
   `ala` was found inside `"Salonga"`, `"escalation"`, `"galante"`,
   `"Calamba"`, etc.
3. **Why was substring matching used?** Because the initial
   `score_topic()` implementation was a one-line
   `if kw.lower() in haystack: score += 1` — minimal and intuitive.
   Substring matching is the obvious first pass.
4. **Why was the "minimal and intuitive" pass not validated against a
   ground-truth before being declared the algorithm?** Because the
   only validation was running the build and looking at the output,
   without a deliberate "is this routing distinguishable?" check.
   Routing quality wasn't measured before the algorithm was locked in.
5. **Why was routing-distinguishability not a measurement step?**
   Because at this stage of the pipeline there was no test spec for
   matcher precision/recall. The taxonomy was treated as an artifact,
   not a hypothesis to be falsified.

## Root Cause

Substring matching has a well-known false-positive cliff for short
matcher terms, but the matcher list was authored without that
constraint in mind. The deeper miss: the matcher engine was shipped
without a `for each topic: print over-broad / under-broad warning`
diagnostic, so the failure showed up only as wrong-looking final
numbers, not as a step-level red flag.

## Fix Applied

Two changes:

1. **Word-boundary matching.** `_kw_pattern(term)` compiles
   `re.compile(r"\b" + re.escape(term) + r"\b")` once and caches.
   `score_topic()` calls `.search()` instead of `in`. `"ala"` now
   matches `"ALA Philippines"` and `"ALA General Assembly"` but not
   `"Salonga"`.
2. **Matcher term tightening.** The over-broad terms in
   `supreme_court_history` were replaced with CJP-specific markers:
   `"panganiban court"`, `"centenary of justice"`,
   `"21st chief justice"`, `"primus inter pares"`. Generic
   terms like `"magistrate"`, `"judiciary"`, `"supreme court"` were
   removed — those signals propagate via the topic's named entities
   (`CJ Alexander G. Gesmundo`, `CJ Hilario G. Davide Jr.`, `Justice
   Antonio T. Carpio`) instead.

Post-fix doc counts:

```
supreme_court_history    core      33   (down from 60 — still high but legitimate)
asean_law_association    subordinate 4   (down from 47)
bar_exam_and_legal_education subordinate 20 (down from 34)
early_life_sampaloc      subordinate 14   (down from 28)
```

Implementation: `scripts/build_topic_map.py` `_kw_pattern()` and the
revised `TAXONOMY` entries for the over-broad topics.

## Generalizable Lesson

Two rules for matcher curation:

1. **Word boundaries are not optional for short matcher terms.** Any
   matcher term of ≤4 letters that is not also a frequent English
   non-word (e.g., `"FLP"` is fine because *all* English text avoids
   it) should be wrapped in `\b` boundaries before being used as a
   matcher. Substring matching is correct only when terms are long
   enough (`"foundation for liberty and prosperity"`) that
   accidental embedding is implausible.
2. **A matcher engine ships with diagnostics, not just outputs.** A
   topic that claims more than ~25% of the corpus is almost certainly
   over-broad; a topic that claims zero docs is under-broad. The
   build script should print a per-topic coverage line and a
   `[warn] over-broad: ...` / `[warn] zero-coverage: ...` whenever
   thresholds are crossed. Adding this diagnostic to
   `scripts/build_topic_map.py` is captured in
   [PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md)
   as the "matcher health check" step.

The deeper meta-rule: when an engine produces ranked outputs (matcher
scores, retrieval results, classifier probabilities), the engine's
output by itself never proves the engine works — you also need a
distribution check (*"the top scorer should not claim more than X% of
the corpus"*) and a ground-truth spot-check. Both are cheap to author
once and pay for themselves the first time the matcher list drifts.
