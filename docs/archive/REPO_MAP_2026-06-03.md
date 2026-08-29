# REPO_MAP — Supervaise Reachy-Mini × CJ Panganiban Kiosk

Generated 2026-06-03 from the actual code at commit `a5a5adc`.
Concrete and current, not aspirational.

---

## 1. DIRECTORY TREE

```
.
├── README.md                       Project overview + pipeline diagram
├── CLAUDE.md                       Navigational entry point for LLM agents
├── PROJECT.md                      Runtime tuning detail (cost model, perf)
├── architecture.md                 Architectural notes
├── End Point.txt                   PowerShell launch one-liner
├── .gitignore
├── .env / .env.example             Top-level env (mostly unused; real ones live in app/)
│
├── app/                            ⚡ Runnable kiosk + dashboard
│   ├── app.py                      Museum kiosk Streamlit entry (1 380 LOC)
│   ├── dashboard.py                Developer dashboard Streamlit entry (1 111 LOC)
│   ├── cj_chat.py                  Shared pipeline library + CLI (1 324 LOC)
│   ├── voice_io.py                 OpenAI Whisper STT + tts-1 TTS (450 LOC)
│   ├── requirements.txt            Pinned Python deps
│   ├── .env / .env.example         API keys + model overrides
│   ├── .gitignore
│   ├── MANIFEST.md
│   ├── README.md
│   ├── assets/                     reachy_curious.png, museum_bg.jpg
│   ├── piper/                      (gitignored) legacy Piper TTS binary cache
│   ├── voices/                     (gitignored) legacy Piper/Whisper voice models
│   └── state/                      (gitignored) runtime TTS cache
│
├── corpus/                         Runtime corpus the kiosk reads
│   ├── voice/
│   │   ├── topic_map.json          35-topic hand-curated taxonomy (4 819 lines)
│   │   ├── voice_card.md           Sonnet system prompt (375 lines)
│   │   └── router_prompt.md        Haiku router system prompt (219 lines)
│   ├── columns/{theme}/{ID}.md+.json    65 paired files
│   ├── speeches/{theme}/{ID}.md+.json   15 paired files
│   └── MANIFEST.md
│
├── data/                           Pre-pipeline raw inputs
│   ├── csv/                        3 curated CSV files
│   └── text/                       80 source .txt files
│
├── scripts/                        Offline corpus pipeline (idempotent)
│   ├── generate_corpus_files.py    (898 LOC)
│   ├── build_topic_map.py          (1 037 LOC)
│   ├── apply_topic_paths.py        (61 LOC)
│   ├── check_paths.py              (149 LOC)
│   └── run_smoke_test.py           (280 LOC)
│
├── docs/                           Governance, never auto-generated
│   ├── decisions/                  ADR-0001 … ADR-0018 + MANIFEST.md
│   ├── lessons/                    LL-001 … LL-011 + MANIFEST.md
│   ├── implementation-plans/       PLAN-0001 … PLAN-0007 + MANIFEST.md
│   ├── test-specs/                 TS-001 … TS-006 + MANIFEST.md
│   ├── guides/                     GUIDE-{end-user,reviewer,admin,manager,firstrun}.md + MANIFEST
│   ├── handover_claude_code_2026-05-15.md / -16.md / -26.md / -31.md
│   └── MANIFEST.md
│
├── reports/                        Pipeline-run outputs (regenerated each run)
│   ├── generation_report.json
│   ├── validation_errors.log
│   ├── topic_map_report.json
│   └── smoke_test_run.json + smoke_test_summary.json
│
└── claude-harness-public/          Vendored Supervaise orchestration scaffolding (140 files, unused at runtime)
```

---

## 2. FILE-BY-FILE (significant files)

### Runtime code (`app/`)

