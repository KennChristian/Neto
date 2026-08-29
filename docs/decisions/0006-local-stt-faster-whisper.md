# ADR-0006: Local STT via faster-whisper (not a cloud STT API)

* Status: accepted
* Date: 2026-05-14
* Deciders: Doc, Janet

## Context and Problem Statement

The app needs speech-to-text. Anthropic does not ship an STT API
([ADR-0001](0001-claude-not-openai-for-inference.md) consequences), so
STT must be solved separately. Options were: local STT via
`faster-whisper`, OpenAI Whisper API, Deepgram Nova-2, AssemblyAI, or
Azure Speech. The demo machine is a Windows laptop with no network
guarantees on demo day.

## Decision Drivers

* Demo-day network risk — if wifi flakes, audio must still work.
* Privacy — keep audio on the demo machine.
* Per-turn cost — local STT is $0 per turn after one-time model download.
* Filipino/English code-switching tolerance — CJ speakers will mix.
* Latency — currently ~3-5s on the `medium` model on CPU.

## Considered Options

* Local: `faster-whisper` `medium` (CPU, int8)
* Cloud: OpenAI Whisper API (~$0.001/turn)
* Cloud: Deepgram Nova-2 (~$0.0007/turn, strong Filipino support)
* Cloud: AssemblyAI
* Cloud: Azure Speech

## Decision Outcome

Chosen option: **local `faster-whisper` `medium`**, because audio never
leaves the demo machine, demo-day network failure does not break STT,
and per-turn cost is $0 after a one-time 1.5 GB model download.

### Consequences

* Good: zero per-turn audio cost; no second vendor relationship.
* Good: privacy — mic input never leaves the laptop.
* Good: if wifi flakes mid-demo, audio still works; only the Claude
  calls fail (and those have retry).
* Bad: 3-5s warm transcription on CPU — the build kit's ≤4s end-to-end
  target is unreachable on this hardware with `medium`.
* Bad: 1.5 GB model cache to populate on first run (~22 min first-time
  download on this machine).
* Bad: VAD threshold (`min_silence_duration_ms=500`) carries from the
  reference impl; build kit recommends 1000ms — see [handover 2026-05-16](../handover_claude_code_2026-05-16.md) §7.
* Neutral: `WHISPER_MODEL=small` is available as an env-var switch for
  English-only demos (~1s transcription) at the cost of code-switch
  tolerance.

## Pros and Cons of the Options

### Local: faster-whisper medium

* Good, because $0/turn, no network dependency, private.
* Bad, because slow on CPU and large one-time model download.

### OpenAI Whisper API

* Good, because simple install, no 1.5 GB cache.
* Good, because ~$0.001/turn is negligible.
* Bad, because network round-trip required on every turn.
* Bad, because adds a second vendor relationship.

### Deepgram Nova-2

* Good, because reportedly the best Filipino-English support.
* Good, because ~$0.0007/turn.
* Bad, because adds a third vendor (with Anthropic).
* Bad, because network dependency on demo day.

### AssemblyAI / Azure Speech

* Good, because mature offerings.
* Bad, because none give a decisive advantage over the simpler options;
  more vendors, more keys, more onboarding.

## More Information

`WHISPER_MODEL=medium` documented in [PROJECT.md](../../PROJECT.md) §11
(env vars) and §8 (performance table). [handover 2026-05-16](../handover_claude_code_2026-05-16.md)
§4 confirms wiring at `cj_chat.py:152-162` and §11 Q4 enumerates the
cloud alternatives offered to the user (kept local). Strategic handover
doc not on disk; date is per the instruction set that scoped this ADR.
