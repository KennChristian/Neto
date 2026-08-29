# TS-002: Topic map matchers — precision, recall, health

* Status: draft
* Verifies:
  [ADR-0014](../decisions/0014-hand-curated-taxonomy-in-python-code.md),
  [ADR-0015](../decisions/0015-topic-paths-derivation-rules.md),
  [ADR-0016](../decisions/0016-theme-anchored-register-selection.md)
* Subject: `scripts/build_topic_map.py` — the `TAXONOMY` list and the
  scoring engine
* Style: hybrid — given/when/then for engine invariants;
  precision/recall metric checks; matcher-health threshold checks

## 1. Model

The matcher engine is a deterministic function:

```
(doc, topic) → score : non-negative int
```

Where `score` counts the *distinct* matcher terms (keywords +
entities) that hit the doc's haystack (lowercased title + summary +
primary_topics + sub_topics + keywords + register_markers + flattened
entities).

A matcher term hits if `re.search(r"\b{escaped term}\b", haystack)`
returns non-None.

## 2. Given / When / Then — scoring invariants

### 2.1 Empty matcher list

**Given** a topic with `matchers.keywords == []` and
`matchers.entities == []`,
**When** `score_topic` is called on any doc,
**Then** the returned score is 0.

### 2.2 Single keyword, exact match

**Given** a topic with `keywords = ["arbitral award"]` and a doc
whose body contains exactly that phrase,
**When** scored,
**Then** score = 1.

### 2.3 Same matcher term appearing twice in a doc

**Given** a topic with `keywords = ["rule of law"]` and a doc with
the phrase appearing 3 times,
**When** scored,
**Then** score = 1 (distinct terms, not occurrences —
[ADR-0015](../decisions/0015-topic-paths-derivation-rules.md)).

### 2.4 Word-boundary correctness

**Given** a topic with `keywords = ["ala"]`,
**When** scored against a doc containing `"Salonga"` (which has the
substring `"alo"`),
**Then** score = 0. (Regex `\bala\b` does not match inside
`Salonga`.)

### 2.5 Case insensitive