| File | Owns |
|---|---|
| **`app/app.py`** ⚡ **kiosk entry point** | Museum-kiosk Streamlit UI; CSS-heavy single file; glass panel + twin-button console + dual progress drop-downs; orchestrates the pipeline via `_run_pipeline()`. |
| **`app/dashboard.py`** ⚡ **dev dashboard entry point** | Alternate Streamlit UI for operators/reviewers; richer diagnostics; documented to use faster-whisper + Piper but in current shipping state uses the same OpenAI pipeline as `app.py`. |
| `app/cj_chat.py` | Pure-pipeline library: corpus loader (`CorpusArtifacts`), `input_gate`, `route_question`, `build_context`, `generate_response_stream`, `fidelity_check`, cost telemetry, env-driven model selection, CLI `main()`. |
| `app/voice_io.py` | OpenAI Whisper `transcribe_openai()`, per-sentence parallel `tts_concatenate_parallel()`, cost estimator, pydub-based MP3 concatenation with raw-byte fallback. NO Streamlit imports. |
| `app/assets/reachy_curious.png` | Robot avatar override (with inline-SVG fallback in `app.py:129`). |
| `app/assets/museum_bg.jpg` | Gallery backdrop override (with CSS-gradient fallback in `app.py:307`). |
| `app/requirements.txt` | **Dependency manifest** — see §5. |
| **`app/.env`** 🔐 | **Local secrets** — actual API keys live here, gitignored. |
| `app/.env.example` | Env template — currently STALE (shows legacy Whisper/Piper vars, doesn't list `OPENAI_API_KEY` which the runtime actually requires). |

### Corpus (`corpus/voice/`)

| File | Owns |
|---|---|
| `corpus/voice/topic_map.json` | 35-topic hand-curated taxonomy; each topic has `description`, `themes`, optional `signature_phrases`; loaded by `CorpusArtifacts.__init__`. |
| `corpus/voice/voice_card.md` | Sonnet composer system prompt; contains length bands (substantive 60-100w, factual 20-40w, doctrinal ≤150w); cached via Anthropic prompt caching. |
| `corpus/voice/router_prompt.md` | Haiku router system prompt; defines the JSON output schema for `route_question`. |
| `corpus/{type}/{theme}/{ID}.{md,json}` | 80 paired corpus documents; ID pattern `[SC][A-E]NNN` (S=speech, C=column); JSON must contain `topic_paths` (theme/topic strings backfilled by `scripts/apply_topic_paths.py`). |

### Scripts (`scripts/`) — offline only, not in runtime path

| File | Owns |
|---|---|
| `scripts/generate_corpus_files.py` | Phase 1: CSV + text → paired `.md`+`.json` corpus files. |
| `scripts/build_topic_map.py` | Phase 2: builds `topic_map.json` from hand-curated taxonomy. |
| `scripts/apply_topic_paths.py` | Backfills `topic_paths` into each doc's `.json` per ADR-0015 rules. |
| `scripts/check_paths.py` | Validates the corpus path layout matches the runtime's expected schema. |
| `scripts/run_smoke_test.py` | Runs `docs/test-specs/TS-006-smoke-test-questions.json` end-to-end through the text-only path of `cj_chat.py`. |

### Docs (`docs/`) — see §6

---

## 3. RUNTIME FLOW

### Startup

```powershell
cd app
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

`app.py:300` (`main()`) sets the page config, injects CSS, runs `_preflight()` (`app.py:222`) which blocks page-load with a remediation banner if `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` is missing or if any in-repo import failed, then initialises session state (`_init_state` at `app.py:255`).

What the visitor sees on first load:
1. A full-screen frosted-glass panel containing the **READY** status pill (top-right), the **Reachy Mini** SVG robot avatar (center), the **"With Due Respect"** title, and a one-line blurb. Rendered by `_render_glass_panel()` at `app.py:787`.
2. Below the glass panel: a **two-button frosted-glass control bar** holding the **START/STOP** pill (left) and the **🎧 MY RESPONSE** button (right, disabled until READY). Rendered by `_render_console()` at `app.py:1209`.
3. Two empty progress columns below the buttons (containers reserved for live drop-downs).

### Per-turn interaction trace

| Step | Owned by | Detail |
|---|---|---|
| Visitor taps **START/STOP** pill | Browser → Streamlit `st.audio_input` widget at `app.py:1243` | The widget is created with `key=f"mic_{ss.mic_key}"`; CSS in `_inject_css()` (`app.py:331`) styles the native mic icon as a text pill labelled literally "START/STOP", changes the bar's border tint via `:has(button[aria-label*='stop'])` while recording. **Browser MediaRecorder captures audio** — no Python audio library involved. |
| Visitor taps STOP | Streamlit returns WAV bytes from the widget on the next script execution | `audio_in.getvalue()` returns `bytes` (WAV/WebM container; OpenAI Whisper accepts both). |
| **Hash-of-bytes guard** | `app.py:1332-1336` inside `main()` | `hashlib.md5(audio_bytes).hexdigest()` compared against `ss.last_audio_hash`; if same → no-op (idempotent across reruns); if new → proceeds. |
| Inline pipeline kicks off | `app.py:1342` calls `_run_pipeline(audio_bytes, left_progress, right_progress)` at `app.py:1012` | Runs on the SAME script execution — no PROCESSING state, no session-state audio handoff. |
| ── **Phase A** drop-down opens in left column ── | `_run_pipeline` `app.py:1063` `st.status("🎧 Understanding your question…")` | |
| **1. STT** | `voice_io.transcribe_openai(wav_path)` at `voice_io.py:147` | Writes the audio bytes to a temp `.wav` file (`app.py:1054`), POSTs to OpenAI Whisper-1 (`response_format="text"`), returns trimmed transcript string. Cost: ~$0.001 per turn. |
| **2. Input gate** (DCI scope check) | `cj_chat.input_gate(client, transcript)` at `cj_chat.py:546` | Haiku 4.5 call against `INPUT_GATE_SYSTEM`; returns `{scope, reasoning}` where `scope ∈ {in_corpus, out_of_corpus, identity_probe}`. JSON-parse fallback → `in_corpus`. Cached system prompt. |
| **3. Routing** | `cj_chat.route_question(client, transcript, artifacts)` at `cj_chat.py:418` OR `cj_chat.force_meta_routing()` at `cj_chat.py:581` if `scope=="identity_probe"` | Haiku 4.5 call against `artifacts.router_system` (= `corpus/voice/router_prompt.md`); returns `{primary_topic, secondary_topics, confidence, reasoning}` with topic IDs validated against `topic_map.json`. Cached system prompt. |
| ── **Phase B** drop-down opens in right column ── | `app.py:1128` `st.status("✨ Preparing the Chief Justice's answer…")` | |
| **4. Context assembly** | `cj_chat.build_context(routing, artifacts)` at `cj_chat.py:651` | Topic data block + 2-3 source docs (selected by `_select_source_doc_ids` at `cj_chat.py:605`); enforces soft token budget; drops lowest-priority docs first if over budget. |
| **5. Composition** (streamed) | `cj_chat.generate_response_stream(client, transcript, routing, artifacts)` at `cj_chat.py:756` | Sonnet 4.6 streaming call with `voice_card` cached as system prompt. Output is `str` accumulated; passed through `_strip_stage_directions` at `cj_chat.py:1055`. |
| **6. Fidelity check** (advisory) | `cj_chat.fidelity_check(client, context, response)` at `cj_chat.py:854` | Haiku 4.5 call; flags `{hallucination, voice_drift, guardrail_violation}` for diagnostics; **does NOT gate the response** — currently advisory-only. |
| **7. TTS** | `voice_io.tts_concatenate_parallel(response)` at `voice_io.py:379` | Splits response into sentence chunks (`sentence_chunks` at `voice_io.py:250`); fires concurrent OpenAI `tts-1` calls (voice `echo`, speed `0.98`) via `asyncio.gather`; concatenates per-sentence MP3 bytes (pydub with raw-byte fallback). Returns one `bytes` blob. |
| **8. Cost rollup** | `app.py:1173-1187`; uses `_anthropic_cost_since` (`app.py:290`) + `estimate_voice_cost` (`voice_io.py:412`) | Per-turn total stored in `ss.last_turn_cost`; session total accumulated; both kept in session_state but NOT displayed (per recent UX decision). |
| Audio handed back | `ss.audio_bytes = mp3_bytes`; `ss.kiosk_state = "READY"`; `ss.autoplay_pending = True` | |
| `st.rerun()` | `app.py:1351` | Fresh render with READY state. |
| **Audio plays** | `_autoplay_audio(ss.audio_bytes)` at `app.py:1271`, called once when `autoplay_pending` is True | Renders an `<audio autoplay controls preload='auto'>` HTML element via `st.markdown(..., unsafe_allow_html=True)` — **parent DOM, not iframe** — so browser inherits the visitor's interaction context and autoplay actually fires. **Browser plays the MP3** — no Python audio library involved. |
| Visitor taps **🎧 MY RESPONSE** | `play_clicked` returned from `_render_console`; handled at `app.py` end of `main()` | Re-renders the autoplay audio element for replay. |
| Cached drop-down rendering on rerun | `app.py` near end of `main()` | After the pipeline run, on the post-`st.rerun()` execution the two columns re-render as `st.expander` containers from cached session_state — same cards (`_card_transcribed`, `_card_scope`, `_card_routing`, `_card_response`, `_card_fidelity`) visible after the live drop-downs collapse. |

### Audio I/O — explicit ownership

- **Capture:** browser's MediaRecorder API, surfaced through `streamlit.audio_input` (returns WAV/WebM bytes to Python on script execution).
- **Playback:** browser's HTML5 `<audio>` element, rendered as raw HTML via `st.markdown(..., unsafe_allow_html=True)` in `_autoplay_audio`. **No Python audio library is involved in either direction.** `pydub` is used only for server-side MP3 concatenation of TTS chunks (`voice_io._concatenate_mp3_chunks` at `voice_io.py:334`); it never touches the microphone or speakers.

---

## 4. WAKE-WORD INTEGRATION POINTS

The current record button is a single Streamlit widget (`st.audio_input`) inside `_render_console`. Adding a "listening / wake word" gate in front of it has two natural seams:

### Seam A — Gate at the top of `main()` (recommended for an Activate-Kiosk gesture)

Insert a one-time "press to activate" surface **before** the call to `_render_console()`. Touches:
- `app/app.py:1300` `main()` body — add a session-state flag (e.g. `ss.kiosk_armed`) and an `st.button` + `st.stop()` block at the top of `main()`, so nothing renders below until the visitor performs the one-time user gesture. Needed because browsers refuse mic permission and `<audio autoplay>` without a prior user interaction.

### Seam B — Replace or wrap the audio_input widget

The actual mic widget call site:
- `app/app.py:1243` inside `_render_console` (`app.py:1209-1268`):
  ```python
  audio_in = st.audio_input(
      label="Press START to speak",
      label_visibility="collapsed",
      key=f"mic_{ss.mic_key}",
  )
  ```
  This returns `bytes | None` of WAV/WebM audio. Any wake-word replacement must produce the same `bytes | None` shape so the downstream funnel doesn't need to change.

### Seam C — The downstream funnel (pipeline trigger)

The hash-of-bytes guard + `_run_pipeline` call at `app/app.py:1332-1351` inside `main()`:
```python
if audio_in is not None:
    audio_bytes = audio_in.getvalue()
    if audio_bytes and len(audio_bytes) > 1024:
        audio_hash = hashlib.md5(audio_bytes).hexdigest()
        if audio_hash != ss.get("last_audio_hash", ""):
            ss["last_audio_hash"] = audio_hash
            _run_pipeline(audio_bytes, left_progress, right_progress)
            ss.mic_key += 1
            st.rerun()
```
This funnel is the **single point of entry** to the pipeline. A wake-word path must produce `audio_bytes: bytes` and feed them into this funnel (or call `_run_pipeline` directly with the same arguments). The hash-of-bytes guard at `app.py:1335` MUST survive any new audio source, otherwise reruns will re-fire the pipeline.

### Where the start-record / stop-record controls live

- **There is only one button.** It's a single `st.audio_input` widget at `app/app.py:1243` styled by CSS in `_inject_css` (`app/app.py:331`) to appear as a pill labelled "START/STOP". The widget's built-in record toggle handles both states — pressing it once starts recording, pressing it again stops. Python never sees the "user pressed mic" event; the widget returns bytes only after stop.
- The visual "recording / not recording" state is driven entirely by CSS `:has(button[aria-label*='stop'])` selectors — no Python state. See comments at `app/app.py:1318-1325`.
- A wake-word gate that wants to mirror a "listening / capturing / thinking / speaking" state must own its own visible UI (most cleanly: an iframe-mounted custom component with its own status pill rendered into the left console column via `left_progress`).

### What MUST NOT change

- **`app/cj_chat.py`** — Anthropic prompt cache on `voice_card.md` requires the system prompt bytes to stay identical between turns. Any wake-word work upstream of `cj_chat.input_gate` is fine; modifying `cj_chat.py` itself is not.
- **`corpus/voice/voice_card.md`, `router_prompt.md`, `topic_map.json`** — same reason.

---

## 5. DEPENDENCIES & ENV

### Python version
Targeted for **Python 3.10 or 3.11**. The repo runs on a Windows machine via the venv created at `app/.venv/`. Python 3.12 is known to break the deprecated `tensorflow-cpu==2.8.1` pin and many 2022-era audio packages — relevant if anyone wants to add wake-word training.

### Dependency manifest (`app/requirements.txt`)

```
# Core
anthropic>=0.40.0        # Claude API (router, composer, fidelity check)
openai>=1.40.0           # Whisper STT + tts-1 TTS
python-dotenv>=1.0.0     # multi-location .env loading

# Audio
pydub>=0.25.1            # MP3 concatenation
imageio-ffmpeg>=0.4.9    # bundled ffmpeg binary (fallback when no system ffmpeg)

# Dashboard / kiosk
streamlit>=1.40.0

# Optional (legacy local-stack residue; safe to drop if unused)
numpy>=1.24.0
scipy>=1.10.0
```

No JS / Node / npm / browser-side tooling. No vector DB, no embeddings, no ML model files in the runtime.

### Run command

```powershell
cd C:\Users\ASUS\Projects\Supervaise-Reachy-Mini-Project\app
.\.venv\Scripts\Activate.ps1
streamlit run app.py
```

(One-liner version in `End Point.txt`.)

### Env vars (NAMES ONLY — values live in `app/.env`, gitignored)

**Required:**
- `ANTHROPIC_API_KEY` — Claude API access for router + composer + fidelity + input-gate
- `OPENAI_API_KEY` — OpenAI API access for Whisper STT + tts-1 TTS

**Optional (defaults in code, can be overridden):**
- `ROUTER_MODEL` — defaults to `claude-haiku-4-5-20251001` (set in `cj_chat.py:99`)
- `INFERENCE_MODEL` — defaults to `claude-sonnet-4-6` (set in `cj_chat.py:100`)
- `OPENAI_STT_MODEL` — defaults to `whisper-1` (set in `voice_io.py:127`)
- `OPENAI_TTS_MODEL` — defaults to `tts-1` (set in `voice_io.py:128`)
- `OPENAI_TTS_VOICE` — defaults to `echo` (set in `voice_io.py:137`)
- `OPENAI_TTS_SPEED` — defaults to `0.98` (set in `voice_io.py:141`)
- `CORPUS_ROOT` / `VOICE_DIR` / `ROUTER_PROMPT` — path overrides (see `cj_chat.py:Config`)
- `DOTENV_PATH` — explicit .env location (overrides the cwd → repo-root → app/ search order)
- `HF_HOME` — moves the HuggingFace cache off the C: drive (only relevant if the legacy faster-whisper path is exercised)

**⚠️ `app/.env.example` is stale.** It only mentions `ANTHROPIC_API_KEY` plus the legacy Whisper/Piper paths and does NOT list `OPENAI_API_KEY` even though the runtime requires it. The authoritative env-var list is the one above; the `docs/handover_claude_code_2026-05-31.md` §7 also has it correct.

---

## 6. EXISTING DOCS

| Path | Covers |
|---|---|
| `CLAUDE.md` | Navigational entry point for LLM agents: which docs to read first, the conflict-resolution policy between docs, "what this repo is NOT" guardrails. |
| `PROJECT.md` | Runtime tuning detail — pipeline architecture, cost model, performance numbers, troubleshooting, config defaults. |
| `README.md` | Project overview, repo layout (slightly out-of-date — references the older `corpus/build_kit/` + `source_materials/` tree), pipeline diagram. |
| `architecture.md` | Architectural notes (one-off; not regularly updated). |
| `End Point.txt` | PowerShell launch one-liner pointing at `app.py`. |
| **`docs/handover_claude_code_2026-05-31.md`** | **Most current handover** — 12-section engineering snapshot: what was built, stack, repo map, file-by-file, feature status, data coupling, run/test, technical decisions, known issues, git state, where work left off, active timeframe. **Read this first** if you're picking the project up cold. |
| `docs/handover_claude_code_2026-05-26.md` / `-16.md` / `-15.md` | Prior handover snapshots; superseded by the 05-31 one but kept for diff context. |
| `docs/decisions/` | 18 ADRs (MADR 4.0 format) covering: Claude-not-OpenAI for inference (0001), Haiku/Sonnet tiering (0002), reject embeddings (0003), Pattern-1 architecture (0004), defer robot embodiment (0005), local-stack (0006-7), Streamlit (0008, 0017), Messages API (0009), prompt caching (0010), corpus ID format (0011), permissive CSV parsing (0012), strict dates (0013), hand-curated taxonomy (0014), topic_paths derivation (0015), theme-anchored register (0016), OpenAI STT/TTS (0018). Plus `MANIFEST.md` indexing them. |
| `docs/lessons/` | 11 lessons-learned (`LL-001` … `LL-011`). Operationally relevant: LL-001 (cache savings ~18 %, not 55 %), LL-002 (Haiku ignores cache_control above some sizes), LL-003 (dotenv override=False), LL-004 (Streamlit caches imported modules), LL-005 (signature library unused). Plus `MANIFEST.md`. |
| `docs/implementation-plans/` | 7 implementation plans (`PLAN-0001` runtime app, `PLAN-0002` web chat UI, `PLAN-0003` embedding audit, `PLAN-0004` biography ingest, `PLAN-0005` book corpus, `PLAN-0006` voice/TTS, `PLAN-0007` taxonomy evolution). Plus `MANIFEST.md`. |
| `docs/test-specs/` | 6 test specifications (`TS-001` generator contract, `TS-002` topic-map matchers, `TS-003` topic_paths derivation, `TS-004` voice card protocol, `TS-005` end-to-end smoke, `TS-006` 30-question smoke set). Plus `MANIFEST.md`. |
| `docs/guides/` | 5 persona-scoped guides (`GUIDE-end-user`, `GUIDE-reviewer`, `GUIDE-admin`, `GUIDE-manager`, `GUIDE-firstrun`). Plus `MANIFEST.md`. |
| `docs/MANIFEST.md` | Index of all governance subdirectories above. |
| `corpus/MANIFEST.md` | Index of the corpus directory layout. |
| `app/MANIFEST.md` | Index of the app/ directory. |
| `app/README.md` | App-specific run instructions. |
| `claude-harness-public/` | Vendored Supervaise orchestration scaffolding (~140 files of templates, prompts, modules). **Not wired into the runtime.** Available as a reference resource for future ADR/test-spec/plan template re-use. |
| **No `IMPLEMENTATION_PLAN.md` at repo root.** | Implementation plans live as numbered files under `docs/implementation-plans/`, indexed by `docs/implementation-plans/MANIFEST.md`. |

---

### Quick orientation for a new planning assistant

If you're handing off a new feature: read `docs/handover_claude_code_2026-05-31.md` first (12-section snapshot), then `CLAUDE.md` (conflict-resolution policy), then this `REPO_MAP.md`. The actual runtime is just three files: `app/app.py`, `app/cj_chat.py`, `app/voice_io.py`. Everything else is corpus, governance, or offline pipeline.
