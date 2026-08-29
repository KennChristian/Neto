# SYSTEM_TRACE — Reachy Mini "CJ" voice robot (live checkout)

*Written 2026-08-29 from the deployed code in `~/Supervaise-Reachy-Mini-Project-main`
(`app/`, `voice/`) and the dashboard in `~/pi_dashboard/`. Line numbers are
approximate — search for the function name; `app/cj_voice_cloud.py` carries
numbered `# ═══ N. …` section banners that match the sections below.*

**How to trace one turn from the journal:**

```
journalctl -u supervaise -f | grep -E '\[(wake|ask|stt|canned|stream|gesture|stop|trace)\]'
journalctl -u supervaise -g 'trace\]'      # one line per turn with all stage timings
```

Every turn ends with a `[trace]` line, e.g.
`[trace] path=streamed | stt_s=1.8s | compose_s=0.9s | first_audio_s=1.4s | audio_s=12.3s | words=41 | topic=judicial_independence | interrupted=False`
(`path` ∈ `streamed` · `canned` · `event-button` · `whole-answer`).

---

## 0. Effective runtime configuration

Behaviour is decided by `/etc/systemd/system/supervaise.service` + its drop-in
`supervaise.service.d/wakeword.conf`, not by `app/.env` alone.

| Env | Value | Effect |
|---|---|---|
| `CJ_WAKE_BACKEND` | `openwakeword` | `wake_loop` uses `_wake_stream` (on-device, 80 ms frames) |
| `CJ_WAKE_OWW_MODEL_PATH` / `_THRESHOLD` | `hi_see_jap.onnx` / `0.08` | wake model + fire threshold |
| `CJ_STOP_OWW_THRESHOLD` | `0.01` | barge-in (stop phrase) threshold |
| `CJ_STREAM_SPEECH` | `1` | `handle_turn` → `_handle_turn_streaming` (classic path is dead in prod) |
| `CJ_TTS_BACKEND` (app/.env) | `elevenlabs` | `speech_engines.tts_elevenlabs_wav` → `voice/speak.synthesize` |
| `CJ_CANNED_ENABLED` | `1` | curated fast path before any LLM call |
| `CJ_VOICE_LOCK` / `_IDLE_S` / `_THRESHOLD` | `1` / `10` / `0.32` | lock-mode conversation after each wake |
| `CJ_FOLLOWUP_WINDOW_S` | `0` | legacy follow-up loop disabled |
| `CJ_MIC_TRAILING_SILENCE_S` | `1.5` | mic closes 1.5 s after the last word |
| `CJ_MIC_RMS_FLOOR/MULT/CAP` | `250 / 3.0 / 1500` | speech threshold = clamp(noise×3, 250, 1500) |
| `CJ_DYNAMIC_SPEED`, `CJ_SPEED_MAX_STEP`, `CJ_SPEED_MIN/MAX` | `1`, `0.01`, `0.95/1.05` | per-sentence pace: emotion delta, slewed, capped |
| `CJ_STOP_DEBUG_WAV` | `1` | keeps ≤40 s of mic audio per answer in `cj_stop_last.wav` |

---

## 1. BOOT — `main()` (banner 10)

1. Import-time side effects: `.env` loading (`answer_pipeline`), `speech_engines` defaults, **mic device pick** (`sd.default.device = reachymini_audio_src_plug`), `_speaker_doa = _SpeakerDoA()`, `_SENT_OUT = _SentenceOut()`.
2. `CorpusArtifacts()` — topic map, voice card, router prompt (35 topics).
3. `make_client()` — Anthropic client (fails fast if `ANTHROPIC_API_KEY` missing).
4. `Gestures()` — `ReachyMini(media_backend="no_media")`, `enable_motors()`, then `_speaker_doa.start()`; sets `_gestures_inst`.
5. `gestures.neutral()`; `print("Ready.")`; **`prewarm_boot()`** — daemon thread imports `speech_streaming`, `voice.speak` (~4 s) and loads the entity dictionary (~0.9 s) so the first answer pays nothing.
6. `--wake` → `wake_loop()`.

