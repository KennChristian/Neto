# CLAUDE.md

A conversation app that speaks as retired Philippine Chief Justice
Artemio V. Panganiban, grounded in his published corpus.

**It now runs on hardware: two Reachy Mini robots**, one playing
Panganiban and one playing a Host, coordinated by a one-microphone
floor lease. The original **May 30, 2026** laptop demo has passed; the
live target is a public hall of roughly 200 people for four hours, and
that is what the current work is tuned for.

This file is the navigational entry point for any Claude Code or LLM
agent opening this repo. It points to where things live — not what
they do. Last reconciled against the running machines **2026-09-13**.

## Read first

Three documents are the source of truth. Read them in this order before
making changes:

| Doc | What it gives you |
|---|---|
| [docs/handover_claude_code_2026-05-26.md](docs/handover_claude_code_2026-05-26.md) | Latest implementation reality — what runs, what's wired, gaps between intent and reality. Supersedes the 05-16 handover. |
| [docs/handover_claude_code_2026-05-16.md](docs/handover_claude_code_2026-05-16.md) | Prior implementation snapshot — kept for diff context. |
| [PROJECT.md](PROJECT.md) | Runtime tuning detail — pipeline architecture, cost model, performance numbers, troubleshooting, config. |

For **planning artifacts** introduced during the Phase 1-3 corpus
work, the entry points are:

| Doc | What it gives you |
|---|---|
| [docs/MANIFEST.md](docs/MANIFEST.md) | Index of all governance subdirectories — handover snapshots, ADRs, lessons, plans, test specs, persona guides. |
| [docs/implementation-plans/MANIFEST.md](docs/implementation-plans/MANIFEST.md) | 7 phase-aligned plans (runtime app, web UI, embedding audit, biography ingest, book corpus, voice/TTS, taxonomy evolution). |
| [docs/test-specs/MANIFEST.md](docs/test-specs/MANIFEST.md) | 5 verification specs (generator contract, matchers, topic_paths, voice card protocol, end-to-end smoke). |
| [docs/guides/MANIFEST.md](docs/guides/MANIFEST.md) | 4 persona-scoped guides (end-user, reviewer, admin, manager). |

The strategic handover (`docs/handover_strategic_2026-05-17.md`) and a
corpus pipeline companion are referenced elsewhere but are **not on
disk in this repo** as of the time this file was written. If they
appear later, they take precedence over implementation docs for
*design intent* questions.

## Subdirectory index

| Path | Purpose | MANIFEST |
|---|---|---|
| [`app/`](app/) | The runtime. **`main_voice_robot.py` is what `supervaise.service` actually runs** (mic, wake word, turn loop, gestures, floor-lease client, playback). `answer_pipeline.py` is the router/context/composer; `speech_engines.py` STT+TTS; `speech_streaming.py` per-sentence synthesis and captions; `answer_gate.py` the deterministic output gates; `personas.py` the cjap/host split; `voice_vad.py` and `voice_identity.py` the post-capture gates. Reads corpus from `../corpus/`. | [app/MANIFEST.md](app/MANIFEST.md) |
| [`dashboard/`](dashboard/) | The port-8080 maintenance dashboard (stdlib, system python3; `pi-dashboard.service`). `/maintain`, `/audience`, `/event`, `/face-avatar` and, since 2026-09-10, the **operator console** `/console` — `console.py` holds the one-mic floor lease, mode/profile config resolution and the journal; `ui_page_console.py` is the page. `assets/` (LiveAvatar key) and `certs/` are git-ignored. `~/pi_dashboard` is a symlink here. | — |
| [`config/modes/`](config/modes/) | Mode profiles `duet.json` / `direct.json` with `kiosk` / `event` threshold sets — the base of the listening-settings resolution (profile → systemd drop-in → `app/.env` → console override). | — |
| [`tests/`](tests/) | pytest suite, **156 tests**: `test_floor_lease.py` (one-mic invariant, duet sequencing, authored pauses), `test_answer_gate.py`, `test_canned.py`, `test_dashboard_ui.py`, `test_context_grounding.py`, `test_breath_motion.py` (continuous motion + envelope emphasis), `test_intro_rotation.py`, `test_name_pin.py`, `test_duet_script.py`, `test_wifi_control.py`. | — |
| [`app/wake/`](app/wake/) | Wake-word stack (PLAN-0008). `engine.py` is the openWakeWord runtime wrapper; `wake_test.py` is the dev dashboard. `models/hey_cj.onnx` is the committed v2 classifier (locked threshold **0.40**); `models/hey_cj.v1.onnx` is the rollback. Training pipeline lives under `training/` (gN gates + Phase 1/2 retrain scripts); `data/` and `training/oww_*` trees are git-ignored — regenerated locally. | — |
| [`corpus/`](corpus/) | The runtime corpus: `voice/` (topic map, voice card, router prompt, `host_card.md`, **`duet_script.json`** — 33 pre-rendered lines, **`intro_variants.json`** — 6 Host intros), `columns/` (64 paired `.md` + `.json`), `speeches/` (15 paired `.md` + `.json`). | [corpus/MANIFEST.md](corpus/MANIFEST.md) |
| [`scripts/`](scripts/) | Corpus pipeline (`generate_corpus_files.py`, `build_topic_map.py`, `apply_topic_paths.py`, `run_smoke_test.py`, `check_paths.py`) **plus the installation scripts: `render_duet.py` and `render_intro.py` (pre-render spoken audio, offline), `deploy_second_robot.sh`, `provision_kit_wifi.sh`, `wake_model_eval.py`.** Idempotent. | — |
| [`data/`](data/) | Phase 1 inputs (`data/csv/`, `data/text/`) **and the pre-rendered audio the installation plays with no network: `data/prerendered/duet/` (33 clips) and `data/prerendered/intro/` (6 variants x 2 modes). The `.wav` files are gitignored and re-renderable; the `manifest.json` beside them is tracked.** | — |
| [`docs/`](docs/) | Handover docs, ADRs (`docs/decisions/`), lessons (`docs/lessons/`), implementation plans (`docs/implementation-plans/`), test specs (`docs/test-specs/`), persona guides (`docs/guides/`). | [docs/MANIFEST.md](docs/MANIFEST.md) |
| [`reports/`](reports/) | Output reports from each pipeline run — `generation_report.json`, `validation_errors.log`, `topic_map_report.json`, `smoke_test_run.json`, `smoke_test_summary.json`. Regenerated on every run. | — |

