# ADR-0004: Pattern 1 — topic-routed two-stage API call (router → inference)

* Status: accepted
* Date: 2026-05-14
* Deciders: Doc, Janet

## Context and Problem Statement

Given the decision to route by hand-curated topics rather than
embeddings ([ADR-0003](0003-reject-embeddings-for-v1.md)), how do we
shape the request flow? Three patterns were on the table:

1. **Pattern 1 (two-stage):** small router call decides which topics
   apply; inference call gets only the routed topics' data plus a few
   raw doc extractions.
2. **Pattern 2 (single-call stuffing):** stuff all 37 topics + every
   doc extraction into one inference call.
3. **Pattern 3 (agentic loop):** let the model decide what to retrieve
   via tool use across multiple turns.

The pipeline must hit ~$0.02/turn and stay under ~25s warm-turn
latency.

## Decision Drivers

* Per-turn cost target (~$0.02; later measured at ~$0.04-0.05).
* Per-turn latency (≤ ~25s warm).
* Attention dilution — packing too much context degrades response
  quality.
* Debuggability — the router's choices should be visible to the
  operator.

## Considered Options

* Pattern 1 — two-stage: Haiku router → Sonnet inference with routed context
* Pattern 2 — single-call: stuff the whole 320KB `topic_map.json` into one Sonnet call
* Pattern 3 — agentic: Sonnet driving tool calls to retrieve, iterating

## Decision Outcome

Chosen option: **Pattern 1**, because it preserves the ~$0.02/turn
target, keeps inference context focused (10-20K tokens vs 320K), and
gives the operator visible router output for debugging.

### Consequences

* Good: per-turn cost stays bounded by router (~$0.003) + inference
  with focused context (~$0.04-0.05).
* Good: router's `{primary_topic, secondary_topics, confidence,
  reasoning}` output drives the dashboard Sources expander — operator
  can see why a topic was chosen.
* Good: inference attention is on a focused context block, improving
  voice fidelity.
* Bad: two API calls per turn instead of one — slightly higher
  cold-path latency on the router (~1.5s).
* Bad: the system is bounded by the router's correctness; mis-routes
  cascade.
* Neutral: enables [ADR-0010](0010-anthropic-prompt-caching-voice-card.md) —
  the static voice-card prefix on the inference call is cacheable.

## Pros and Cons of the Options

### Pattern 1 — two-stage

* Good, because per-call cost stays bounded.
* Good, because router output is debuggable in the dashboard.
* Good, because inference context is small enough to attend to fully.
* Bad, because two calls per turn (router adds ~1.5s).

### Pattern 2 — single-call stuffing

* Good, because one round trip; simpler code path.
* Bad, because ~$3/turn (rejected per [PROJECT.md](../../PROJECT.md) §3:
  *"single-call alternative (stuffing all 320KB of `topic_map.json`
  into one inference) was rejected: ~$3 per turn, 5-10s latency,
  attention dilution"*).
* Bad, because attention dilution degrades voice fidelity.

### Pattern 3 — agentic

* Good, because the model can self-correct retrieval on follow-up.
* Bad, because per-turn cost is unbounded; multi-step latency blows the
  ≤25s budget.
* Bad, because workflow is Q&A, not agentic — see [ADR-0009](0009-messages-api-not-managed-agent.md).

## More Information

[PROJECT.md](../../PROJECT.md) §3 documents this directly: *"Two Claude
calls instead of one is a deliberate choice"*; [handover 2026-05-16](../handover_claude_code_2026-05-16.md)
§4 confirms the wiring (`route_question()` at `cj_chat.py:168-209`,
`build_context()` at `cj_chat.py:215-269`, `generate_response()` at
`cj_chat.py:275-316`). Strategic handover doc not on disk; date is per
the instruction set that scoped this ADR.
