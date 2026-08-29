# ADR-0003: Reject embeddings and vector DB for v1

* Status: accepted
* Date: 2026-05-14
* Deciders: Doc, Janet

## Context and Problem Statement

The corpus is 89 documents and ~150K words. The early design assumed an
embedding-based retrieval layer: chunk the corpus, embed each chunk,
store in a vector DB, retrieve top-k for the user's question, then send
the retrieved chunks to inference. We evaluated three embedding vendors
during the build week (Sentence Transformers locally, OpenAI
embeddings, Voyage AI) and hit recurring problems: noisy retrieval on
questions phrased in CJ's idiom, vector-DB operational overhead for a
single-machine demo, and the corpus being small enough that an
LLM-driven classification was tractable.

## Decision Drivers

* Retrieval quality on questions written in CJ-register English (not
  the same vocabulary as the corpus).
* Operational simplicity — single-machine demo, no separate vector DB
  service.
* Corpus size — at 89 docs / 37 topics, classification by an LLM is
  feasible in one call.
* Time-to-demo — May 30, 2026.

## Considered Options

* Continue with Sentence Transformers (local embeddings)
* Switch to OpenAI embeddings
* Switch to Voyage AI embeddings
* Drop embeddings entirely; replace with a hand-curated topic taxonomy
  and an LLM router

## Decision Outcome

Chosen option: **drop embeddings entirely**, replaced with a
hand-curated 37-topic taxonomy (anchor / pillar / vector / personal
tiers) and a Haiku-based router that picks 1-3 topics per question.
Retrieval is then a deterministic lookup against `topic_map.json` and
the per-doc Stage-1 extractions in `app/artifacts/topics/`.

### Consequences

* Good: no vector DB, no embeddings model, no chunking layer — fewer
  moving parts for the demo.
* Good: routing is debuggable (Haiku returns topic IDs + reasoning, all
  shown in the dashboard's Sources expander).
* Good: per-turn retrieval is deterministic given a routed topic.
* Bad: the taxonomy was hand-curated and must be maintained as the
  corpus grows (Pass B speeches will likely add or shift topics).
* Bad: routing accuracy is bounded by the router prompt and the
  taxonomy's coverage; questions outside the taxonomy fall back to
  `rule_of_law`.
* Neutral: the synthesis pipeline (`corpus/synthesis_scripts/`) still
  produces a `signature_library.json` of 684 phrases — see [LL-005](../lessons/LL-005-signature-library-loaded-but-unused.md).

## Pros and Cons of the Options

### Continue with Sentence Transformers

* Good, because fully local, free per-call.
* Bad, because retrieval quality on CJ-register questions was below the
  bar in build-week tests.

### Switch to OpenAI embeddings

* Good, because higher-quality embeddings than Sentence Transformers.
* Bad, because adds a second vendor for a single use case.
* Bad, because still needed a vector DB or in-memory index layer.

### Switch to Voyage AI embeddings

* Good, because purpose-built for retrieval; reputable quality.
* Bad, because adds yet another vendor and key for one capability.
* Bad, because does not address the operational-complexity concern.

### Drop embeddings entirely

* Good, because matches corpus size — 37 topics is small enough for an
  LLM router.
* Good, because removes an entire subsystem (chunker + embedder + index).
* Bad, because requires the taxonomy be hand-curated and maintained.

## More Information

Repo state confirms this decision: there is no `embeddings/`,
`vector_db/`, or chunking module on disk; routing is via
`route_question()` in [app/cj_chat.py](../../app/cj_chat.py) against
`topic_map.json`. [handover 2026-05-16](../handover_claude_code_2026-05-16.md) §4
row "Embeddings ingestion": *"None — routing is by topic IDs via Haiku,
not vector similarity. No embeddings layer exists."* Strategic handover
doc not on disk; date is per the instruction set that scoped this ADR.
