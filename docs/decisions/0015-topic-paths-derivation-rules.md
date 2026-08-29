# ADR-0015: `topic_paths` derivation — word-boundary matching, ≥2-hit primary threshold, tier tie-break

* Status: accepted
* Date: 2026-05-26
* Deciders: Janet

## Context and Problem Statement

Every document in the corpus has a `topic_paths` field with `primary`
and `secondary` lists of topic ids drawn from
[`corpus/voice/topic_map.json`](../../corpus/voice/topic_map.json).

The Haiku router will use these in Phase 4
([PLAN-0001](../implementation-plans/PLAN-0001-runtime-app-haiku-router-sonnet-composer.md))
as the deterministic structured lookup
([ADR-0003](0003-reject-embeddings-for-v1.md),
[ADR-0004](0004-pattern-1-topic-routed-two-stage-api.md)). The
router's choice of topic *fans out* to whichever docs have that topic
in `primary` (high-relevance) or `secondary` (also-relevant).

Routing quality is bounded by:
1. How well the taxonomy's matchers distinguish a topic.
2. How `topic_paths` are derived from matcher scores for each doc.

Early in Phase 2 development, a naive substring match caused
`supreme_court_history` to claim 60 of 79 documents — because tokens
like `magistrate`, `judiciary`, and `ponente` appear in passing in
most legal columns
([LL-009](../lessons/LL-009-substring-matching-overbroad.md)).

## Decision Drivers

* **Distinguishability**: a topic must claim only the docs where it is
  meaningfully present, not every doc that uses one of its words once
  in passing.
* **Determinism**: re-running `scripts/apply_topic_paths.py` must yield
  bit-identical `topic_paths` arrays given the same corpus and
  taxonomy.
* **No-empty-routes guarantee**: every doc must have at least one
  primary topic, otherwise the router has no destination on a hit.
* **Tier coherence**: when two topics tie on raw score, the
  higher-tier (anchor > core > subordinate > meta) wins — anchors are
  designed to be the natural routing destination.

## Considered Options

1. **Word-boundary regex match + threshold + tier tie-break (chosen)**
   — keywords compile to `\bterm\b` regexes; score = count of distinct
   matcher terms that hit; primary = top scorers with score ≥ 2;
   secondary = next-tier scorers with score ≥ 1; ties broken by tier.
2. **Plain substring match** — `term.lower() in haystack`.
3. **TF-IDF over the taxonomy + cosine threshold** — would require
   embedding the matchers, conflicts with
   [ADR-0003](0003-reject-embeddings-for-v1.md).
4. **Rule-per-topic scoring functions** — every topic ships its own
   Python predicate that returns a score.

## Decision Outcome

Chosen option: **Word-boundary regex match + threshold + tier
tie-break**.

The implementation is in `scripts/build_topic_map.py`:

- `_kw_pattern(term)` compiles `\b{escaped term}\b` once and caches.
- `score_topic(topic, haystack)` returns the count of *distinct*
  matcher terms (keywords + entities) whose pattern hits the
  haystack.
- The haystack is the lowercased concatenation of the doc's `title`,
  `one_paragraph_summary`, `primary_topics`, `sub_topics`, `keywords`,
  `register_markers`, and flattened `entities` lists.
- `derive_topic_paths(doc_id, doc_scores)` sorts topics by `(-score,
  tier_rank)` and selects:
  - `primary`: up to 2 topics with `score >= 2`.
  - `secondary`: up to 3 topics with `score >= 1`.
  - If no topic crosses the ≥2 threshold, the strongest scorer is
    promoted to primary to guarantee every doc has at least one
    routing destination.

### Consequences

* Good: word-boundary matching eliminates the substring false-match
  cliff. `asean_law_association` no longer matches every doc with
  `Salonga` in it (LL-009).
* Good: the ≥2 threshold raises the routing confidence bar — *one*
  keyword match could be incidental; *two* is signal.
* Good: deterministic. Re-running on the same inputs yields the same
  `topic_paths` arrays. CI/test specs can diff against a golden file
  ([TS-003](../test-specs/TS-003-topic-paths-derivation.md)).
* Good: tier tie-break encodes intent — anchors *are* the primary
  routing surface; subordinates are filler.
* Good: the no-empty-routes guarantee means the router never has to
  fall back to "no topic" — a useful invariant for downstream
  retrieval.
* Bad: a topic whose entire signature is a single short term (`"AI"`)
  cannot reach score ≥ 2 without listing it twice or coupling it to
  an entity hit. Surfacing this constraint at curation time is the
  fix (see
  [PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md)
  on the *minimum two-distinct-matchers* rule for new topics).
* Bad: a doc with rich keywords but no topic-specific tokens may get
  promoted into a topic via the no-empty-routes fallback even when
  the fit is weak. Detectable in
  [TS-002](../test-specs/TS-002-topic-map-matchers.md) — flag any
  doc whose primary topic has score = 1.
* Neutral: the score is *count of distinct matcher terms*, not
  frequency. Repeating `rule of law` twice in a doc adds nothing.
  This is deliberate — a topic's confidence should come from breadth
  of evidence, not from a single phrase being repeated.

## Pros and Cons of the Options

### Word-boundary + threshold + tier tie-break (chosen)

* Good, because eliminates substring-leakage false matches.
* Good, because deterministic and testable.
* Good, because tie-break is explicit and inspectable.
* Bad, because requires ≥2 distinct matchers per topic.

### Plain substring match

* Good, because simplest possible implementation.
* Bad, because 3-letter or 4-letter matcher terms leak (`ala`, `feu`).
* Bad, because over-broad topics (60/79 docs) eat the routing surface.

### TF-IDF / cosine

* Good, because well-understood retrieval primitive.
* Bad, because conflicts with [ADR-0003](0003-reject-embeddings-for-v1.md);
  introduces non-determinism if the embedding model is swapped.

### Rule-per-topic scoring functions

* Good, because maximally expressive (regexes, theme constraints,
  date windows).
* Bad, because every topic becomes a code change; review surface
  explodes.
* Bad, because uniform reasoning across topics is lost — "why did this
  doc match topic X?" requires reading X's predicate.

## More Information

- Implementation: `score_topic()`, `derive_topic_paths()` in
  `scripts/build_topic_map.py`.
- Driving incident:
  [LL-009](../lessons/LL-009-substring-matching-overbroad.md).
- Test spec for these rules:
  [TS-003](../test-specs/TS-003-topic-paths-derivation.md).
- Topic-map evolution process for taxonomy edits:
  [PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md).
