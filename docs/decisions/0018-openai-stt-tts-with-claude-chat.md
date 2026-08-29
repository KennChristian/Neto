# ADR-0018: OpenAI for STT + TTS, Anthropic for chat — push-to-talk + per-sentence parallel TTS

* Status: accepted
* Date: 2026-05-26
* Deciders: Janet

## Context and Problem Statement

The dashboard initially ran with **faster-whisper** (local STT) and
**Piper** (local TTS), keeping both on-device. That stack works but
has three real costs:

1. **Cold start** — first mic recording downloads ~470 MB (small) or
   ~1.5 GB (medium) of Whisper weights. Painful first run; not
   acceptable for a museum kiosk.
2. **Voice quality** — Piper `en_US-ryan-high` is intelligible but
   flat; it mangles every Tagalog phrase CJP code-switches into. The
   user wants a "premium, museum/exhibit-style" UX.
3. **Maintenance** — Piper binary + voice model + Whisper model cache
   are all OS-specific extra installs that diverge across operators.

We need a stack that is:
- Premium-sounding (CJP's testimonial register, Tagalog ornaments
  pronounced respectfully).
- Easy to install (no model downloads, no PATH gymnastics).
- **API-cost-controlled** — explicitly NOT OpenAI's per-minute
  Realtime API, which would be 10-20× the cost.

Anthropic's Claude is already in use for the chat pipeline
([ADR-0001](0001-claude-not-openai-for-inference.md)) and stays.
The decision here is purely about the voice loop endpoints.

## Decision Drivers

* **Cost per turn** must stay in the same order of magnitude as the
  chat pipeline (~$0.04-$0.06 per turn observed in
  [TS-006](../test-specs/TS-006-smoke-test-questions.md)).
* **No always-on microphone** — privacy + cost. The mic opens ONLY
  while the user is recording.
* **No always-on TTS stream** — we don't pay for silence. TTS fires
  per-sentence as the composer streams text.
* **Latency** — perceived latency matters more than total latency.
  Streaming Sonnet text gives the user immediate visible feedback;
  TTS audio plays a few seconds later.
* **No new local installs** — no model downloads, no platform-
  specific binaries.
* **Tagalog code-switching** — OpenAI TTS voices handle Tagalog
  ornaments (*Maraming salamat po*) more naturally than Piper's
  English-only Ryan voice.
* **Persona match** — CJP is a male retired Chief Justice; the TTS
  voice should be a calm, measured male. After A/B comparison the
  user landed on OpenAI's `spruce` voice as the closest match to
  the testimonial / ceremonial-doctrinal register documented in the
  voice card. Iteration history (kept here so the change-rationale
  is auditable):
    - First draft of this ADR shipped with `nova` (female) — wrong
      gender; corrected before any production commit.
    - `onyx` (deep male) followed — landed but felt heavier than
      CJP's actual delivery.
    - `spruce` (calm, even-toned male, from the newer gpt-4o-mini-tts
      voice set) — current default.
  All three remain available via `OPENAI_TTS_VOICE` in `.env`.

## Considered Options

1. **OpenAI Whisper (STT) + OpenAI TTS (tts-1, per-sentence parallel)
   + push-to-talk recording (chosen)**.
2. **OpenAI Realtime API** — bidirectional streaming voice. Highest
   UX quality, single integration point.
3. **Keep faster-whisper + Piper** — purely local, free per-call.
4. **Mix**: OpenAI TTS + local Whisper.
5. **Mix**: OpenAI Whisper + Piper TTS.
6. **Anthropic-only via partner TTS** — Anthropic doesn't ship STT
   or TTS; would require a third provider.

## Decision Outcome

Chosen option: **OpenAI Whisper STT (one call per recording) +
OpenAI TTS (per-sentence parallel) + push-to-talk recording**.

Implementation lives in `app/voice_io.py`:

- `transcribe_openai(audio_path)` — single Whisper call after the user
  presses Stop. No streaming STT, no VAD, no continuous mic. Audio
  blob is the full recording.
- `sentence_chunks(text)` — splits the composer's response on
  sentence boundaries, packing 30-240 char chunks.