> The earlier 89-doc pipeline (`app/artifacts/`, `corpus/build_kit/`,
> `corpus/prompts/`, `corpus/synthesis_scripts/`, `corpus/analysis/`,
> `corpus/manifest.json`) and `source_materials/` tree were removed
> when PLAN-0001 §A migrated the runtime to consume the Phase 1-3
> outputs directly. Book sections will return under `corpus/books/`
> per [PLAN-0005](docs/implementation-plans/PLAN-0005-book-corpus-addition.md).

## The installation, as it actually runs (2026-09-13)

Two machines. Neither talks to the other; both talk to the authority.

| | alpha | beta |
|---|---|---|
| hostname | `reachy-cjap` | `reachy-2` (192.168.88.10) |
| plays | Panganiban (default) | Host (default) |
| also runs | **the lease authority + console** | nothing extra |
| services | `supervaise.service`, `pi-dashboard.service` | the same two |

- **Who plays whom is `cjap_is`**, held by the authority and swappable from
  `/console` **with no restart and no corpus reload** — both machines load
  both voice cards and both ElevenLabs voice ids at boot.
- **The microphone opens only while a robot holds the floor**, granted by the
  authority on a 3 s lease. If the authority goes away the lease expires and
  **both robots go silent and still** — fail-closed, deliberately. A visitor
  cannot tell that from switched off; there is no on-screen or spoken notice.
- **Modes**: `duet` (pre-rendered exchange, no microphone, no composer, works
  with **no internet**) and `direct` (a visitor asks). Profiles `kiosk` (wake
  word on) and `event` (wake word off, louder thresholds, no follow-up window).
- **Config resolution**, later wins: `config/modes/<mode>.json` defaults →
  its `profiles.<profile>` → the systemd drop-in **on the authority** →
  `app/.env` **on the authority** → console override. The robot applies the
  result into `os.environ` on every lease reply. A machine's own drop-in and
  `.env` only matter when the console is unreachable.
- **Not in git**: `/etc/systemd/system/supervaise.service.d/wakeword.conf`
  (per-machine tuning, root-owned), `app/.env` (keys), the rendered `.wav`s.

Run the tests before anything else: `app/.venv/bin/python -m pytest tests/`.
Operator procedure for a venue is [docs/event_runbook](docs/) and
[docs/PRE_EVENT_CHECKLIST.md](docs/PRE_EVENT_CHECKLIST.md).

## Known open items — read before trusting the safety story

Measured 2026-09-13, not estimated. These are the things most likely to
mislead someone reading the code and assuming it is handled.

