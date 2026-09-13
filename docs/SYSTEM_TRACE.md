# SYSTEM_TRACE — Reachy Mini "CJ" voice robot (live checkout)

*Written 2026-08-29 (module names updated to the renamed layout the same day — see `RENAME_MAP_2026-08-29.md`) from the deployed code in `~/Supervaise-Reachy-Mini-Project-main`
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
| (streaming is the only answer path since 2026-08-29) |
| `CJ_TTS_BACKEND` (app/.env) | `elevenlabs` | `speech_engines.tts_elevenlabs_wav` → `voice/speak.synthesize` |
| `CJ_CANNED_ENABLED` | `1` | curated fast path before any LLM call |
| `CJ_VOICE_LOCK` / `_IDLE_S` / `_THRESHOLD` | `1` / `10` / `0.32` | lock-mode conversation after each wake |
| `CJ_FOLLOWUP_WINDOW_S` | `0` | legacy follow-up loop disabled |
| `CJ_MIC_TRAILING_SILENCE_S` | `1.5` | mic closes 1.5 s after the last word |
| `CJ_MIC_RMS_FLOOR/MULT/CAP` | `200 / 2.5 / 1500` | speech threshold = clamp(noise×2.5, 200, 1500) |
| `CJ_LISTEN_DIRECTION` | `back` | XVF3800 fixed beams parked at 225°/315° chip frame (rear) whenever no voice lock steers them; `auto` = 4 adaptive beams |
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
| `pi_dashboard/assets/liveavatar.json`, `liveavatar_avatar.json` | /maintain → avatar session | which LiveAvatar avatar to open (api_key + avatar_id + sandbox, mode 0600) and its cached name/preview |
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

## 6. Removed / remaining duplication

Removed 2026-08-29 (see `RENAME_MAP_2026-08-29.md`): the classic non-streaming turn, `_wake_windows`, the STT-keyword wake backend, the legacy follow-up loop, `--auto` mode, `voice/speak.py` playback/fallback half, the Streamlit kiosk files (→ `app/legacy/`).

Still duplicated (small, left in place): `_publish_wake`/`_publish_stop`; four wav-duration readers; canned speak+publish block in `handle_turn` vs `_ask_turn`; turn-meta block in both turn paths; avatar mode/lag helpers in app and dashboard.

## 7. Changes made on 2026-08-29 for speed / traceability