- `tts_chunks_parallel_async(text)` — `asyncio.gather` fires one
  OpenAI TTS call per chunk concurrently.
- `tts_concatenate_parallel(text)` — synchronous wrapper that
  concatenates the per-sentence MP3 blobs (pydub if installed) and
  returns one playable MP3.

Streamlit dashboard wires:
- Mic recording → `st.audio_input` (push-to-talk built in;
  user presses ⏺ to start, ⏹ to stop). On stop, ONE
  `transcribe_openai()` call runs.
- Composer text → `st.write_stream(generate_response_stream(...))`.
- After the stream completes, `tts_concatenate_parallel(response)`
  is called once. The result is rendered via `st.audio(autoplay=True)`.
- Robot avatar switches `robot_state` between *idle*, *listening*
  (during STT), *talking* (during TTS + playback). CSS keys eye
  colour and pulse animations off that state.

### Per-turn cost model (late 2025 prices)

| Stage | Provider | Unit | Typical per turn |
|---|---|---|---|
| STT (`whisper-1`) | OpenAI | $0.006 / min audio | ~$0.001 (10-15 s utterance) |
| Router + gate + fidelity (Haiku 4.5) | Anthropic | mix per [TS-006](../test-specs/TS-006-smoke-test-questions.md) | ~$0.005 |
| Composer (Sonnet 4.6, streaming) | Anthropic | per [TS-006](../test-specs/TS-006-smoke-test-questions.md) | ~$0.045-$0.055 |
| TTS (`tts-1`, parallel per sentence) | OpenAI | $0.015 / 1k chars | ~$0.003-$0.005 (200-300 char response) |
| **Per-turn total** | | | **~$0.054-$0.066** |

The chat half (Anthropic) still dominates cost; the voice loop adds
~10% overhead in exchange for hosted Whisper + premium TTS. The
chosen design avoids OpenAI's Realtime API which prices at
$40-$80 per million audio tokens — roughly 10-20× the per-turn cost
above.

### Consequences

* Good: no local model installs. First launch is fast and identical
  across operators.
* Good: per-sentence parallel TTS makes wall-clock TTS time ≈
  slowest single sentence, not the sum. For a 5-sentence response,
  total TTS is ~1-2 s after the composer stream finishes.
