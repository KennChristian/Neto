# ADR-0010: Enable Anthropic prompt caching on the voice-card system prompt

* Status: accepted
* Date: 2026-05-16
* Deciders: Doc, Janet

## Context and Problem Statement

After cost measurement on 2026-05-15, the per-turn cost was ~$0.048
(higher than the README's earlier $0.016 estimate), driven primarily
by the inference call shipping a ~3,265-token voice card on every
turn. Anthropic prompt caching offers a 10× input-cost discount on
cached prefixes for 5 minutes after a cache write. The question was
whether to wire caching, and on which prefix.

Before measurement, the savings were projected at ~55%. The empirical
measurement showed ~18% per cached turn — see [LL-001](../lessons/LL-001-cache-savings-18-not-55.md).

## Decision Drivers

* Per-turn cost ($0.048 baseline; ~$0.02 target).
* Minimal code surface — keep the cache change a small diff.
* No quality regression — only cache content that is byte-identical
  across turns.
* Observability — operator needs to see the savings.

## Considered Options

* Don't cache; accept ~$0.048/turn.
* Cache only the voice card on the inference call (~3,265 tokens).
* Also cache the topic_map and / or conversation history.

## Decision Outcome

Chosen option: **cache the voice card on the inference call only**,
marked with `cache_control: {"type": "ephemeral"}`. Also mark the
router system prompt as cached for future-proofing, accepting that
Haiku 4.5 silently ignores it (see [LL-002](../lessons/LL-002-haiku-ignores-cache-control.md)).
Add a module-level `CACHE_STATS` accumulator and a sidebar metrics
panel so the operator can see paid/saved tokens and dollars per
session.

### Consequences

* Good: per-turn cost drops from ~$0.048 to ~$0.040 on cache hits — see
  [PROJECT.md](../../PROJECT.md) §9 and [handover 2026-05-16](../handover_claude_code_2026-05-16.md) §1.
* Good: code change is small (+91 lines in `cj_chat.py`, +30 in
  `dashboard.py`).
* Good: observability built-in — dashboard sidebar shows live savings.
* Bad: first call pays a 1.25× cache-write premium (`paid $0.0485 vs
  baseline $0.0460 (saved $-0.0024)` per [handover 2026-05-16](../handover_claude_code_2026-05-16.md) §5).
* Bad: savings are 18% per cached turn, not the 55% initially projected — see [LL-001](../lessons/LL-001-cache-savings-18-not-55.md).
* Bad: Haiku 4.5 ignores `cache_control` on the router prompt — see [LL-002](../lessons/LL-002-haiku-ignores-cache-control.md).
* Neutral: extending the cache to the topic_map (~71K tok) or
  conversation history is sketched in `cj_chat.py` comments but not
  wired — see [handover 2026-05-16](../handover_claude_code_2026-05-16.md) §11 Q3.

## Pros and Cons of the Options

### Don't cache; accept ~$0.048/turn

* Good, because zero code change, zero risk.
* Bad, because the cost lever is sitting on the table.

### Cache only the voice card on inference

* Good, because the voice card is byte-identical every call — clean
  cache hits.
* Good, because the diff is small and reversible.
* Good, because no quality regression — same content, same model.
* Bad, because savings are bounded by the voice card's share of the
  input (~25% of inference input, hence ~18% total savings).

### Also cache topic_map / conversation history

* Good, because larger cache → larger savings on hit.
* Bad, because conversation history changes every turn — can't share
  a cache.
* Bad, because caching the full 37-topic `topic_map` (~71K tok)
  changes the architecture: we'd send all topics every call. Trades
  $/turn after several turns but risks quality regression from
  attention dilution (see [ADR-0004](0004-pattern-1-topic-routed-two-stage-api.md)).

## More Information

Wired in [app/cj_chat.py](../../app/cj_chat.py) — `cache_control` on
system blocks at `cj_chat.py:189-194` (router) and `cj_chat.py:302-309`
(inference); `CACHE_STATS` accumulator at `cj_chat.py:107-178`. Sidebar
panel at `app/dashboard.py:141-167`. [PROJECT.md](../../PROJECT.md) §9
("With prompt caching enabled (current code)") and [handover 2026-05-16](../handover_claude_code_2026-05-16.md) §1
TL;DR carry the 18% number. Quote from the latter on the projection
gap: *"empirically delivers ~18% per-turn savings on warm cache (not
the 55% I initially projected)"*.
