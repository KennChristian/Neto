# PLAN-0008 — Wake Word, Milestone 1 (detection only)

Handoff spec for Claude Code. Scope is **Milestone 1 only**: get the kiosk to wake on
"hey cj" / "hey cjp" and route the captured question into the existing pipeline.
Milestone 2 (automatic end-of-question detection / endpointing) is a **separate, later**
handoff — do not build it here.

> Suggested home in the repo: `docs/implementation-plans/PLAN-0008-wakeword-milestone-1.md`
> (matches the existing PLAN-000X convention). This work also warrants a new ADR for the
> engine choice and a `CLAUDE.md` update — see §8.

---

## 0. How to use this doc

1. Read, in order: `docs/handover_claude_code_2026-05-31.md`, then `CLAUDE.md`, then
   `REPO_MAP.md`, then this file.
2. Read the **actual** `app/app.py` and `app/voice_io.py` before writing any code.
3. Read the **actual** openWakeWord API from its own docs/source before writing against it —
   do NOT guess function names or signatures.
4. Work the tasks in §6 in order. Stop at the check-in points. Keep a running progress file
   (§8) so a fresh session can resume.

---

## 1. Context primer

This is a museum-kiosk persona of retired PH Chief Justice Artemio Panganiban. Architecture is
DCI (Direct Corpus Injection) — no RAG/embeddings. The live runtime is just three files:

- `app/app.py` — Streamlit kiosk UI + pipeline orchestration (`_run_pipeline`).
- `app/cj_chat.py` — pipeline library (STT scope gate, router, context, composer, fidelity). **Do not modify** (see §5).
- `app/voice_io.py` — OpenAI Whisper STT + tts-1 TTS.

Current per-turn flow (unchanged by this work downstream of capture):
`st.audio_input` (browser MediaRecorder) → user taps stop → WAV bytes → hash-of-bytes guard
(`app/app.py:1332-1351`) → `_run_pipeline(audio_bytes, …)` (`app/app.py:1012`) →
STT → input_gate → route → build_context → compose (stream) → fidelity → TTS → autoplay.

---

## 2. What we are building (Milestone 1 scope)

Add a wake-word gate **in front of** the existing record flow:

- **Engine:** openWakeWord. (Picovoice Porcupine is a *contingency only* — adopt it **IF and
  only IF** openWakeWord proves lackluster in testing. Do **not** build Porcupine now.)
- **Wake phrase:** "hey cj" primary; the same model is trained to also fire on "hey cjp".
- **Training:** Rung 1 — a quick custom synthetic model (see §6 Task 1). Start with a STOCK
  model first (Rung 0) purely to prove the audio plumbing.
- **State machine:** `SLEEPING → (wake detected) → LISTENING → ANSWERING → SLEEPING`, with a
  timeout from LISTENING back to SLEEPING if no question arrives.
- **End-of-question:** NOT solved here. For Milestone 1 the question-capture is ended by a
  **manual control** (a plain stop button). Milestone 2 replaces that with voice-activity
  endpointing. This is a deliberate placeholder.

Out of scope: endpointing/VAD, Reachy robot SDK integration, Porcupine, any pipeline changes.

---

## 3. THE KEY ARCHITECTURAL DECISION — resolve this first

**Problem:** the current app captures audio in the **browser** via `st.audio_input`
(`app/app.py:1243`). Python never holds a live microphone stream — it only receives finished
WAV bytes. openWakeWord needs a **continuous** Python-side audio stream (80ms / 16kHz frames).
So there is nothing to feed it today. This must be designed before anything else.

Two viable approaches:

- **(A) Python-side continuous capture — RECOMMENDED.** Capture the mic in Python
  (e.g. `sounddevice`/`pyaudio`) on a background thread, feed frames to openWakeWord, and
  signal the Streamlit app on detection. **Why recommended:** it aligns with the robot future —
  on Reachy Mini the audio will come from the Reachy SDK *in Python*, not a browser. Building
  the wake module to consume a generic Python audio source means the laptop (`sounddevice`) and
  the robot (Reachy SDK) are the same code behind one interface. Keeps the wake logic portable.
- **(B) Browser-side wake** via an openWakeWord WASM custom Streamlit component. Matches the
  current browser-audio model, but requires JS/custom-component work and **does not port to the
  robot** (no browser on the Pi). Not recommended.

**Decision: go with (A).** Build the wake module behind a clean audio-source interface (the
"I/O seam") so the source can later swap `sounddevice → Reachy SDK` without touching wake logic.