`wake_loop()` arming: `wake_word.make_detector()` → `OpenWakeWordDetector._load()` (model resident), `gestures.scan()`, `[wake] armed`, `StopWord(detector, threshold)` shares the same model.

---

## 2. IDLE — `_wake_stream()` (banner 9)

One `_MicTap` (always-open `sd.InputStream`, callback-fed queue, RMS history for the noise floor). Per 80 ms frame, in order:

| # | Check | File / trigger | Behaviour |
|---|---|---|---|
| 1 | `/dev/shm/cj_ask_trigger` (< 30 s old) | `/event` buttons | stash `_pending_ask`, return 1.0 (fires a turn without the mic). Not blocked by mic mute. |
| 2 | `/dev/shm/cj_gesture_trigger` (< 10 s) | `/maintain` Mechanical actions | `Gestures.manual(name)` in a thread → `[gesture] name: done` |
| 3 | `cj_wake_trigger` / `cj_enroll_trigger` (< 10 s) | `/maintain` Activate listening / Enroll | return 1.0 / −1.0 |
| 4 | `stream.read()` + `tap.note_rms()` | mic | raises after 2 s of a dead stream → systemd restart |
| 5 | `model.predict(frame)` | openWakeWord | score |
| 6 | score ≥ thr **and `_muted()`** | `/dev/shm/cj_muted` = **mic mute** | logged once, ignored |
| 7 | score ≥ thr | | `_publish_wake(fired=True)`, return score |

`_publish_wake` writes `cj_wake_live.json` every frame (dashboard wake meter).

**After fire** (`wake_loop`): `_run_enrollment` if score < 0 · `_ask_turn` if an ask is pending · else `prewarm_connections()` (TLS to OpenAI/Anthropic/ElevenLabs + entity dictionary, in threads) · `_warm_voice_lock` · `gestures.perk()` (non-blocking, faces the DoA angle) · `_safe_turn()` (+ up to 2 `rewake` retries).

---

## 3. TURN (banners 4 → 8 → 7 → 6)

### 3a Capture — `handle_turn` → `record_with_meter`
`gestures.start("listen")` · stage `transcribe=active` · pre-roll from the tap buffer (the wake phrase itself is skipped) · threshold from the idle noise floor · 30 ms frames until `speech_seen and silence ≥ 1.5 s` → temp wav. The live RMS meter prints only on a TTY (never into journald).

### 3b Voice lock, ack, speaker gate
Lock-mode follow-ups verify the speaker embedding in a background thread (overlaps STT) · `_play_ack()` plays a short acknowledgement clip before STT · first question after a wake → `lock.lock(path)` · optional enrolled-speaker gate.

