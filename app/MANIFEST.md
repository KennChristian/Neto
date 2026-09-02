# app/ — MANIFEST (live robot service, 2026-08-29 layout)

Entry point: `main_voice_robot.py --wake` (systemd `supervaise.service`, venv `app/.venv`).
Sequence + line refs: [../docs/SYSTEM_TRACE.md](../docs/SYSTEM_TRACE.md). Old→new names: [../docs/RENAME_MAP_2026-08-29.md](../docs/RENAME_MAP_2026-08-29.md).

| File | Role |
|---|---|
| `main_voice_robot.py` | boot, wake loop, turn capture/STT/dispatch, gestures + DoA, playback, barge-in, `[trace]` line |
| `speech_streaming.py` | `SentenceSpeaker` — per-sentence TTS one ahead, gapless play, replay wav, caption feeds |
| `speech_engines.py` | STT (`gpt-4o-mini-transcribe`) + TTS (ElevenLabs clone, OpenAI fallback), speed/farewell settings |
| `speech_tempo.py` | tempo normaliser (WSOLA toward session average) |
| `answer_pipeline.py` | corpus artifacts, input gate, router, composer stream, fidelity check |
| `answer_canned.py` | curated + event answers (`../data/entities/canned_answers.json`) |
| `answer_gate.py` | per-sentence / full-answer forbid rules |
| `answer_filler.py` | question-relevant filler line while composing |
| `text_entities.py` | entity dictionary NER correction |
| `text_language_gate.py` | Filipino/English transcript gate |
| `voice_identity.py` | speaker enrolment/verification + voice lock (data in `~/speaker_id/`) |
| `wake_word.py` | openWakeWord detector (`wake/models/hi_see_jap.onnx`) |
| `usage_meter.py` | API usage tally for the dashboard |
| `wake/` | wake model, training scripts, data |
| `requirements.txt` | venv deps |
