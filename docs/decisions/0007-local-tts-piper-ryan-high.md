# ADR-0007: Local TTS via Piper voice `en_US-ryan-high` (not OpenAI TTS)

* Status: accepted
* Date: 2026-05-14
* Deciders: Doc, Janet

## Context and Problem Statement

The app needs text-to-speech. Options were: local TTS via Piper with
one of its voice models, OpenAI TTS (`tts-1` with the `onyx` voice), or
ElevenLabs. The voice that speaks needs to read CJ's English with
embedded Tagalog / Spanish / French phrases (*"Maraming salamat po,"*
*"Au contraire,"* *"Compañero"*) without sounding obviously wrong.

## Decision Drivers

* Demo-day network risk — if wifi flakes, TTS must still work.
* Privacy — keep audio on the demo machine.
* Per-turn cost — local TTS is $0/turn after voice download.
* Diction quality — does the voice carry CJ's measured judicial tempo?
* Multilingual phrase handling — Tagalog/Spanish/French inclusions.

## Considered Options

* Local: Piper with `en_US-ryan-high`
* Cloud: OpenAI TTS `tts-1` with the `onyx` voice
* Cloud: ElevenLabs

## Decision Outcome

Chosen option: **local Piper with the `en_US-ryan-high` voice**,
because audio stays on the laptop, demo-day network failure does not
break TTS, and per-turn cost is $0. Tagalog/Spanish/French phrases are
approximated via a hand-crafted `TTS_FOREIGN_SUBSTITUTIONS` table (12
entries) — a stopgap, not native quality. The single-function swap to
OpenAI TTS is preserved in `synthesize_speech()` if the team later
prioritizes diction over local-only execution.

### Consequences

* Good: zero per-turn audio cost; no second vendor relationship.
* Good: privacy — generated audio never leaves the demo machine.
* Good: demo-day network failure does not break TTS.
* Bad: Piper RTF ~1.8 on CPU — a 150-word response takes ~5-10s to
  render.
* Bad: `en_US-ryan-high` cannot pronounce Tagalog/Spanish/French
  natively; phonetic substitutions are crude.
* Neutral: a one-function swap to OpenAI TTS `onyx` is documented in
  [PROJECT.md](../../PROJECT.md) §12 ("Swap to OpenAI TTS / ElevenLabs")
  — `synthesize_speech()` is the single point of change.

## Pros and Cons of the Options

### Local: Piper with `en_US-ryan-high`

* Good, because $0/turn, no network dependency, private.
* Good, because deterministic — same input, same wav.
* Bad, because American-English-only voice with crude phonetic subs for
  non-English phrases.
* Bad, because ~5-10s synthesis on CPU for a 150-word response.

### Cloud: OpenAI TTS `tts-1` (`onyx`)

* Good, because native multilingual handling — `TTS_FOREIGN_SUBSTITUTIONS`
  can be dropped entirely.
* Good, because faster (drops total turn to ~12-15s per [PROJECT.md](../../PROJECT.md) §8).
* Good, because ~$0.50 for a 50-turn demo at `tts-1` pricing.
* Bad, because network dependency on demo day.
* Bad, because adds a vendor relationship.

### Cloud: ElevenLabs

* Good, because reportedly best-in-class voice quality.
* Bad, because adds a vendor relationship for marginal benefit over `onyx`.
* Bad, because cost is meaningfully higher than `tts-1`.

## More Information

[PROJECT.md](../../PROJECT.md) §8 (performance) and §12 ("Swap to
OpenAI TTS / ElevenLabs") document the one-function swap path.
[handover 2026-05-16](../handover_claude_code_2026-05-16.md) §6 row
"`TTS_FOREIGN_SUBSTITUTIONS` list (12 entries)": *"User explicitly
chose this over OpenAI TTS swap."* Strategic handover doc not on disk;
date is per the instruction set that scoped this ADR.