**Known challenge to handle (don't hand-wave):** Streamlit reruns the script top-to-bottom on
every interaction. A continuous background capture/detection thread must persist across reruns
(hold it in `st.session_state` or a module-level singleton; bridge detection→UI via a flag,
`threading.Event`, or a queue). Confirm this works in Task 0 before building on it.

---

## 4. Milestone 1 interaction flow (given approach A)

Note from the repo map: there is only **one** button today — `st.audio_input` is a single
browser toggle that Python cannot trigger programmatically. So Milestone 1 moves question
capture to the Python side:

1. **Activate gesture (one-time):** keep/honor a single "Activate kiosk" user gesture
   (REPO_MAP Seam A, `app/app.py:1300`) — browsers still require a prior user interaction for
   audio autoplay of the *response*.
2. **SLEEPING:** openWakeWord listens on the Python audio stream.
3. **Wake detected** ("hey cj"/"hey cjp") → **LISTENING:** Python begins capturing the question
   audio from the same stream. Show a visible "listening" state.
4. **Stop (Milestone 1 placeholder):** a plain `st.button("Stop")` (Python-readable, unlike
   `st.audio_input`) ends capture. (Milestone 2 will replace this with VAD endpointing.)
5. Captured audio is encoded to WAV `bytes` and fed into the **existing funnel** — preserve the
   hash-of-bytes guard, then call `_run_pipeline(audio_bytes, left_progress, right_progress)`.
   Do not duplicate or modify the pipeline.
6. **ANSWERING:** existing STT→…→TTS runs untouched → autoplay → **SLEEPING**.
7. **Timeout:** if no audio is captured within N seconds of waking, return to SLEEPING.

Single entry point to protect: `app/app.py:1332-1351`. The wake path must produce
`audio_bytes: bytes` and go through this funnel (or call `_run_pipeline` with the same args).
The MD5 hash guard at `app/app.py:1335` MUST survive — without it, reruns re-fire the pipeline.

---

## 5. Guardrails — MUST NOT change

- **Do not modify `app/cj_chat.py`.** Its system prompts rely on Anthropic prompt caching; the
  bytes must stay identical between turns. All wake work is *upstream* of `cj_chat.input_gate`.
- **Do not modify** `corpus/voice/voice_card.md`, `router_prompt.md`, or `topic_map.json` (same
  prompt-cache reason).
- **Preserve** the hash-of-bytes guard (`app/app.py:1335`) on any new audio source.
- **Do not break the existing browser-record path while developing.** Build the wake path in
  parallel and keep the current path working as a fallback until the wake path is proven, then
  switch over. The kiosk must never be left non-functional between sessions.
- **Python version:** the app's venv is 3.10/3.11. Python 3.12 breaks legacy audio pins. Install
  openWakeWord into the existing `app/.venv` if compatible; if it pulls conflicting deps, isolate
  it and document the boundary — do not silently upgrade the app's environment.
- **Read before writing:** the real openWakeWord API, and the real `app/app.py` / `voice_io.py`.
  No invented signatures.

---

## 6. Tasks (in order; check in at the marked points)

**Task 0 — Plumbing / de-risk (STOCK model, no pipeline).** Prove approach A end to end:
Python continuously captures the mic via `sounddevice`, feeds openWakeWord a STOCK model
(e.g. "hey jarvis"), and on detection flips a visible flag in the Streamlit UI — surviving
Streamlit reruns. No "Hey CJ", no pipeline yet.
> ✅ Check: say the stock word → a visible state change in the running app. **CHECK IN HERE**
> before proceeding — this validates the riskiest assumption.

**Task 1 — Rung 1 custom model.** Train a custom "hey cj" model using openWakeWord's synthetic
(Piper TTS) pipeline; include "hey cjp" utterances in the training set so one model fires on
both. Keep the model file in the repo (e.g. `app/wake/models/`).
> ✅ Check: the model detects "hey cj" and "hey cjp" on recorded test clips; rejects unrelated
> speech at a reasonable threshold.

**Task 2 — State machine + Python capture.** Implement `SLEEPING→LISTENING→ANSWERING→SLEEPING`
with the timeout. On wake, start Python-side question capture; a plain `st.button("Stop")` ends
it (Milestone 1 placeholder); produce WAV `bytes`.
> ✅ Check: "hey cj" → listening state → press stop → valid WAV bytes exist in memory.

**Task 3 — Wire to the existing funnel.** Feed the captured bytes through the hash guard into
`_run_pipeline`, without touching `cj_chat.py`. Full loop.
> ✅ Check: say "hey cj", ask a real question, press stop → the real CJ response generates and
> autoplays, exactly as the button flow does today. **CHECK IN HERE.**

**Task 4 — Portability seam + docs.** Ensure the audio source sits behind a clean interface
(`sounddevice` now; a documented stub/seam for the Reachy SDK later). Update `CLAUDE.md` and the
progress file (§8). Add an ADR for the engine choice.
> ✅ Check: swapping the audio source would not require touching wake-detection logic.

---

## 7. Tech-lead lineage note (for the reviewer)

The reviewer specified a stream-based, chunked, sliding-window, callback-on-match design for
wake detection (referencing his real-time stream-processing framework and the RTP
sequence/timestamp/payload model). **This plan implements exactly that** — openWakeWord *is* an
off-the-shelf implementation of that architecture: it ingests the mic **stream**, slices it into
**80ms chunks**, scores a **sliding window** of frames continuously, and fires a **callback**
when the score crosses threshold. We adopt his design and avoid hand-rolling the buffer/window
logic on (eventually) Raspberry Pi hardware — which is the call an experienced stream-processing
engineer would make. The same stream→window→decide pattern recurs in Milestone 2 (VAD
endpointing). No deviation from his architecture, only "library instead of DIY".

---

## 8. Repo memory (so context survives between sessions)

- **Update `CLAUDE.md`** with durable wake-word context: that the kiosk has a wake gate using
  openWakeWord, where the wake module lives (`app/wake/`), and the audio-source-interface seam.
- **Maintain a progress file** — `docs/implementation-plans/PLAN-0008-progress.md` (or a checklist
  at the bottom of this file). After each task, record: what was done, what's next, any decisions
  or surprises. A fresh Claude Code session should be able to resume from it alone.
- **Add an ADR** (e.g. `ADR-0019-wake-word-engine.md`) recording: openWakeWord chosen, Porcupine
  as conditional fallback, "hey cj"+"hey cjp", Python-side capture for robot portability.

---

## 9. Definition of done (Milestone 1)

- Saying "hey cj" or "hey cjp" into the laptop mic wakes the kiosk and starts capturing a question.
- A manual stop ends capture and the existing pipeline returns the real spoken CJ response.
- `cj_chat.py` and the corpus prompts are untouched; the hash guard is intact.
- The wake module is self-contained behind an audio-source interface (laptop now, robot later).
- `CLAUDE.md`, the progress file, and an ADR are updated.
- Endpointing (Milestone 2) is explicitly NOT included.
