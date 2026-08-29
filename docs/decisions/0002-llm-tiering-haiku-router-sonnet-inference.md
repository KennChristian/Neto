# ADR-0002: LLM tiering — Haiku 4.5 for routing, Sonnet 4.6 for inference, Opus excluded

* Status: accepted
* Date: 2026-05-02
* Deciders: Doc, Janet

## Context and Problem Statement

Given Claude as the inference vendor ([ADR-0001](0001-claude-not-openai-for-inference.md)),
which model(s) do we use? The pipeline has two LLM calls per turn: a
short router call (input ~2.8K tokens, output ~70 tokens) that picks
1-3 topics from a 37-topic taxonomy, and a longer inference call (input
~13K tokens, output ~250-350 tokens) that produces the CJ-voiced
response. Their requirements are very different — the router needs to
be cheap and structured; the inference needs to be voice-faithful.

## Decision Drivers

* Per-call cost — keep total per-turn around $0.02 target (later
  measured at ~$0.04-0.05; see [PROJECT.md](../../PROJECT.md) §9).
* Latency — the router is in the critical path; faster is better.
* Voice fidelity — only the inference call sees the voice card.
* Reasoning depth — neither call needs Opus-tier reasoning; the router
  is a classification, the inference is creative writing constrained by
  a system prompt.

## Considered Options

* All Sonnet 4.6 — both router and inference
* All Opus — both router and inference
* Tiered: Haiku 4.5 router + Sonnet 4.6 inference
* Tiered: Haiku 4.5 router + Opus inference

## Decision Outcome

Chosen option: **Haiku 4.5 router + Sonnet 4.6 inference**, because the
router is a cheap classifier that doesn't need Sonnet-tier reasoning,
and the inference call hits the voice-fidelity bar on Sonnet without
the Opus price premium.

### Consequences

* Good: router call costs ~$0.003 instead of ~$0.013 if Sonnet had
  routed.
* Good: Opus reasoning premium avoided on a workload that does not
  reward it.
* Bad: cross-model behavior differences — see [ADR-0010](0010-anthropic-prompt-caching-voice-card.md)
  and [LL-002](../lessons/LL-002-haiku-ignores-cache-control.md): Haiku 4.5
  silently ignores `cache_control`, while Sonnet honors it.
* Neutral: model IDs are pinned in `app/cj_chat.py` (`ROUTER_MODEL =
  "claude-haiku-4-5-20251001"`, `INFERENCE_MODEL = "claude-sonnet-4-6"`).

## Pros and Cons of the Options

### All Sonnet 4.6

* Good, because uniform model behavior (caching, JSON output, retries).
* Bad, because the router call is ~4× more expensive than it needs to be.

### All Opus

* Good, because top-of-line reasoning across both calls.
* Bad, because Opus pricing makes the $0.02/turn target infeasible.
* Bad, because the workload (topic routing + constrained voice
  generation) does not require Opus reasoning.

### Tiered: Haiku 4.5 router + Sonnet 4.6 inference

* Good, because cheap router (~$0.003) leaves headroom in the per-turn budget.
* Good, because Sonnet 4.6 meets voice-fidelity bar in build-week tests.
* Bad, because mixed-model behavior introduced [LL-002](../lessons/LL-002-haiku-ignores-cache-control.md).

### Tiered: Haiku 4.5 router + Opus inference

* Good, because cheap router + premium inference quality.
* Bad, because the Opus premium is not earned by the workload, and
  pushes per-turn cost above the $0.02 target.

## More Information

Model IDs and per-call cost split documented in [PROJECT.md](../../PROJECT.md)
§9 and §11 (`ROUTER_MODEL = "claude-haiku-4-5-20251001"`,
`INFERENCE_MODEL = "claude-sonnet-4-6"`). Behavior split between Haiku
and Sonnet on caching documented in [handover 2026-05-16](../handover_claude_code_2026-05-16.md) §8 Bug #1.
Strategic handover doc is not on disk; date is per the instruction set
that scoped this ADR.