- **The output gates do not catch the failure that actually happens.** Across
  50 adversarial questions and 277 composed sentences they blocked **zero**,
  while 37 invented particulars reached speech. The year gate and the
  forbidden-pattern gate do block, but the real failure is the composer
  recombining **real** corpus entities into pairings that were never true — a
  real person given the wrong office. Every component is individually
  grounded, so nothing sees it. Unverified case titles and the whole-answer
  fidelity audit **log only**. The opening sentence can begin playing before
  its audit returns. Do not describe these gates to a stakeholder as a safety
  net until this is fixed.
- **Only the top 2 routed documents contribute full prose**; the other 3-6
  contribute a JSON sidecar, and some sidecar summary fields are empty.
  `CJ_CONTEXT_BODY_DOCS` controls it, and raising it trades against latency.
- **Audio is the internal ~5 W speaker**, which is inaudible in a hall. No USB
  DAC is attached. `~/bin/audio-out dac` switches the route without a restart,
  but the host-side echo-cancellation delay for that route has never been
  calibrated, so the app deliberately refuses to arm it until
  `CJ_AEC_REF_DELAY_DAC_MS` is set. Calibrate at the venue with
  `~/tools/aec_ref_calib.py`.
- **`speaker-watchdog.service` is disabled on both machines** (2026-09-13). It
  re-routed audio onto any paired Bluetooth speaker within 15 s, which would
  have hijacked the route mid-event. Leave it disabled.
- **Memory is bounded, not free.** The speaker-embedding call is capped at
  `CJ_EMBED_MAX_S` (10 s) because it previously scaled with capture length and
  drove RSS to ~1 GB with 816 MB in swap. `MALLOC_ARENA_MAX=2` is set in the
  drop-in on both machines.
- **The duet loop is 4.3 minutes** and repeats about 14 times an hour. Better
  than the 55 s it was, still not "no repeat within an hour".
- **Every browser-avatar behaviour is unverified.** Testing needs a live paid
  LiveAvatar session that cannot be run from the headless Pi.

## Conflict resolution

When documents disagree:

- **Implementation facts** (what code exists, file:line, what runs) → the latest Claude Code handover wins ([docs/handover_claude_code_2026-05-16.md](docs/handover_claude_code_2026-05-16.md)).
- **Design intent** (why a choice was made, scope, audience, the May 30 target) → the strategic handover wins when present; otherwise [PROJECT.md](PROJECT.md) and the relevant ADR in [docs/decisions/](docs/decisions/).
- **Runtime pipeline mechanics** → [PLAN-0001](docs/implementation-plans/PLAN-0001-runtime-app-haiku-router-sonnet-composer.md) and [`corpus/voice/voice_card.md`](corpus/voice/voice_card.md).

## What this repo is NOT

- **Not RAG / no embeddings.** Routing is a Haiku call against a hand-curated taxonomy (35 topics post-Phase-2; previously 37); there is no vector store and no similarity search.
- **(SUPERSEDED 2026-09-13) ~~Not a robot embodiment for May 30.~~** [ADR-0005](docs/decisions/0005-defer-robot-embodiment-for-may-30.md) deferred Reachy Mini integration for the laptop demo. That deferral is over. The app runs on **two Reachy Mini units** as `supervaise.service`, with continuous head motion, a cloned voice, and a two-robot floor lease. Read this bullet as history, not as current scope.
- **Not a multi-trigger wake word.** One trigger only. **The live model is `app/wake/models/hi_see_jap.onnx` ("Hi Cee-Jap" / "Cee-Jap"), swapped in 2026-08-25** — not the `hey_cj.onnx` the older text describes, and not at threshold 0.40. The threshold is set per mode by the console (`config/modes/*.json`): 0.003 in direct-kiosk. In **direct-event the wake word is OFF entirely** and a loudness threshold sustained over 240 ms is the only gate on starting a turn. See [PLAN-0008 progress](docs/implementation-plans/PLAN-0008-progress.md) for the training history.
- **Tests exist and are the first thing to run.** `app/.venv/bin/python -m pytest tests/` — **156 passing as of 2026-09-13**. The earlier statement below is kept for history.
- **(historical) No automated tests yet.** Verification is currently manual via the six build-kit sanity questions plus interactive dashboard runs. Test *specifications* exist in [docs/test-specs/](docs/test-specs/); converting them into a runnable suite is part of the runtime work in [PLAN-0001](docs/implementation-plans/PLAN-0001-runtime-app-haiku-router-sonnet-composer.md).
