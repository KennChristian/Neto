# PLAN-0006: Voice / TTS integration for the FLP Museum hub deployment

* Status: draft
* Phase: 8 (post-launch)
* Owner: TBD
* Depends on: [PLAN-0001](PLAN-0001-runtime-app-haiku-router-sonnet-composer.md)
  (runtime working), [PLAN-0002](PLAN-0002-web-chat-ui.md) (or a kiosk
  surface)
* Verified by: manual UX walkthroughs at the FLP Museum (when
  installed) plus latency benchmarks
* Related ADRs:
  [0005](../decisions/0005-defer-robot-embodiment-for-may-30.md)
  (deferring robot embodiment for the May 30 demo),
  [0006](../decisions/0006-local-stt-faster-whisper.md) (STT decision —
  already in place for operator dashboard),
  [0007](../decisions/0007-local-tts-piper-ryan-high.md) (TTS decision —
  already in place for operator dashboard)

## 1. Goal

Extend the conversation app from a chat surface (chat-only per
PROJECT.md §1) to a **voice surface** suitable for the Foundation for
Liberty and Prosperity's planned Museum for Liberty and Prosperity
kiosk. The end-state is a visitor speaking aloud, receiving an
audible CJP response, optionally with a robot-embodied front-end.

This plan is **post-launch** — the May 30, 2026 demo is chat-only
([ADR-0005](../decisions/0005-defer-robot-embodiment-for-may-30.md)).
The plan exists so the team knows where voice fits in.

**Stack locked**:
- STT — `faster-whisper`
  ([ADR-0006](../decisions/0006-local-stt-faster-whisper.md)).
- TTS — Piper with the `en_US-ryan-high` voice
  ([ADR-0007](../decisions/0007-local-tts-piper-ryan-high.md)).
- UI — Streamlit (operator + end-user share the same deployment per
  [ADR-0008](../decisions/0008-streamlit-dashboard-operator-ui.md)
  and [ADR-0017](../decisions/0017-end-user-ui-also-streamlit.md)).
  Voice widgets live in the same Streamlit page as the chat textarea.

## 2. Scope

**In scope**
1. Production-grade STT for kiosk use — `faster-whisper` is the
   chosen STT
   ([ADR-0006](../decisions/0006-local-stt-faster-whisper.md));
   confirm it scales to public usage patterns. No alternatives
   evaluated for kiosk — Whisper is locked.
2. Production-grade TTS for visitor audio — Piper with
   `en_US-ryan-high` is the chosen TTS
   ([ADR-0007](../decisions/0007-local-tts-piper-ryan-high.md)).
   *Filipino-accented English* suitability is accepted; PLAN-0006 §4
   discusses the Tagalog-ornament rendering trade-off.
3. Latency budget specifically for the voice loop (target ≤4s end-
   to-end from voice-end to first audio).
4. Tagalog code-switching in TTS — Piper Ryan-high is English-only;
   need a Tagalog fallback voice or a code-switching synthesiser.
5. Wake-word or push-to-talk affordance.
6. Acoustic environment: museum hub is noisier than an office;
   microphone array + noise gate spec.

**Out of scope (this plan)**
- Reachy Mini robot embodiment integration — see
  [ADR-0005](../decisions/0005-defer-robot-embodiment-for-may-30.md).
  The robot is its own plan when the time comes.
- Visual avatar.
- Hardware procurement and installation logistics (FLP project
  management).

## 3. Workstream A — Voice-pipeline shape

```
Visitor speech
  → microphone (noise gate + VAD)
  → STT (faster-whisper)
  → text input (same as chat surface)
  → runtime (PLAN-0001 pipeline)
  → response text
  → TTS (Piper)
  → audible response
```

Each stage gets its own latency budget; total target ≤4s
(STT 1s + LLM 2-3s + TTS 0.5s + buffer 0.5s).

## 4. Workstream B — Tagalog code-switching in TTS

The voice card permits *short* Tagalog ornaments at warm moments
(*"Maraming salamat po"*, *"Susmaryosep!"*, *"Abangan!"*). Piper
Ryan-high will pronounce these as English approximations — which is
acceptable for a Filipino-bilingual audience reading "Maraming
salamat po" as Tagalog-by-context, but flat compared to native
pronunciation.

Two options:

1. **Accept English-flavored Tagalog.** Cheaper; matches the
   English-primary register of the voice card.
2. **Hybrid TTS** — detect Tagalog tokens and route those through a
   Tagalog Piper voice (one exists for some Philippine languages, may
   require search). English back to Ryan-high. Mid-utterance voice
   switching introduces seams.

Recommendation: Option 1 for v1; evaluate Option 2 if visitor
feedback flags it.

## 5. Workstream C — Acoustic environment

Museum hubs are noisier than offices (visitor chatter, ventilation,
adjacent exhibits). The mic + VAD chain needs to:

1. Reject background speech (e.g., other visitors a meter away).
2. Recover from talk-over (interruption handling — does the visitor
   stop the response by speaking?).
3. Handle accented and varied speaking speeds.

Recommendation:
- Beam-forming directional microphone aimed at the visitor stance.
- Push-to-talk affordance (physical button or floor-mat) for
  unambiguous "start listening".
- Visual "I'm listening" / "I'm speaking" indicators.

## 6. Workstream D — Identity disclosure in voice

The voice surface must preserve the honesty rule. Implementation:

1. **First-utterance auto-greet** when a new visitor approaches
   (motion sensor or push-to-talk activation):
   *"Hello, I am an AI conversation robot built by the Foundation
   for Liberty and Prosperity. I speak with the voice of Chief
   Justice Panganiban — drawn from his speeches, columns, and
   writings. What would you like to ask me?"*

2. **Periodic re-disclosure** every N turns (e.g., 5) so visitors who
   join mid-session hear the framing.

3. **Identity-probe responses** (when visitor asks *"is this real?"*)
   trigger the META path same as chat.

## 7. Failure modes

| Failure mode | Detection | Response |
|---|---|---|
| Mic input timeout (visitor walks away mid-question) | VAD silence threshold | Reset; idle state |
| STT confidence below threshold | Whisper confidence score | Audible "I didn't catch that — could you repeat?" |
| TTS synthesis fails | Per-call error | Display response on screen instead |
| Background noise spike during response | Audio level monitor | Pause + resume; show subtitle |
| LLM hangs >budget | Per-call timeout | Fall back to a short pre-recorded "Let me think — please give me a moment" |
| Power / network outage | Healthcheck | Visible offline indicator; queue restart |

## 8. Edge cases

- **Multiple visitors take turns rapid-fire.** Memory layer: clear
  on idle-timeout to avoid one visitor's question polluting the
  next.
- **Child visitor.** Voice card's register selection is
  age-agnostic; CJP's natural register is courteous and intelligible
  enough. Reviewer pass required to confirm.
- **Visitor asks in another language.** Out-of-scope; respond *"I'm
  most comfortable in English; would you mind trying again?"*
- **Visitor asks the same question repeatedly.** Memory layer should
  detect and respond with light acknowledgment + same content (not
  the *exact* same wording).

## 9. Acceptance

- End-to-end voice loop ≤4s for typical-length questions.
- Identity disclosure plays on session start; periodic re-disclosure.
- Reviewer pass with 10 simulated visitor questions in a noisy
  environment.
- Per-session cost ≤$0.10 (assumes 2-turn average session).

## 10. Out-of-scope discoveries to surface

- Robot embodiment (Reachy Mini) — its own plan when scoped.
- Multilingual UX — own plan; would substantially change voice card
  and TTS strategy.
- Visitor logging / analytics consent model — privacy plan needed
  for any retention.