**Given** `keywords = ["IMHO"]` and doc containing `"In My Humble
Opinion"`,
**When** scored,
**Then** score = 0 (literal match on `"imho"` only — uppercase
acronym is the matcher's intent).

### 2.6 Multiple matchers hit same doc

**Given** topic with `keywords = ["A", "B", "C"]` and doc containing
"A B" (not C),
**When** scored,
**Then** score = 2.

### 2.7 Entity match

**Given** `entities = ["Foundation for Liberty and Prosperity"]` and
doc with that name in `entities.institutions`,
**When** scored,
**Then** score includes the entity hit.

### 2.8 Special characters in matcher term

**Given** `keywords = ["section 2(2)"]` (parens, special chars),
**When** scored,
**Then** `re.escape` neutralises them; literal `"section 2(2)"`
match required.

## 3. Precision / recall over the seeded corpus

For each topic with `doc_count >= 3`, the curator authors a small
known-truth set (`golden/topic_<id>.json`) listing 3-5 docs that
**should** be primary for that topic and 3-5 docs that **should not**
be (chosen from semantically adjacent topics).

After a `build_topic_map.py` run:

- **Recall** per topic = (# golden-positive docs in `doc_ids`) /
  (# golden-positive docs in golden set)
- **Precision** per topic = (# golden-positive docs in `doc_ids`) /
  (# `doc_ids`)

Targets (initial — tune after first measurement):
- Recall ≥ 0.80 per topic.
- Precision ≥ 0.70 per topic.

This requires authoring the golden sets, which is a small curator
task and is captured in
[PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md)
§4 as "matcher health check" follow-up work.

## 4. Matcher health — distribution checks

**Implemented** in `scripts/build_topic_map.py` `matcher_health_check()`.
Runs at the end of every build; warnings are printed to stdout and
recorded under `health_warnings` in
`reports/topic_map_report.json`. Thresholds crossed:

### 4.1 Zero-coverage

**Trigger:** topic with `doc_count == 0` and not in `tier == "meta"`.
**Severity:** warn.
**Implication:** matcher list is too narrow, or the topic is
speculative. Curator decides whether to loosen (PLAN-0007 §3d) or
retire (§3b).

Currently `robot_identity_meta` has 0 docs by design — it's `tier:
"meta"`. The check is theme-conditioned.

### 4.2 Over-broad

**Trigger:** topic with `doc_count > 0.25 * n_docs` (i.e., >25% of
corpus).
**Severity:** warn.
**Implication:** matcher list is too inclusive. Curator tightens
(PLAN-0007 §3c).

Current state: `supreme_court_history` at 33/79 = 41.8% — flagged.
Trim is captured in
[LL-009](../lessons/LL-009-substring-matching-overbroad.md) §"Fix
Applied" follow-on work.

### 4.3 Near-duplicate

**Trigger:** topic pair `T1`, `T2` with `|D_T1 ∩ D_T2| / |D_T1 ∪
D_T2| > 0.7` (Jaccard).
**Severity:** warn.
**Implication:** topics are routing-indistinguishable; consider merge
(PLAN-0007 §3e) or matcher-disjoint refactor.

### 4.4 Dominant-term

**Trigger:** within a topic, ≥80% of its `doc_ids` are matched by a
single matcher term.
**Severity:** info.
**Implication:** the topic depends on one term; brittle to curator
edit.

## 5. Edge cases

| Case | Expected behavior |
|---|---|
| Matcher term is empty string `""` | Skipped at compile (regex `\b\b` matches nothing useful); no error |
| Matcher term is whitespace only | Skipped at compile |
| Doc has empty haystack (no enrichment) | Scores 0 against every topic; falls back to "promote strongest scorer" — but strongest is 0; doc has `topic_paths.primary == []`. **Important**: every doc in the current corpus has enrichment, so this is hypothetical. If a future doc shows this, the matcher health check flags it. |
| Topic has `tier: "meta"` and 0 docs | Excluded from over-broad / zero-coverage checks |
| Matcher term is exactly 3 chars and uppercase ("FLP", "ICC", "EEZ") | Word-boundary works correctly; expected to match where intended |

## 6. Determinism

**Given** the same corpus and the same `TAXONOMY` list,
**When** `build_topic_map.py` runs twice in different processes,
**Then** the `corpus/voice/topic_map.json` outputs are bit-identical
(modulo `generated_at` timestamp).

**Caveat:** `generated_at` is the only nondeterministic field;
clients comparing outputs should ignore it.

## 7. Integration with `apply_topic_paths.py`

After `build_topic_map.py` writes `topic_map.json`,
`apply_topic_paths.py` re-scores every doc and writes
`topic_paths.primary` / `.secondary` into each `.json` file.

**Invariants verified by the apply step:**

- Every doc gets a `topic_paths.primary` list, possibly empty.
- For every primary topic, the doc's id appears in that topic's
  `doc_ids` in `topic_map.json` (round-trip consistency).
- If a doc has *no* topic with score ≥ 2, the strongest scorer is
  promoted to primary (no empty primaries; per
  [ADR-0015](../decisions/0015-topic-paths-derivation-rules.md)).

## 8. Failure modes & observability

| Failure mode | Detection | Response |
|---|---|---|
| `TAXONOMY` has two entries with same `id` | Build raises on dict-key collision | Fix the duplicate id |
| Matcher term contains an unescaped regex special char | `re.escape` prevents; safe by construction | None |
| Doc has malformed `entities` (not a dict) | `_doc_haystack` skips that field | Logged; doc still scored on title + summary |
| `topic_map.json` write fails (disk full) | OSError surfaces | Re-run after resolving disk |

`reports/topic_map_report.json` contains:
- `n_docs`, `unmatched_docs` (list of doc ids with empty primary),
- `per_doc` (rows with id, title, theme, topics_hit, primary,
  secondary, top_scores).

## 9. Out-of-scope

- Whether the *taxonomy itself* covers the corpus thematically —
  that's a curator judgment, not a mechanical check.
- Whether topic definitions match their matchers semantically —
  out of scope; covered by reviewer-pass in
  [GUIDE-reviewer.md](../guides/GUIDE-reviewer.md).
- LLM-router accuracy — covered by
  [TS-004](TS-004-voice-card-protocol.md) §"Router routing accuracy".
