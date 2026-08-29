# ADR-0009: Messages API (not Managed Agent) — Q&A workflow, not agentic

* Status: accepted
* Date: 2026-05-14
* Deciders: Doc, Janet

## Context and Problem Statement

Anthropic offers two surfaces for building LLM workflows: the raw
Messages API and the Managed Agent API. The Messages API is a stateless
request/response with explicit system prompts and tool-use; the Managed
Agent API wraps tool-use loops, retrieval, and state-keeping. The
question was which to use for a Q&A conversation app.

## Decision Drivers

* Workflow shape — single-turn Q&A with bounded retrieval, not
  multi-step planning.
* Cost control — per-turn budget targets a tight envelope.
* Latency control — managed agent loops can introduce unbounded
  iterations.
* Debuggability — visibility into each call's tokens, cache stats, and
  routed topics.

## Considered Options

* Anthropic Messages API (`anthropic.Anthropic().messages.create(...)`)
* Anthropic Managed Agent API
* A custom tool-use loop on top of Messages API

## Decision Outcome

Chosen option: **Anthropic Messages API**, because the pipeline is
deterministic Q&A — router → retrieve → inference — with no need for
the model to drive multi-step planning. This keeps the cost model
predictable, surfaces token/cache stats directly, and avoids paying for
agent-loop infrastructure we don't use.

### Consequences

* Good: deterministic two-call shape per turn (router + inference).
* Good: per-call `usage` payload exposes `cache_creation_input_tokens`
  and `cache_read_input_tokens` — the `CACHE_STATS` accumulator in
  [app/cj_chat.py](../../app/cj_chat.py) relies on this.
* Good: retry policy is explicit (`Anthropic(max_retries=4)`).
* Bad: the app must do its own state-keeping for conversation history
  (last-10-turn window in `st.session_state` or in-process list).
* Neutral: future moves toward agent-style tool use (e.g.
  letting the model decide between topic-routing vs free retrieval) are
  blocked-by this ADR and would require a revisit.

## Pros and Cons of the Options

### Anthropic Messages API

* Good, because matches the workflow shape exactly.
* Good, because token/cache observability is first-class on each response.
* Good, because no opaque agent loop to debug.
* Bad, because state-keeping is the app's responsibility.

### Anthropic Managed Agent API

* Good, because handles tool-use loops and retrieval for you.
* Bad, because the workflow is not agentic — paying for plumbing we
  don't need.
* Bad, because looser cost/latency bounds.
* Bad, because less visibility into per-call internals.

### Custom tool-use loop on Messages API

* Good, because preserves Messages API observability while adding tool use.
* Bad, because adds complexity for a use case (multi-step planning) we
  do not have.

## More Information

Wiring in [app/cj_chat.py](../../app/cj_chat.py) — `route_question()` at
`cj_chat.py:168-209` and `generate_response()` at `cj_chat.py:275-316`
both call `self.client.messages.create(...)` directly; no agent API in
use. [handover 2026-05-16](../handover_claude_code_2026-05-16.md) §4
confirms. Strategic handover doc not on disk; date is per the
instruction set that scoped this ADR.