- Per-sentence `ffmpeg` mp3 (0.75 s each on the CM4, inside the synth path) removed; Replay uses a raw-PCM wav concat.
- `prewarm_boot()` — heavy imports + entity dictionary at boot (first answer synth 0.72 s → 0.27 s).
- Emotion classified once per sentence; wav duration read once; mic meter no longer floods journald.
- `[trace]` line per turn; section banners in `main_voice_robot.py`.
- Dashboard: HTTP/1.1 keep-alive, 500 ms state poll, fire-and-forget actions.
- Sentence tempo smoothing (`app/tempo_smooth.py`, called from `SentenceSpeaker._synth`): rate from the word alignment → WSOLA stretch ≤6 % toward a session-wide EMA (`/dev/shm/cj_tempo_avg.json`); opener never stretched; `[tempo]` log lines. ElevenLabs request stitching via `previous_request_ids` (voice/speak.py → speech_engines → SentenceSpeaker._rids).
- Hallucination guards (evening): `GROUNDING_RULE` in the composer prompt (`answer_pipeline.generate_response_stream`); pre-TTS **fact gate** in `speech_streaming._add_gated` — deterministic `answer_gate.fact_check` (years absent from context/question/persona-core corpus block; unverified quoted titles logged, `CJ_FACT_GATE_TITLES=block`) then `answer_pipeline.sentence_fact_audit` (Haiku, ~1.2 s) for fact-bearing sentences (`_FACT_TRIGGER`: years, 3+ digit numbers, counts, quoted titles); unsupported → sentence dropped, `[fact-gate] … BLOCKED`. Env: `CJ_FACT_GATE`, `CJ_FACT_AUDIT` (both default on).
- (LED ring idea withdrawn the same evening: the Reachy Mini audio board has no LEDs — the XMOS registers exist but nothing is populated. Mic-muted is shown by posture instead: antennas drooped + head bowed while `cj_muted` exists, `Gestures.start("sleep")`.)
- Filler glossary in `answer_filler._SYSTEM` (ACID, APJR, FLP, JBC, ICC, EEZ, EDSA, …). `/maintain` quick-status strip (mic · speaker route · app · internet · camera · event mode · last-turn timings · tempo) + "Reset voice tempo" (`/api/ctl tempo-reset`); `state.audio_route`, `state.tempo_avg`.
- XVF3800 live dump 2026-08-29 (`audio_control_utils.py PARAM` in `/venvs/mini_daemon`): PP_DTSENSITIVE=1, PP_AGCONOFF=1 (desired 0.0045, max gain 64), PP_MIN_NS=0.15, PP_NLAEC_MODE=0, PP_ECHOONOFF=1, PP_NLATTENONOFF=1, AUDIO_MGR_OP_L/R=8, MIC_GAIN 90, REF_GAIN 8, SYS_DELAY 12, fixed beams off, LED_EFFECT 4.
- Speed limit: ElevenLabs speed capped at 1.00 (CJ_SPEED_MAX); tempo normaliser only slows, ceiling CJ_TEMPO_RATE_MAX 15 chars/s, up to 10 %.
- 2026-08-30: tempo stretch factor was inverted since creation (fixed: duration × r/target); pace ceiling 13 chars/s (`CJ_TEMPO_RATE_MAX`, /maintain Pace knob); curated clips capped via `speech_tempo.cap_clip` with a stretched-clip cache in `~/.voice_cache/tempo/`.
- 2026-08-30 Phase 1 voice isolation (log-only): `voice_vad.py` (Silero via sherpa-onnx), `_gate_start/_gate_report` → `[gate]` line per utterance; DoA outside the frontal cone → face front (never reject by direction). Dynamic speed widened (0.94–1.03).
- 2026-09-02 ElevenLabs Voice Isolator before STT: added (`_stt_isolate` in `main_voice_robot.py`) and REVERTED the same day per user — the ~2-3 s API round trip per turn wasn't worth it. Findings kept for the record: the isolation API rejects input under 4.6 s (pad with silence), returns MP3, and can never sit in the 80 ms wake loop (whole-file API; wake stays fully on-device). An offline "Isolate voice" button remains in `~/audio-ui.py` for cleaning recordings.
- 2026-09-02 Dual audio output (user: "play the tts through the laptop and the bluetooth speaker"): `~/bin/audio-out laptop|both|dual <a> <b>` — the laptop (LAPTOP-BANC5VFE, paired as an A2DP sink) is a route target, and `both` = Bluetooth speaker + laptop at once. `~/.asoundrc.route` now always defines `audio_out_route` (primary) and `audio_out_route2` (second device, or `type null`) with `# Primary:` / `# Secondary:` headers; `main_voice_robot._dual_route()` reads them, `_aplay_cmd` returns `~/bin/aplay-dual` (plays on both, exit code = primary's, dead second device → `audio-out ensure` drops it) and `_SentenceOut` opens a second PortAudio stream. speaker-watchdog leaves a working manual route alone (laptop / dual) instead of forcing Sony. /maintain: "Route: laptop", "Route: speaker + laptop", laptop connection row. Laptop side untested today (its Bluetooth was off: page-timeout on connect).
- 2026-09-02 Stream-player fix found on the way: on a Bluetooth route the plug pcm reported 1-10000 channels and PortAudio could not grope it, so `audio_out_route` was missing from its device list and EVERY streamed sentence fell back to aplay (journal: "No output device matching 'audio_out_route'"). `audio-out` now writes `slave { ...; channels 2 }` for BlueALSA routes; PortAudio lists `audio_out_route`, `audio_out_route2`, `reachymini_audio_sink`, `default` again.
- 2026-09-02 ElevenLabs Voice Isolator is back behind a switch (user: "a toggle button ... so that we can activate and deactivate it in case there are problems"): `_stt_isolate()` runs only while `~/.cj_stt_isolate_on` exists (the /maintain "Isolator: turn ON/OFF" button; env `CJ_STT_ISOLATE=1` also) — pads to 5 s, MP3 → ffmpeg → 16 kHz wav trimmed back to the capture length, timeout `CJ_STT_ISOLATE_TIMEOUT_S` (8 s), any failure → raw capture; last result in `/dev/shm/cj_isolate_last.json` (shown on /maintain). Measured 2.7 s for a 4.8 s clip.
- 2026-09-02 Video clip sound/picture sync (user: "merge it well especially in the video"): with sound on the robot the /face-avatar page used to start the picture a fixed 350 ms after posting `video-audio-go`, but on the Sony route aplay needs ~1.1 s to open the BlueALSA device (measured; ~0.25 s on PipeWire). `_video_audio_start` (pi_dashboard/ui_common.py) now runs `aplay -v`, blocks the go request until aplay's param dump ("boundary") = device ready, and answers `lead_ms` (route base internal 120 / Bluetooth 320 ms + operator offset in `~/.cj_video_lead`, the /maintain Video clips "Sync" box, `video-lead-<ms>`); the page starts the picture that long after the reply. Video audio is tee'd to `audio_out_route2` on a dual route. /api/ctl handlers may return a dict (extra JSON fields).
- 2026-09-02 "why is the speaker late": measured turn 05:21 — capture 7.7 s for 3.1 s of speech (pre-roll + 1.2 s trailing silence), STT 7.0 s of which the Voice Isolator (switched ON at the time) took 3.9 s, first composer token 3.7 s, first answer audio 7.3 s after the transcript (dynamic filler bridged at 3 s). Per-clip start overhead: PipeWire ~0.23 s, Bluetooth 0.45-0.9 s (open + A2DP drain).
- 2026-09-04 Avatar swap + state indicator (user: "can we switch to another avatar that I made through liveavatar then also update the UI add the Idle, Speaking, and etc"). **Swap**: the avatar id was hardcoded in `ui_page_face.avatar_session()` (`dd73ea75…` = LiveAvatar's stock "Wayne"); it is now an operator field in the /maintain "LiveAvatar page" card. `POST /api/avatar-conf` (its own endpoint, not `/api/ctl`, because the body may carry an API key and every ctl action is printed to the journal) validates the id with `GET /v1/avatars/{id}` before writing `assets/liveavatar.json`, so a typo is refused instead of leaving the exhibit with a face that will not start; the resolved name/status/preview/voice are cached in `liveavatar_avatar.json` and surfaced through `state().avatar_conf` (file reads only — state() is polled ~3×/s). Applying posts a new `avatar` page command: the /face-avatar page drops its cached `cjap_still`, parks, and opens one session to capture the new portrait. Note `GET /v1/avatars` returns count 0 for this API key (tried `avatar_type=public|private|custom`, `space_id`, paging), so the card cannot offer a picker list — the id has to be pasted from the LiveAvatar dashboard. The key field is there because a custom avatar on another account needs that account's key.
- 2026-09-04 **State indicator**: /audience already had the Idle / Listening / Thinking / Speaking / Mic-muted pill; its CSS, markup and JS moved out of `AUDIENCE_PAGE` into the shared `EXHIBIT_CSS` / new `EXHIBIT_PILL` / `EXHIBIT_JS`, so /face-avatar now shows the identical pill from the same `setState()` rules (`?pill=off` hides it). /maintain's avatar card gained state chips from the existing `robotMode()` — page · idle|listening|thinking|speaking|muted · voice mode · measured lag — so all three views read the same. Two bugs found while testing: (a) `applyCmd`/`applyVideoCmd` primed `lastCmdTs` on the first *command* rather than the first *poll*, so the first avatar/stop/resume/voice/video command after a reboot (no `/dev/shm/cj_avatar_cmd.json` yet) was silently swallowed; (b) `avatar_status_put` stringified `lag: null` into the text `"None"`. Both fixed.
- 2026-09-04 Custom-avatar swap attempt (`0c62adc0-68be-4d8c-88f1-191857f21fde`) — **blocked, not applied**. LiveAvatar returns two separate reasons for it: *"You dont have access to this avatar"* (the key stored on the robot, `ec8c63…e519`, belongs to space `e0d30fe74d924d2cb5bfa492068b9904` — the custom avatar was made in a different account/space) and, in sandbox only, *"This avatar is not supported in sandbox mode"* — **custom avatars need production mode**, `is_sandbox: false`. The stored key does have production rights (a production token for Wayne is issued fine), so the missing piece is the owning account's API key. Consequence for the validator: a catalogue hit (`GET /v1/avatars/{id}`) is not proof an avatar can be used, so `avatar_conf_set` now gates on a `POST /v1/sessions/token` dry-run with the chosen sandbox flag (a token is not a started session — nothing is billed) and reports LiveAvatar's own messages, adding "untick sandbox" / "paste the owning account's key" hints. An avatar that is usable but absent from the key's catalogue is still accepted, with the name left blank until ⟳.
- 2026-09-04 Avatar view presets (user: "make the avatar full" → "or make a button for flexibility"). The custom avatar's video is 1920×1080, but /face-avatar rendered it in a 9:10 box with `object-fit:cover`, cropping ~half the frame width. Rather than pick one size, /maintain's LiveAvatar card gained a **View** row: `framed` (the original 9:10 exhibit portrait), `wide` (16:9 window, `contain` — the whole frame) and `full` (edge to edge, `cover`). `avatar-view-<v>` writes `~/.cj_avatar_view`; the page reads `state().avatar_view` on its normal poll and toggles `#cam.v-wide` / `.v-full` — no command channel, so a reloaded page and a rebooted robot come back in the chosen view. Set to `full`.
- 2026-09-10 **Operator console for the two-robot installation** (`/console?key=cjap` on the port-8080 dashboard; model `dashboard/console.py`, page `dashboard/ui_page_console.py`, robot side `app/floor_lease.py` + hooks in `main_voice_robot.py`). The maintenance dashboard itself moved into the repo (`dashboard/`, `~/pi_dashboard` is a symlink; its old git history stays local because it has secrets committed). **One invariant**: exactly one microphone open across cj-alpha (Panganiban) and cj-beta (Host) — the *floor* is a single value `alpha|beta|none` held by the console; there is no per-robot mic toggle. **Lease**: robots POST `/api/lease` ~1 Hz with what their mic is actually doing (`observed`) and get the floor + a 3 s TTL; expired lease, unreachable console, fresh boot, unknown role → mic closed (`_MicTap` is opened/closed ONLY by `LeaseClient.on_mic`; the recorder, wake stream and barge-in listeners all ask `_floor_ok()` per frame). **Floor change**: floor→none at once, then the target is named only after both robots report closed after the move began or TTL+0.5 s elapsed (never open-then-close). **Drain**: a floor/mode change during a turn (`_TURN["active"]`, set by `_safe_turn`/`_ask_turn`/host intro) is queued and applied when the turn ends; "Cut short" bumps `interrupt_seq` → robot touches `cj_mute_trigger`. **Modes** duet (floor forced none, floor requests refused) / direct; **profiles** kiosk / event from `config/modes/<mode>.json` (event = wake word off, speech floor 800/cap 2500, post-answer window 0). **Resolution** profile → systemd drop-in → app/.env → console override, per key with source, journaled (`~/.cj_console_journal.jsonl` + stdout) on every change and re-resolved when a source file changes; the effective env rides in the lease reply and lands in the robot's `os.environ` (`_floor_settings`; wake threshold retuned in place). Drop-in keys moved out: `CJ_WAKE_OWW_THRESHOLD`, `CJ_MIC_RMS_*`, `CJ_MIC_TRAILING_SILENCE_S`, `CJ_LISTEN_IDLE_S`, `CJ_VOICE_LOCK_IDLE_S`, `CJ_ALWAYS_LISTEN` (backup `wakeword.conf.bak-console-20260910`); added `CJ_ROBOT_ROLE=alpha` (this unit is still named reachy-cjap) and `CJ_CONSOLE_URL`. New env the robot honours: `CJ_WAKE_LISTEN` (0 = wake phrase scored but never fires), `CJ_LISTEN_IDLE_S=0` (no post-answer window even with a voice lock), `CJ_HOST_INTRO`, `CJ_DRY_RUN` (clips → `sleep <dur>`, streamed sentences → timed silence). **Locked** (shown, not editable; unlock only *requested* with a logged reason): specifics rule, fact audit, year gate, AI-self-description regex gate, corpus grounding. `/api/state` keeps its old document and gains `floor, floorTarget, transition, pending, mode, profile, observed, leaseTtl, speaking{alpha,beta,+caption feed}, rms, settings{effective,sources,overrides,env,schema}, locked, warnings, seq`. Tests: `tests/test_floor_lease.py` (pytest now in `app/.venv`) — random API sequences never grant both, two simulated robots with dropped polls never both open, expired lease closes the mic, drain/cut, duet, resolution order, locked gates.
