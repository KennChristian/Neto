# ADR-0001: Use Claude (not OpenAI) for inference

* Status: accepted
* Date: 2026-05-02
* Deciders: Doc, Janet

## Context and Problem Statement

The conversation app needs an LLM to produce CJ-voiced responses given
a routed context block of ~10-20K tokens. Two practical vendors were on
the table at the time: Anthropic (Claude) and OpenAI (GPT). The choice
had to balance voice-fidelity (does the model adhere to the voice card's
register and style?), price-per-turn at the expected demo workload
(~$0.02/turn target), tooling fit (prompt caching, system-prompt
behavior), and the team's prior familiarity with each vendor's API.

## Decision Drivers

* Voice-card adherence — the model must respect a ~3K-token system
  prompt describing CJ's register, signature phrases, and out-of-corpus
  policy without drifting.
* Per-turn cost at ~$0.02 target.
* Tooling fit — prompt caching support, deterministic tool/JSON output
  for the router, retry semantics.
* Team familiarity — Anthropic SDK already in use for prior work.

## Considered Options

* Anthropic Claude (Haiku 4.5 router + Sonnet 4.6 inference)
* OpenAI GPT (GPT-4o or GPT-4-mini tier)
* Mix-and-match (e.g. OpenAI router + Claude inference)

## Decision Outcome

Chosen option: **Anthropic Claude**, because the team already had
working code against the Anthropic SDK, Claude's adherence to long
system prompts (the voice card) was strong in early tests, and prompt
caching offered a clear cost lever on the static voice-card prefix.

### Consequences

* Good: single SDK, single billing surface, prompt-caching available
  on the voice-card prefix (see [ADR-0010](0010-anthropic-prompt-caching-voice-card.md)).
* Good: Sonnet 4.6 voice fidelity met the bar in build-week sanity
  checks (twin beacons, *Au contraire*, *Cheers!* all surfaced).
* Bad: Anthropic does not ship an STT API — STT had to be solved
  separately (see [ADR-0006](0006-local-stt-faster-whisper.md)).
* Neutral: vendor lock to Anthropic for inference; swap would require
  reworking the `generate_response()` and `route_question()` helpers.

## Pros and Cons of the Options

### Anthropic Claude

* Good, because team is already using the Anthropic SDK; one vendor, one key.
* Good, because Claude adhered to the voice card without prompt acrobatics.
* Good, because Anthropic prompt caching gives a static-prefix discount.
* Bad, because no STT API — STT must be sourced elsewhere.

### OpenAI GPT

* Good, because OpenAI ships STT (Whisper API) and TTS in the same account.
* Bad, because adding OpenAI would mean a second SDK, second key, second billing.
* Bad, because voice-card adherence was not tested on GPT during the build week.

### Mix-and-match

* Good, because best-of-breed per call.
* Bad, because doubles the operational surface (two SDKs, two keys, two retry policies) for marginal benefit.

## More Information

Evidence aggregated from [PROJECT.md](../../PROJECT.md) §9 (cost model,
pricing assumptions) and [docs/handover_claude_code_2026-05-16.md](../handover_claude_code_2026-05-16.md)
§4 (Sonnet 4.6 voice fidelity confirmed in the smoke test) and §11 Q4
(Anthropic has no STT, alternatives offered include OpenAI Whisper /
Deepgram / AssemblyAI). The strategic handover doc that would normally
cite a direct May 2 quote is not on disk in this repo as of writing —
date is per the instruction set that scoped this ADR.
