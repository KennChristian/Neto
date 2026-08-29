# LL-002: Haiku 4.5 silently ignores `cache_control`

* Date: 2026-05-16
* Severity: minor
* Related: [ADR-0010](../decisions/0010-anthropic-prompt-caching-voice-card.md), [ADR-0002](../decisions/0002-llm-tiering-haiku-router-sonnet-inference.md)

## Symptom

`cache_control: {"type": "ephemeral"}` was set on the router's
~2,400-token system prompt (Haiku 4.5) and the inference call's
~3,265-token voice card (Sonnet 4.6). The inference call reports
cache writes on the first call and cache reads on subsequent calls as
expected. The router call, however, reports
`cache_creation=0, cache_read=0, regular_input=~2,807` on every call,
regardless of how recently it was called. Same code path, same SDK,
different result.

## 5 Whys

1. **Why does the router report no cache usage?** Anthropic's API does
   not honor `cache_control` on Haiku 4.5 in this SDK version.
2. **Why was the directive set on the Haiku call anyway?** Because the
   change "mark every system prompt as ephemeral" was applied uniformly
   without testing per-model behavior; the assumption was the SDK-level
   directive would apply on any model.
3. **Why was the assumption that SDK-level directives apply on any
   model?** Because that is the typical pattern for cross-model
   features — and prompt caching is documented as an Anthropic feature,
   not as a per-model feature.
4. **Why did per-model behavior diverge here?** Caching has model-side
   minima and support windows that are not always reflected in SDK
   surface; either Haiku 4.5 lacks support in this SDK version, or the
   2,400-token router prompt is below Haiku's effective minimum.
5. **Why wasn't this caught before publishing savings claims?**
   Because we trusted the SDK-level configuration to "just work" rather
   than verifying empirically per model.

## Root Cause

We assumed prompt caching was a feature that worked uniformly across
Anthropic models on this SDK version. Empirically, only Sonnet honored
the directive on this SDK; Haiku silently dropped it.

## Fix Applied

[handover 2026-05-16](../handover_claude_code_2026-05-16.md) §8 logs
the bug; the `cache_control` directive on the router prompt is left
in place (no harm) and the published cost numbers reflect that the
router gets no cache discount. The router is <7% of total cost so the
practical impact is small. Wired at [app/cj_chat.py](../../app/cj_chat.py)
`cj_chat.py:189-194` (router system block, marked but not honored) and
`cj_chat.py:302-309` (inference system block, honored).

## Generalizable Lesson

When you enable a feature like prompt caching, verify per-model
behavior empirically by inspecting the per-call `usage` payload (e.g.
`cache_creation_input_tokens`, `cache_read_input_tokens`). "SDK accepted
the directive without error" is not the same as "the model honored it."
This applies to any feature with model-side dependencies — caching,
tool use, structured output, extended thinking — and is cheap to check:
log the usage fields once after the change and look at them.