### 3c STT — `speech_engines.transcribe_openai`
`gpt-4o-mini-transcribe`, language + steering prompt, prompt-echo guard · offline fallback clip · wake-phrase stripping (`rewake` if that's all that was heard) · non-Latin guard · `text_language_gate.check` (Filipino/English) · lock mismatch → `ignored` · `[stt] heard: … (Ns)` · `text_entities.process_transcript` (entity NER) · `_publish_transcript("user")`.

### 3d Dispatch
1. **Farewell** (lock active + bye/thanks) → `speak(..., voice_settings=farewell_settings())` → `"bye"`.
2. **Canned** (`answer_canned.match`; event-mode paraphrases) → `speak()` → `[trace] path=canned`.
3. **Streaming** (`CJ_STREAM_SPEECH=1`) → `_handle_turn_streaming`.
4. Classic non-streaming path below this point is **dead in production**.

### 3e Streaming answer — `_handle_turn_streaming` → `speech_streaming.stream_turn`
`play_filler()` + `answer_filler.start()` (Haiku one-liner while composing) · gate + router run in parallel (Haiku) · `identity_probe` / `out_of_corpus` short-cuts · composer stream (Sonnet) → `split_ready()` sentence splitter → `answer_gate.check_answer(forbid_only=True)` → `SentenceSpeaker.add()` · async fidelity audit during playback · `speaker.finish()` blocks until playback drains · `[stream] first audio Ns after transcript`.

### 3f `SentenceSpeaker` (`app/stream_speak.py`)
- `add(sentence)`: classify emotion **once** (`_emos[idx]`), speed = `smooth_speed(emotion_speed(emo), prev)` (≤0.01 step, 0.95–1.05), submit `_synth` to a 2-worker pool (one sentence ahead), start `_play_loop`, register `_prefeed`.
- `_synth`: `process_tts_sentence` → `speech_engines.tts_elevenlabs_wav(text, speed, previous_text)` → wav path (**no ffmpeg**; the OpenAI fallback still transcodes its mp3).
- `_play_loop`: first-audio hook → gesture style → alignment sidecar → `publish_speaking` (`cj_speaking.json`, captions + word timing + `next` prefeed) → `play_fn(wav)` → **`_replay_append(wav)`** (raw PCM into `cj_last_answer.wav.tmp`) → unlink.
- `finish()`: join player, discard unplayed synths, `_replay_finish()` → `/dev/shm/cj_last_answer.wav` (dashboard **Replay** plays it with `aplay`, no decode).

### 3g TTS — `speech_engines.tts_elevenlabs_wav` → `voice/speak.synthesize`
Cache key = SHA256(normalized text + voice + model + `voice_settings`) in `~/.voice_cache/` (hit: read + copy to `/dev/shm`; miss: `eleven_flash_v2_5`, `pcm_24000`, `previous_text[-400:]`, retries on 5xx, then `voice.audio.process` (HPF, presence, −16 LUFS), cache put, word alignment sidecar). Base `VOICE_SETTINGS` in `voice/config.py` (stability .50, similarity .75, style 0, speed 1.0); farewells override to .30/.50/0.97.

### 3h Playback — `_play_wav_listener` / `_SentenceOut` / `StopListener`
One persistent `sd.OutputStream(device="audio_out_route")` for the whole answer (gapless, 150 ms inter-sentence gap, keep-alive silence) · `StopListener` = one mic stream + one warmed openWakeWord model spanning the answer; per frame: `cj_mute_trigger` (Interrupt button) cuts, stop-phrase score ≥ thr **and not mic-muted** cuts · `speak()` (canned/farewell/event) uses `_play_wav_interruptible` instead.

### 3i Back to idle — `wake_loop`
Lock-mode conversation (`[lock] in conversation …`): `perk` → `_safe_turn(followup=True, listen_s=remaining)` until 10 s quiet, `bye`, interrupt, or mic mute → `lock.release()` · `gestures.neutral()` · `[wake] re-armed`.

---

## 4. `/dev/shm` relay contract (app ⇄ dashboard)

| File | Writer → Reader | Purpose |
|---|---|---|
| `cj_wake_live.json`, `cj_wake_events.jsonl` | app → dashboard | wake meter + fire journal |
| `cj_stop_live.json`, `cj_stop_events.jsonl`, `cj_stop_last.wav` | app → dashboard/operator | stop meter, fire journal, last mic trace |
| `cj_wake_trigger`, `cj_enroll_trigger` | dashboard → app | Activate listening / Enroll voice (touch; < 10 s) |
| `cj_ask_trigger` | dashboard `/event` → app | `{"q","a","id"}` scripted answer (< 30 s) |
| `cj_gesture_trigger` | dashboard `/maintain` → app | `{"g": name}` mechanical action (< 10 s) |
| `cj_gestures_off` | app (idle-off / motors-off) | idle & talk motion frozen while present |
| `cj_muted` | dashboard Mute mic ⇄ app `_muted()` | **mic** mute: wake + stop phrase ignored, robot still speaks |
| `cj_mute_trigger` | dashboard Interrupt → app | one-shot: cut the current answer |
| `cj_transcript.jsonl`, `cj_turn_meta.jsonl`, `cj_stage.json` | app → dashboard | transcript feed, per-turn internals (topic, budget, docs, timings, cost, WPM), pipeline tracker |
| `cj_speaking.json`, `cj_sent_<ms>.wav`, `cj_aside.json` | app → `/audience`, `/face-avatar` | captions + word timing, per-sentence audio, ack/filler asides |
| `cj_last_answer.wav` | app → dashboard Replay | whole voiced answer (raw PCM concat) |
| `cj_voice_lock.json`, `cj_speaker_last.json` | app → dashboard | lock state, speaker gate |
| `cj_avatar_audio`, `cj_avatar_lag`, `cj_avatar_page.json`, `cj_avatar_cmd.json` | dashboard/avatar page ⇄ app | avatar heartbeat/mode, measured lag, page control channel |
| `cj_answer_gate.jsonl`, `cj_postproc_corrections.jsonl` | app → dashboard | audit logs |

Dashboard `/api/action` is fire-and-forget (`{"queued":true,"id":N}` → poll `/api/action/status?id=N`); `/api/ctl` actions (mute/unmute/interrupt/gesture-*/replay/…) are immediate.

---

## 5. Log tags → stage

| Tag | Stage |
|---|---|
| `[mic]` | device pick, noise floor, end of speech |
| `[gestures]` `[doa]` `[gesture]` | body: connect, speaker direction, per-sentence style + manual actions |
| `[wake]` `[mute]` | idle / arming / fire / re-arm; mic-muted wake ignored |
| `[ask]` | event-button turn |
| `[prewarm]` | boot warm-up, wake-fire connection warm-up |
| `[lock]` `[speaker]` | voice lock conversation mode, enrolled-speaker gate |
| `[stt]` `[postproc]` | transcription and entity correction |
| `[canned]` `[answer-gate]` `[dynfiller]` `[filler]` | pre-composer fast paths, gate, fillers |
| `[stream]` `[stream-speak]` `[fidelity]` | routing/compose timings, per-sentence synth/replay, async audit |
| `[tts]` `[audio]` `[stop]` | engine fallback, output device, barge-in |
| `[meta]` `[trace]` | maintenance feed; **one-line per-turn timing summary** |

---

## 6. Known dead / duplicated code (left in place, documented)

- Classic non-streaming turn in `handle_turn` (after the `CJ_STREAM_SPEECH` return), `_wake_windows`, `wake_word.wait_for_wake` / `MicAudioSource` / `SttKeywordDetector`, `run_hands_free_loop`, the legacy follow-up loop, `--auto` mode — unreachable under the deployed env.
- ~60 % of `voice/speak.py` (`speak()`, host/robot playback, espeak fallback) — the app imports only `synthesize` / `effective_settings`.
- `app/app.py`, `app/dashboard.py`, `app/wake_test.py` — not imported by the service.
- Duplicated helpers: `_publish_wake`/`_publish_stop`; four wav-duration readers; canned speak+publish block in `handle_turn` vs `_ask_turn`; turn-meta block in both turn paths; avatar mode/lag helpers in app and dashboard.
- Backups of every edited file live in `_backups/` (app, voice) and `~/pi_dashboard/_backups/`.

## 7. Changes made on 2026-08-29 for speed / traceability

- Per-sentence `ffmpeg` mp3 (0.75 s each on the CM4, inside the synth path) removed; Replay uses a raw-PCM wav concat.
- `prewarm_boot()` — heavy imports + entity dictionary at boot (first answer synth 0.72 s → 0.27 s).
- Emotion classified once per sentence; wav duration read once; mic meter no longer floods journald.
- `[trace]` line per turn; section banners in `main_voice_robot.py`.
- Dashboard: HTTP/1.1 keep-alive, 500 ms state poll, fire-and-forget actions.
- Sentence tempo smoothing (`app/tempo_smooth.py`, called from `SentenceSpeaker._synth`): rate from the word alignment → WSOLA stretch ≤6 % toward a session-wide EMA (`/dev/shm/cj_tempo_avg.json`); opener never stretched; `[tempo]` log lines. ElevenLabs request stitching via `previous_request_ids` (voice/speak.py → speech_engines → SentenceSpeaker._rids).
