# LL-001: Prompt caching savings were 18%, not the projected 55%

* Date: 2026-05-16
* Severity: moderate
* Related: [ADR-0010](../decisions/0010-anthropic-prompt-caching-voice-card.md)

## Symptom

Before wiring Anthropic prompt caching, the projected per-turn savings
were quoted to the user as "~55% — biggest win." After implementation
and empirical measurement on 2026-05-16, the actual savings were ~18%
per cached turn and ~13% steady-state averaged over a session
(including the first-call cache-write premium). The projection was
~3× the reality.

## 5 Whys

1. **Why was the projection 55% instead of 18%?** The projection
   assumed prompt caching would discount ~55% of inference input
   tokens.
2. **Why did the projection assume ~55% of inference input was cached?**
   Because the voice card (~3,265 tokens) felt like a "big" prefix
   intuitively, without a back-of-envelope calculation of how it
   compared to the rest of the inference input.
3. **Why didn't a back-of-envelope calculation happen first?** Because
   the user asked for "the biggest win," and the answer was reached as
   a rough estimate from a memory of the voice card being the largest
   single artifact, rather than from inspecting an actual per-call
   token breakdown.
4. **Why was the largest-single-artifact intuition wrong?** Because the
   inference call ships ~13,000 input tokens total per turn: voice
   card (~3,265) + topic_data (~3,800) + source_documents (~2,100) +
   conversation history (~1,500 mid-session) + everything else. The
   voice card is only ~25% of that.
5. **Why is 25% of the input being discounted not yielding 25%
   savings?** Because cache reads are 0.1× the regular input price
   (90% off), not 100% off. Discounting 25% of input at 90% off
   yields ~22% input savings — and with output cost unchanged, total
   savings land around 18%.

## Root Cause

A cost projection was made from intuition about prefix size rather than
from a per-call token-mix calculation against actual cache-discount
math.

## Fix Applied

[PROJECT.md](../../PROJECT.md) §9 was rewritten with empirically-measured
numbers (~$0.048 baseline, ~$0.040 cached, ~13% averaged session
savings). [handover 2026-05-16](../handover_claude_code_2026-05-16.md)
§1 carries the corrected number: *"empirically delivers ~18% per-turn
savings on warm cache (not the 55% I initially projected)."* The cache
itself stays — savings are real, just smaller than projected.

## Generalizable Lesson

Before publishing a savings claim from a caching change, get the
per-call token breakdown of the workload and apply the actual
cache-discount factor to the cached fraction. A "big prefix" intuition
is not a measurement. Specifically: cache savings ≈ (cached fraction
of input) × (1 − cache-read multiplier) × (input share of total cost).
For a prefix that is 25% of input at 90% discount, expect ~18-22%
total, not 55%.