* Good: OpenAI's `spruce` voice handles Tagalog ornaments
  intelligibly without Piper's phonetic substitutions, and presents
  the calm, even-toned register that fits CJP. (Falls back to
  `onyx` or any other voice via `OPENAI_TTS_VOICE` if the active
  TTS model doesn't support spruce.)
* Good: every voice call goes through `voice_io.py`. Switching
  providers (Eleven Labs, Cartesia, Azure) is a single-file change.
* Bad: requires an **additional** API key (`OPENAI_API_KEY`) on top
  of `ANTHROPIC_API_KEY`. Documented in `.env.example` and the
  pre-flight banner.
* Bad: voice loop now requires internet. The prior local stack
  worked offline once models were cached. For the kiosk deployment
  ([PLAN-0006](../implementation-plans/PLAN-0006-voice-tts-integration.md))
  this might force a fallback to local TTS — captured as future
  work in the plan, not blocking for the May 30 demo.
* Bad: audio is concatenated at the end — true progressive
  playback (audio chunk N plays while chunks N+1, N+2 still
  generating) would need a custom Streamlit component or a
  client-side MediaSource consumer. The current "stream text live,
  concat audio at end" pattern is a strong v1 and was the explicit
  trade-off the user requested.
* Neutral: `pydub` is recommended (clean MP3 concatenation) but
  optional. Without it, raw byte concatenation of OpenAI MP3 chunks
  works in practice with minor seam artefacts on strict players.

## Pros and Cons of the Options

### OpenAI Whisper + OpenAI TTS + push-to-talk (chosen)

* Good, because hosted Whisper has no model download.
* Good, because parallel per-sentence TTS gives "feels real-time"
  latency without paying for an always-on stream.
* Good, because the audio quality is dramatically better than Piper.
* Bad, because requires `OPENAI_API_KEY` and internet.

### OpenAI Realtime API

* Good, because best UX quality and lowest latency.
* Bad, because $40-$80 per million audio tokens makes a single
  10-minute museum-kiosk session genuinely expensive.
* Bad, because requires WebSocket plumbing that doesn't fit
  Streamlit cleanly.

### Keep faster-whisper + Piper (all local)

* Good, because free per call after model download.
* Bad, because cold-start UX is poor (1.5 GB download).
* Bad, because Piper Ryan-high mangles Tagalog ornaments.
* Bad, because OS-specific binary install across operators.

### Mix: OpenAI TTS + local Whisper

* Good, because keeps STT local (privacy + zero per-call cost).
* Bad, because keeps the cold-start UX problem.
* Bad, because two-provider strategy without proportional benefit.

### Mix: OpenAI Whisper + Piper TTS

* Good, because hosted STT solves cold start.
* Bad, because keeps the Tagalog mispronunciation.
* Bad, because keeps the platform-specific Piper install.

### Anthropic-only via partner TTS

* Good, because single billing relationship.
* Bad, because Anthropic doesn't ship STT or TTS; introducing a
  third provider (e.g., Eleven Labs) adds complexity without
  cost savings vs OpenAI.

## Cadence tuning — voice match for CJP's speech pattern

Two settings in `app/voice_io.py` were tuned together so OpenAI's
`onyx` voice approximates CJP's measured judicial cadence rather than
defaulting to news-anchor pace:

1. **Speed: `0.80` (80% of normal)**, set via `TTS_SPEED_DEFAULT`.
   CJP speaks at a relaxed pace; OpenAI's recommended sweet spot is
   `0.80-0.85`. Below `0.80` the voice starts to drag; above `0.90`
   the deliberation is lost. Override via `OPENAI_TTS_SPEED` in
   `.env`. (Earlier drafts of this ADR used `0.82`; the user tuned
   it to the floor of the recommended range to match CJP's pace.)

2. **Reflective ellipses**, injected by `add_reflective_pauses()`
   before sentence chunking. The function replaces a comma after each
   of CJP's signature reflective markers with an ellipsis, so the
   TTS engine takes a longer breath there. Markers covered:

   - *In my humble opinion,*
   - *In my view,*
   - *In my respectful view,*
   - *With due respect,*
   - *Au contraire,*
   - *IMHO,*
   - *In conclusion,*
   - *More importantly,*
   - *That said,*
   - *Indeed,*
   - *Allow me to say,*
   - *Permit me to say,*
   - *As I have said before,*
   - *As I have written,*

   Each becomes `<marker>...` — a longer reflective pause than the
   comma-only natural pause. The list is intentionally conservative
   (only well-known CJP markers); arbitrary text isn't modified.

The sentence chunker's `_SENTENCE_END` regex was updated with a
negative-lookbehind `(?<!\.\.)` so it does NOT split on the third
period of an ellipsis — the reflective pause stays within its chunk
and reaches OpenAI TTS intact.

To smoke-test cadence changes without API spend:

```python
from voice_io import add_reflective_pauses, sentence_chunks
text = "The rule of law, in my humble opinion, matters. Au contraire, we must…"
print(add_reflective_pauses(text))
for c in sentence_chunks(add_reflective_pauses(text)): print(c)
```

## More Information

- Implementation: `app/voice_io.py`.
- Voice-loop pricing snapshot above is also reproduced in the
  dashboard's sidebar diagnostic.
- For the kiosk deployment, see
  [PLAN-0006](../implementation-plans/PLAN-0006-voice-tts-integration.md)
  — which now needs a small update to note that the kiosk's offline
  fallback path remains faster-whisper + Piper, but online operation
  uses this OpenAI stack.
- Related ADRs:
  [ADR-0006](0006-local-stt-faster-whisper.md) and
  [ADR-0007](0007-local-tts-piper-ryan-high.md) document the prior
  local choices and are now superseded for the online path; both
  remain accepted as the **offline fallback** for any future
  air-gapped deployment.
