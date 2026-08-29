# Rename / cleanup map — 2026-08-29

Modules were renamed by **function** so the tree reads as the pipeline.
Old names appear in historical handovers (`docs/handover_*`), which were left as-is.
Local git checkpoints exist in both trees (`git log` in the checkout and in `~/pi_dashboard`).

## `app/` (the voice robot service, `supervaise.service`)

| Old | New | Role |
|---|---|---|
| `cj_voice_cloud.py` | **`main_voice_robot.py`** | entry point: boot → wake loop → turn → playback; gestures, mic, barge-in (11 numbered section banners) |
| `stream_speak.py` | **`speech_streaming.py`** | `SentenceSpeaker`: per-sentence TTS + gapless playback, replay wav, tempo smoothing hook, caption feeds |
| `voice_io.py` | **`speech_engines.py`** | STT (OpenAI) + TTS (ElevenLabs clone / OpenAI fallback), speed knobs, farewell settings |
| `tempo_smooth.py` | **`speech_tempo.py`** | per-sentence tempo normaliser (WSOLA toward a session EMA) |
| `cj_chat.py` | **`answer_pipeline.py`** | corpus artifacts, input gate, router, composer stream, fidelity check |
| `canned_answers.py` | **`answer_canned.py`** | curated/event answers (`data/entities/canned_answers.json` — data file, unchanged) |
| `dynamic_filler.py` | **`answer_filler.py`** | Haiku one-liner filler while composing |
| `postprocess.py` | **`text_entities.py`** | entity dictionary NER correction (transcript + TTS pass) |
| `lang_gate.py` | **`text_language_gate.py`** | Filipino/English transcript gate |
| `speaker_id.py` | **`voice_identity.py`** | enrolment, verification, voice lock (`~/speaker_id/` data dir unchanged) |
| `wake_word.py`, `answer_gate.py`, `usage_meter.py` | *(unchanged)* | openWakeWord detector · answer gate · usage tally |
| `app.py`, `dashboard.py`, `wake_test.py`, `assets/`, `requirements-kiosk.txt` | **`app/legacy/`** | Streamlit kiosk + old dashboard, not used by the robot |

## `~/pi_dashboard/` (`pi-dashboard.service`, port 8080)

| Old | New | Role |
|---|---|---|
| `dashboard.py` | **`ui_server.py`** | HTTP server (keep-alive), `/api/action` jobs, WiFi/BT, Say box, phone audio |
| `supervaise_ui.py` (2300 lines) | **`ui_common.py`** | paths + `/dev/shm` relay constants, state/health/usage readers, `control()` actions, tuning, entities |
| | **`ui_page_maintenance.py`** | `/maintain` page (+ key gate page) |
| | **`ui_page_audience.py`** | `/audience` page + shared exhibit CSS/JS |
| | **`ui_page_event.py`** | `/event` buttons page |
| | **`ui_page_face.py`** | `/face`, `/face-avatar`, HeyGen session helpers, camera MJPEG |
| | **`ui_routes.py`** | `handle_get` / `handle_post` dispatch; facade re-exporting one namespace (`import ui_routes as ui`) |
| `say_text_helper.py` | *(unchanged)* | Say-box TTS helper (runs in the app venv) |

## Removed (dead under the deployed configuration)

- `main_voice_robot.py`: classic whole-answer composer path (116 lines), `_wake_windows()`, STT-keyword wake arming branch, legacy follow-up / stop-relisten loop, `--auto` push-to-talk mode (`--wake` is now the only mode).
- `wake_word.py`: `WakePhraseMatcher`, `SttKeywordDetector`, `MicAudioSource`, `wait_for_wake`, `run_hands_free_loop` (−208 lines). `make_detector` accepts only `openwakeword`.
- `voice/speak.py`: `init`, `speak()`, host/robot playback, espeak + canned fallback (−207 lines); `voice/fallback/` → `_archive/`.
- Dashboard: legacy mp3 replay fallback (the app writes `cj_last_answer.wav`).
- Repo root: `End Point.txt` (deleted), `architecture.md` / `REPO_MAP.md` → `docs/archive/`, `claude-harness-public/` → `_archive/`, all `__pycache__`, every `*.bak-*` → `_backups/`.

## References updated

systemd `supervaise.service` (`main_voice_robot.py --wake`) and `pi-dashboard.service` (`ui_server.py`) · `~/bin/verify.sh` import check · `~/bin/snapshot-push.sh` dashboard file list · `~/tools/pronunciation/*` · `scripts/*` · `tests/*` · `docs/SYSTEM_TRACE.md` · `app/MANIFEST.md`.
**Not updated:** the deploy bundle `~/CJAP/deploy/pi/` (install.sh still copies `dashboard.py`/`supervaise_ui.py`) — refresh it with `snapshot-push.sh` before the next fresh-robot install.
