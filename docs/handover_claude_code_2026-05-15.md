# Claude Code Implementation Handover — 2026-05-15

**Project:** CJ Panganiban Conversation App (Supervaise FLP Project 2)
**Repo:** https://github.com/jeanettepao-ux/Supervaise-FLP-Project-2
**Last commit:** `839a4d2` on `main`, clean working tree
**This document:** implementation truth as of today. Pair with the
strategic/decision handover (separate document) for full context.

---

## 1. TL;DR

The project runs end-to-end today. The text-only smoke test
(`python cj_chat.py --text "What is the rule of law?"`) passes — full
output captured in §4. The Streamlit chat dashboard (`streamlit run
dashboard.py`) serves HTTP 200 and has been used interactively. Both the
CLI and the dashboard share the same pipeline: faster-whisper STT →
Claude Haiku router → Claude Sonnet inference → Piper TTS. There are
**no automated tests** in the repo; verification has been one-off
human-driven runs of the 6 sanity-check questions from the build kit.
The Tagalog TTS is approximated by hand-crafted phonetic substitutions
(stopgap, not native quality); everything else behaves as the build-kit
spec intended.

---

## 2. Repo layout

```
Supervaise-FLP-Project-2/
├── README.md                    [implemented]  project intro + quick start
├── PROJECT.md                   [implemented]  comprehensive project doc (456 lines)
├── .gitignore                   [implemented]  excludes .env, .venv/, app/voices/*.onnx, app/piper/, app/state/
├── docs/
│   └── handover_claude_code_2026-05-15.md      [this file]
├── app/                                         the runnable app
│   ├── README.md                [implemented]  app run instructions (212 lines)
│   ├── cj_chat.py               [working]      CLI + all pipeline functions (616 lines)
│   ├── dashboard.py             [working]      Streamlit chat UI (367 lines)
│   ├── requirements.txt         [implemented]
│   ├── .env                     [implemented; GITIGNORED]  ANTHROPIC_API_KEY + paths
│   ├── .env.example             [implemented]
│   ├── .gitignore               [implemented]  app-scoped ignores (state/, voices/*.onnx, piper/)
│   ├── artifacts/                                corpus artifacts loaded at startup
│   │   ├── voice_card.md        [implemented]  inference system prompt (229 lines)
│   │   ├── router_prompt.md     [implemented]  router system prompt (198 lines)
│   │   ├── topic_map.json       [implemented]  37 canonical topics
│   │   ├── topic_graph.json     [implemented]  37 nodes, 78 edges
│   │   ├── entity_index.json    [implemented]  69 people, 16 cases, laws_treaties
│   │   ├── frameworks.json      [implemented]  10 named frameworks (four_ins, three_es, etc.)
│   │   ├── signature_library.json [implemented]  ~684 normalized signature phrases
│   │   └── topics/              [implemented]  89 Stage-1 per-doc extractions
│   ├── piper/                   [installed; GITIGNORED]  Piper Windows binary + dlls (38 MB)
│   ├── voices/                  [installed; GITIGNORED]  en_US-ryan-high voice (116 MB)
│   ├── state/                   [runtime; GITIGNORED]    generated TTS wavs land here
│   └── .venv/                   [GITIGNORED]   Python 3.11 venv (464 MB)
├── corpus/                                      source corpus + pre-processing
│   ├── manifest.json
│   ├── build_kit/               [implemented]  voice_card.md, router_prompt.md, cj_chat.py reference, README.md (the spec)
│   ├── prompts/                 [implemented]  stage_1a_extraction.md, stage_3_design.md
│   ├── synthesis_scripts/       [implemented]  taxonomy.py, synthesize.py, make_summary.py, aliases.py, stage_3_design.md
│   └── analysis/
│       ├── synthesis/           [implemented]  Stage 3 outputs (canonical layer, 7 files)
│       └── topics/              [implemented]  Stage 1 outputs (89 per-doc extractions)
└── source_materials/                            original published writing (~150K words)
    ├── manifest.json
    ├── books/book_01_centenary-of-justice/   [implemented]  25 .md files (chapters + appendices)
    └── columns/                              [implemented]  65 .md files (2011–2026)
```

Everything marked `[implemented]` exists on disk and is wired in.
`[working]` = exercised by at least one successful run today.
No directory is a stub or empty.

---

## 3. What's been built

| Component | Status | File(s) | Notes |
|---|---|---|---|
| STT (faster-whisper) | working | `app/cj_chat.py:134-144` | `medium` model, int8 quantized, CPU. VAD on (`min_silence_duration_ms=500`). Verified round-trip on Piper-synthesized wav. |
| Router (Haiku) | working | `app/cj_chat.py:150-183` | `claude-haiku-4-5-20251001`, max_tokens=300, JSON output. Code-fence stripping + topic-ID validation against `topic_map.json` with `rule_of_law` fallback. All 6 build-kit sanity questions routed correctly. |
| Retrieval (build_context) | working | `app/cj_chat.py:189-243` | Loads 1-3 routed topics from `topic_map.json`, top-3 raw docs of primary topic from `artifacts/topics/`, trimmed to essentials. Outputs an XML-tagged context block. |
| Inference (Sonnet) | working | `app/cj_chat.py:249-286` | `claude-sonnet-4-6`, max_tokens=600, voice_card.md as system prompt, confidence-aware grounding note. Pipes response through `_strip_stage_directions` before return. |
| TTS (Piper) | working | `app/cj_chat.py:413-442` | Multi-line stdin, `--sentence_silence 0.6`, `--length_scale 1.05`, `--quiet`. Outputs single concatenated wav. |
| TTS text prep | working | `app/cj_chat.py:325-372` | Strips markdown, applies phonetic substitutions for Tagalog/Spanish/French (12 entries), converts long-dashes → commas, splits on sentence boundaries. |
| Stage-direction stripping | working | `app/cj_chat.py:391-410` | Regex `^\s*\*[^*\n]+\*\s*$` removes whole-line italics like `*A moment of quiet*`; inline emphasis preserved. |
| Audio I/O (CLI push-to-talk) | working | `app/cj_chat.py:459-514` | RMS-based silence detection, ~1.2s trailing silence, 30s max. Streams via `sounddevice.InputStream`. |
| Audio I/O (dashboard mic) | working | `app/dashboard.py:206-241` | `st.audio_input` widget, browser records, MD5-hash to avoid re-processing on Streamlit rerun, mic-counter key trick to reset widget per turn. |
| Audio playback | working | `app/cj_chat.py:445-453` | Cross-platform: `winsound` on win32, `afplay` on darwin, `aplay` on linux. Dashboard uses `st.audio(..., autoplay=True)`. |
| Conversation history | working | `app/cj_chat.py:600-610`, `app/dashboard.py:97-99,254-259` | Last 10 turns (20 messages) passed to inference call for multi-turn coherence. Persisted in `st.session_state.messages` (dashboard) or in-process list (CLI). |
| Anthropic retry handling | working | `app/cj_chat.py:90-95` | `make_client()` returns `Anthropic(max_retries=4)` — ~15s of internal retry on 5xx/429 before bubbling up. |
| API error handling (dashboard) | working | `app/dashboard.py:286-322` | Catches `APIStatusError` and branches on `status_code` (529, 429, other); `APIConnectionError`; catch-all `Exception`. Shows `st.error` banner, persists marker assistant turn so user's question stays in history. |
| API error handling (CLI) | working | `app/cj_chat.py:548-564` | try/except around route+generate, prints friendly stderr message. |
| Sources expander (dashboard) | working | `app/dashboard.py:149-187` | Topic pills (primary/secondary, color-coded), confidence (color-coded), router reasoning, top-3 doc titles+dates+IDs. |
| TTS debug expander | working | `app/dashboard.py:343-356` | Toggle in sidebar. Shows the per-line chunks Piper saw with ⏸ markers where pauses land. |
| Voice card (CJ system prompt) | implemented | `app/artifacts/voice_card.md` | 229 lines. Identity, voice fingerprint, register hierarchy, anchor topics, out-of-corpus policy. From build kit. Unchanged. |
| Router prompt | implemented | `app/artifacts/router_prompt.md` | 198 lines. System block parsed from the first ```...``` fence. From build kit. Unchanged. |
| Topic taxonomy artifacts | implemented | `app/artifacts/{topic_map,topic_graph,entity_index,frameworks,signature_library}.json` | 37 topics, 78 edges, 69 people, 16 cases, 10 frameworks, 684 phrases. Generated by `corpus/synthesis_scripts/synthesize.py`. |
| Operator UI (dashboard) | working | `app/dashboard.py` | Single-page Streamlit chat with mic + text-fallback + history + audio playback + sources + TTS debug. Sidebar toggles for TTS and debug; "Clear conversation" button. |
| Backend API endpoints | not started | — | No HTTP backend exists. The dashboard *is* the backend — it embeds the pipeline directly. |
| Embeddings ingestion | not started | — | None — routing is by topic IDs via a Haiku call, not vector similarity. No embeddings layer exists. |
| Database schema | not started | — | No DB. Conversation history is in-memory (`st.session_state` or Python list); artifacts are JSON files on disk. |
| Robot adapter (Reachy Mini) | not started | — | Out of scope per build-kit README (May 30 demo is conversation-only). |
| Speech corpus (Pass B) | not started | — | The ~150 CJ speeches called out in the build kit are not in `source_materials/`. Only book + columns. |
| Automated tests | not started | — | No `tests/` directory, no `pytest`, no fixtures. Verification has been manual smoke tests only. |

Status legend per spec:
`not started` = directory or stub only
`in progress` = partial, won't run end-to-end
`runnable` = executes without error, behavior unverified
`working` = executes and produces expected output on ≥1 case
`tested` = automated tests pass

---

## 4. What runs right now

### Text-only smoke test (no audio, no mic required)

```powershell
cd "D:\Reachy Mini Project\App 2\app"
.venv\Scripts\python.exe cj_chat.py --text "What is the rule of law?"
```

**Actual output captured today (2026-05-15):**

```
Loading artifacts...
  ✓ 37 topics loaded

👤 You: What is the rule of law?

🧭 Routing...
   primary: rule_of_law
   secondary: ['liberty_and_prosperity']
   confidence: high
💭 Thinking...

⚖️  CJ: The rule of law is the bedrock of any decent and ordered
society — the supreme principle that law, not force, not the whims of
the powerful, governs us all. In my humble opinion, it is the single
most important organizing concept in our public life.

What does it mean in practice? It means that no one — no president,
no general, no corporation, no foreign power — stands above the law.
It means that rights are protected, not merely promised. And it means
that when any branch of government commits grave abuse of discretion,
the courts must step in — not because judges are superior to the
executive or the legislature, but because, as I wrote in *Obra
Maestra*, the Constitution must be upheld as truly paramount.

But the rule of law cannot stand alone. Liberty without prosperity is
an empty promise — freedom and food, justice and jobs, ethics and
economics must always go together. These twin beacons must always go
together; one is useless without the other.

The opposite of the rule of law is the rule of force — and we see it
today wherever might masquerades as right. *Au contraire* — right
must always be mightier than might. That is the eternal, universal
truth at the heart of this principle.

Mabuhay!
```

Pipeline observable in output: artifacts loaded (37 topics), router
returned `rule_of_law` (high) + `liberty_and_prosperity`, response hits
every CJ signature marker (twin beacons, *Au contraire*, *Obra
Maestra*, chiastic doublets, "In my humble opinion", `Mabuhay!`).

### Full voice dashboard

```powershell
cd "D:\Reachy Mini Project\App 2\app"
.venv\Scripts\streamlit run dashboard.py
```

Streamlit listens on `http://localhost:8501` (HTTP 200 verified). First
load triggers `@st.cache_resource` for artifacts (~1s), faster-whisper
medium model (~12s cold), and Anthropic client (~0.2s). Cold first turn
~25s total; warm subsequent turns ~15-20s.

### Voice CLI

```powershell
.venv\Scripts\python.exe cj_chat.py
```

Push-to-talk loop. Not executed end-to-end today, but `record_until_silence`
and the surrounding code path were exercised during the build (commit
`b7072ef` and prior). No regressions since.

---

## 5. Implementation decisions made during build

| What | Why | Where in code | Reversible? |
|---|---|---|---|
| Python 3.11 (not 3.12 or 3.14) | faster-whisper / ctranslate2 wheels most stable on 3.11; user's system has 3.11 already installed; 3.14 too new for some deps. | `app/.venv/` (built with `py -3.11 -m venv`); README documents. | Yes — rebuild venv with another version. |
| `python-dotenv` with `load_dotenv(override=True)` | User's shell environment had an empty `ANTHROPIC_API_KEY` shadowing the `.env`. Default `override=False` silently kept the empty value. | `app/cj_chat.py:47-50` | Trivial — change `override=True` flag. |
| `Anthropic(max_retries=4)` | Default SDK retry is 2 (~3s total backoff). User hit a 529 OverloadedError that survived default retries. 4 retries ≈ 15s window — covers most transient overloads without making the user wait too long. | `app/cj_chat.py:90-95` | Trivial — `ANTHROPIC_MAX_RETRIES` constant. |
| Branch on `status_code` instead of importing `OverloadedError` | `anthropic.OverloadedError` lives in private `anthropic._exceptions` in v0.102.0 — not at top-level namespace. Importing from private modules is fragile across versions. | `app/dashboard.py:286-304` | Could switch to `except OverloadedError` if/when SDK exposes it publicly. |
| Streamlit `st.audio_input` (browser-side recording) | Originally I built a separate-process two-terminal design (CLI for audio + read-only dashboard polling a state file). User asked for the dashboard to BE the input UI — st.audio_input is Streamlit's built-in browser-mic widget, no extra deps, no native code. | `app/dashboard.py:206-212` | Yes — could swap back to file-polling design; old design is preserved in commit `8311558` history. |
| `mic_counter` key trick to reset the audio widget | `st.audio_input` caches its recording across Streamlit reruns. Without resetting the widget key, the same recording would re-submit on every rerun. Bumping `f"mic_{counter}"` forces Streamlit to create a fresh widget. | `app/dashboard.py:102-103, 211, 241` | Yes — could use MD5-hash-only approach if we drop the widget reset. |
| MD5-hash of audio bytes for "already processed?" check | Belt-and-suspenders alongside the mic_counter trick. If the user re-uses an audio file (unlikely but possible), the hash dedupes the request. | `app/dashboard.py:222-224` | Yes. |
| TTS pipeline: per-sentence multi-line stdin + `--sentence_silence 0.6` | Piper concatenates multi-line stdin into one `--output_file` wav with `--sentence_silence` between each line. Gives explicit, controllable inter-sentence breath; verified by silent-gap analysis of resulting wav. | `app/cj_chat.py:413-442` | Reversible — could pass full text as one line and accept Piper's default inter-sentence behavior. |
| Em-dash → comma substitution in TTS path (not chunk splitting) | First attempt was splitting on em-dashes too (commit `6788eee`). User reported "no pause on em-dashes" — turned out to be a Streamlit stale-import issue, but they suggested the simpler text-substitution approach. Confirmed via silent-gap analysis that Piper's native comma pause is actually 150-300ms (occasionally 600ms for clause-boundary commas), strong enough for the dashes. Simpler code, same audible result. | `app/cj_chat.py:349-358` | Reversible — old chunking code is in commit `6788eee` history. |
| `TTS_FOREIGN_SUBSTITUTIONS` list (Tagalog/Spanish/French phonetic spellings) | Piper's `en_US-ryan-high` voice is American-English-only. Hand-crafted phonetic spellings ("Mah-RAH-ming sah-LAH-maht poh") give it stress + vowel hints. Stopgap, not native quality. User explicitly chose this over OpenAI TTS swap. | `app/cj_chat.py:307-322` | Easy to extend (add tuples) or remove (delete list). |
| Stage-direction stripping: whole-line `*...*` only | Claude occasionally prefixes responses with `*A moment of quiet*` style narration. Stripping inline italics (`*Au contraire*`, `*A Centenary of Justice*`) would lose emphasis. Regex `^\s*\*[^*\n]+\*\s*$` only matches lines that are entirely wrapped — internal asterisks save inline emphasis. | `app/cj_chat.py:391-410` | Easy — adjust regex. |
| Streamlit `@st.cache_resource` for artifacts, whisper, anthropic client | Streamlit reruns the script top-to-bottom on every interaction. Without caching, each rerun would re-load 37 topics + the whisper model + a new Anthropic client. Caching by resource (not data) keeps them as singletons. | `app/dashboard.py:73-88` | Trivial. |
| `state/tts/` for generated wavs | Streamlit's `st.audio(path)` needs the wav to persist for the lifetime of the page. Tempfiles get cleaned too eagerly; persistent dir under app root works. Gitignored. | `app/dashboard.py:91-94`, `.gitignore` | Easy — switch to `st.audio(bytes)` if disk persistence becomes an issue. |
| All audio dirs and venvs gitignored, not committed | Voice model is 116 MB, Piper binary is 38 MB, .venv is 464 MB. Committing these blows up the repo and isn't useful — each user installs locally. README and PROJECT.md document where to get them. | `app/.gitignore`, root `.gitignore` | Reversible (would not recommend). |
| `.env` loaded from `Path(__file__).parent / ".env"` (not CWD) | Streamlit reruns from various working dirs; CWD-relative `.env` loading failed in some cases. Resolving relative to `cj_chat.py` is stable. | `app/cj_chat.py:48` | Trivial. |
| Windows stdout `reconfigure(encoding="utf-8")` | Default Windows console can't print 🎤 📝 ⚖️ 🔊 emojis and crashes with `UnicodeEncodeError`. Stdlib `sys.stdout.reconfigure` fixes it without external deps. | `app/cj_chat.py:53-58` | Trivial. |

---

## 6. Deviations from spec

| Item | Type | What the spec says | What's on disk | Why |
|---|---|---|---|---|
| Two-terminal "CLI + read-only dashboard" design | intentional | The strategy/design doc (per my reading of the build-kit README and the original conversation flow) called for the dashboard to be an audience-facing viewer that mirrored what the CLI did. | The dashboard is now self-contained and drives the full pipeline; the CLI is the secondary path. | User explicitly asked for the dashboard to host the mic input (matching a previous app they'd built). I rebuilt as interactive chat in commit `b7072ef`. The strategy doc may still reference the old design. |
| TTS em-dash pause (0.5s split vs comma substitution) | discovered | Build kit doesn't prescribe TTS pause behavior. Earlier commits in this repo (`7e582d5`, `6788eee`) implemented em-dash splitting with 0.5s pauses. | Current code substitutes em-dashes with commas; pause is now driven by Piper's native comma phoneme (150-300ms typical). | User asked for the simpler approach in their second TTS feedback turn. The earlier "split on em-dash" code is preserved in git history (`6788eee`). |
| Streamlit dashboard added to scope | intentional | The build-kit README explicitly says "Web UI — the reference impl is CLI; a web UI is straightforward but separate work." | Streamlit dashboard exists at `app/dashboard.py`. | User asked for my recommendation, I suggested a hybrid, user said "Build your recommendation". |
| Anthropic max_retries=4 | discovered | Build-kit reference impl uses bare `Anthropic()` (default max_retries=2). | `make_client()` returns `Anthropic(max_retries=4)`. | User hit a 529 OverloadedError that survived default retries. |
| Whisper VAD `min_silence_duration_ms=500` | unintentional | Build-kit README troubleshooting says: "If [Whisper hallucinations] still happening, increase `vad_parameters={'min_silence_duration_ms': 1000}`". | Current code uses 500. | Carried over from the build_kit reference cj_chat.py without bumping. Hasn't bitten us — but the build kit explicitly recommends 1000 if hallucinations occur. Cheap to change. |
| Model IDs | discovered | Build-kit uses `claude-haiku-4-5-20251001` and `claude-sonnet-4-6`. | Same. Both verified callable in current Anthropic SDK v0.102.0. | The naming convention `sonnet-4-6` (no date suffix) is unusual but the API accepts it. Tested: returns valid responses. |
| TTS pause length 0.6s (not 0.5s) | intentional | Build kit doesn't prescribe. | `TTS_SENTENCE_SILENCE = "0.6"` (bumped from 0.5 in commit `c30e197`). | User feedback that pauses needed to be more obvious. Constant at top of `cj_chat.py`; easy to revert. |
| No automated tests | intentional | Build kit doesn't mandate tests; verification is the 6-question sanity check. | No `tests/` directory. | Within the demo timeline this is acceptable but worth flagging. See §9. |
| No `corpus/synthesis_scripts` rerun | intentional | The build-kit pipeline can regenerate artifacts from `source_materials/`. | The current `app/artifacts/` files are pre-generated and committed. | The artifacts are stable — no need to rerun the synthesis pipeline for this demo. Re-running would require redoing Stage 1 extraction (89 LLM calls) and Stage 3 synthesis. |

---

## 7. Bugs, blockers, and known issues

| Severity | What | Details | Workaround |
|---|---|---|---|
| smell | Streamlit caches imported modules across reloads | `streamlit run dashboard.py` auto-reloads `dashboard.py` on save but **not** `cj_chat.py` (an imported module). Tuning changes in `cj_chat.py` (TTS pause length, foreign substitutions, etc.) require a full Streamlit restart (Ctrl+C + relaunch). | Document the restart requirement (already in `PROJECT.md` and `app/README.md`). |
| smell | Whisper "medium" model is slow on CPU | 3-5s per transcription warm. Build-kit target is ≤4s end-to-end turn, which is unreachable on this hardware with `medium`. | Switch `WHISPER_MODEL=small` in `.env` for English-only demos (drops transcription to ~1s); accept slower turns for Tagalog code-switch. |
| smell | Piper RTF ~1.8 on CPU | A 150-word response takes ~9s to render. | Acceptable for the demo. Build-kit explicitly suggests OpenAI TTS `onyx` swap for production polish (~5x faster + better diction). User declined this swap. |
| tech debt | No tests | Manual smoke-test only. Refactors are risky. | Add minimal pytest suite for `_prepare_tts_text`, `_strip_stage_directions`, `route_question` JSON parsing fallback. ~1-2 hours. See §9. |
| tech debt | `cj_chat.py` is 616 lines of one-file mixed concerns | Config + pipeline functions + audio I/O + main loop. Refactoring into modules would help future-CC, but the build kit explicitly intended this to be a "runnable skeleton" single file. | Leave alone for now. |
| tech debt | `synthesize.py` and other corpus/synthesis_scripts/ are not exercised | The current `app/artifacts/` are pre-built; the synthesis scripts in `corpus/synthesis_scripts/` haven't been re-run during this session. If they have bit-rot, no one would know yet. | Document as a "do this before Pass B" task. |
| smell | TTS phonetic substitutions are crude approximations | Tagalog/Spanish/French speakers will hear the attempt is American-English. Native quality requires a multilingual TTS engine. | Documented in PROJECT.md. User explicitly chose this over OpenAI TTS swap. |
| smell | `record_until_silence` uses RMS threshold (350) | Hardcoded ambient-noise threshold. Will fail in loud rooms or with very quiet speakers. | Acceptable for controlled demo environment. Bump threshold or add auto-calibration if needed. |
| smell | First-time whisper download is ~22 minutes for `medium` | 1.5 GB at apparent ~1 MB/s on the test machine. User experience is "app hangs" if they didn't pre-fetch. | Documented in `app/README.md`: "(Optional) Pre-fetch the whisper model" with the exact one-liner. |
| smell | Conversation history in dashboard lives in browser session only | Refresh = lost context. No durable store. | Out of scope per build kit ("No memory beyond last 10 turns"). |
| tech debt | The `state/current.json` references in PROJECT.md are stale | The old read-only dashboard wrote to `state/current.json`; the new interactive dashboard doesn't. PROJECT.md mentions it once. | Minor doc inconsistency. Fix when convenient. |

No `blocker` or `bug` (wrong behavior) found.

---

## 8. Dependencies and environment

### System

- **OS:** Windows (tested on Windows with bash from Git for Windows)
- **Python:** 3.11.9 (CLI confirms `Python 3.11.9`). Repo also has 3.14 and 3.12 installed but neither used.
- **Disk:** ~620 MB in `app/` (without whisper cache); add 1.5 GB for `whisper-medium` cache at `%USERPROFILE%\.cache\huggingface\hub\`.
- **No ffmpeg, portaudio, or other native libs required** — `sounddevice` ships its own portaudio, `faster-whisper` ships ctranslate2 wheels, Piper is a single-file Windows exe.

### Python dependencies (pinned versions installed today)

```
anthropic==0.102.0
ctranslate2==4.7.1
faster-whisper==1.2.1
numpy==2.4.4
onnxruntime==1.26.0
python-dotenv==1.2.2
scipy==1.17.1
sounddevice==0.5.5
streamlit==1.57.0
tokenizers==0.23.1
```

(Full `pip freeze` available; `requirements.txt` uses `>=` constraints.)

### Required environment variables (names only)

- `ANTHROPIC_API_KEY` — Claude API key (must start `sk-ant-...`)
- `WHISPER_MODEL` — `small` or `medium` (default `medium`)
- `PIPER_BIN` — path to Piper executable (default `./piper/piper.exe`)
- `PIPER_VOICE` — path to ONNX voice (default `./voices/en_US-ryan-high.onnx`)

Loaded from `app/.env` via `python-dotenv` with `override=True`. `.env.example` is committed; `.env` is gitignored.

### Local-only assets (not committed; user must install)

| Asset | Path | Size | Source |
|---|---|---|---|
| Piper TTS binary + dlls | `app/piper/` | 38 MB | https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip |
| Piper voice model (ONNX) | `app/voices/en_US-ryan-high.onnx` | 116 MB | https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx |
| Piper voice config | `app/voices/en_US-ryan-high.onnx.json` | 4 KB | https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json |
| faster-whisper `medium` model | `%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-medium\` | 1.5 GB | auto-downloads on first run from HuggingFace |
| Anthropic Python SDK | venv | — | pip-installed |

`.venv/` is 464 MB; not committed. Rebuild with `py -3.11 -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt`.

---

## 9. Immediate next actions

Ranked by what unblocks the next obvious step.

1. **Add a minimal pytest suite.** [2-4 hours]
   - Touches: new `app/tests/` directory.
   - Why: every refactor right now is a step into a swamp. A few unit tests on `_prepare_tts_text` (input → expected chunks), `_strip_stage_directions` (real example + 3 edge cases), `route_question` JSON parsing fallback (malformed router output → safe default), and a mocked end-to-end `run_turn` would let future-CC change things without fear.
   - Blocker: none.

2. **Reconcile PROJECT.md with the current dashboard architecture.** [30 min]
   - Touches: `PROJECT.md`.
   - Why: the doc was written before the dashboard rewrite (commit `b7072ef`); some references to the old read-only state-file design remain (search for `state/current.json`).
   - Blocker: none.

3. **Bump Whisper VAD silence to 1000ms.** [5 min]
   - Touches: `app/cj_chat.py:141` (`min_silence_duration_ms=500` → `1000`).
   - Why: build kit explicitly recommends this if hallucinations occur; preemptive insurance for the demo.
   - Blocker: none.

4. **Wire a sidebar "WHISPER_MODEL" toggle.** [15 min]
   - Touches: `app/dashboard.py`.
   - Why: lets the operator switch `small`/`medium` during a demo without restarting. Useful if the audience is pure-English and you want faster turns.
   - Blocker: would need to call `get_whisper.clear()` to drop the cached `WhisperModel` on switch.

5. **Document the Streamlit-restart requirement more loudly.** [10 min]
   - Touches: `app/README.md` quick-start section.
   - Why: every time the user tuned `cj_chat.py` they hit the stale-import issue. A `⚠️ Restart Streamlit after editing cj_chat.py` callout would have saved several round-trips.
   - Blocker: none.

6. **Add a sample wav for offline TTS regression testing.** [30 min]
   - Touches: `app/tests/fixtures/`.
   - Why: confidence that TTS-pause behavior didn't regress.
   - Blocker: none.

7. **Voice-card iteration on stage directions.** [30 min]
   - Touches: `app/artifacts/voice_card.md`.
   - Why: we strip stage directions post-hoc, but adding an explicit prohibition to the system prompt would avoid wasting tokens on generating them in the first place. Belt-and-suspenders.
   - Blocker: would change a build-kit artifact (consider whether that's in scope).

8. **Investigate Reachy Mini integration scaffold.** [4-8 hours]
   - Touches: new `app/robot/` directory.
   - Why: build kit lists this as out of scope for May 30, but the wider Reachy Mini project lives in this same tree (note the `reachy-mini-dances-library` and `reachy-mini-emotions-library` HuggingFace caches on the machine). Bridging audio I/O to the robot would be the next major arc.
   - Blocker: need user direction on whether to start this before or after the demo.

9. **Speech corpus ingestion (Pass B).** [2-3 days]
   - Touches: new directory under `source_materials/speeches/`; rerun `corpus/synthesis_scripts/`.
   - Why: build kit anticipates ~150 CJ speeches as Pass B. Codebase supports them without changes (`synthesize.py` regenerates `topic_map.json` etc.).
   - Blocker: requires speech sources + LLM cost for Stage 1 extraction.

10. **Add CI on push.** [1 hour]
    - Touches: new `.github/workflows/ci.yml`.
    - Why: at least lint + the pytest suite (#1) on every push to `main`.
    - Blocker: #1.

---

## 10. Questions for the human

1. **Strategy-doc vs implementation divergence on dashboard role.** The strategy/decision handover (which I haven't seen) may describe the dashboard as a read-only audience viewer (the original commit `8311558` design). The current implementation is a self-contained interactive chat (`b7072ef` onward) because you asked for the mic input to be in the dashboard. Confirm which side wins if these conflict.

2. **Voice-card modifications.** Are you OK with me editing `app/artifacts/voice_card.md` (and the upstream `corpus/build_kit/voice_card.md`)? Concretely: adding "do not include stage directions or italicized narration" as an explicit instruction. The build kit treats voice_card.md as the canonical specification; modifying it changes contract.

3. **WHISPER_MODEL default for the live demo.** Build kit says `medium` for Filipino/English code-switching; I have it set to `medium`. But that costs ~5s/turn extra and the demo may be predominantly English. Want me to switch the default to `small` and have a sidebar toggle, or keep `medium` for safety?

4. **TTS_FOREIGN_SUBSTITUTIONS expansion.** The default list has 12 entries covering CJ's most common Tagalog/Spanish/French phrases. The `signature_library.json` has 684 phrases total — many are English but a non-trivial chunk are Tagalog. Want me to scan and pre-populate substitutions for every foreign phrase in the corpus, or wait until they come up in practice?

5. **Reachy Mini scope.** The HuggingFace cache on this machine shows you've already pulled `pollen-robotics/reachy-mini-dances-library` and `reachy-mini-emotions-library`. Is the May 30 conversation app meant to feed into the robot at some point, or are these tracks fully independent?

6. **Anthropic API key in `.env` was shared in chat.** I noted twice that it should be rotated. Has it been? If not, treat the key string as compromised and rotate via https://console.anthropic.com/settings/keys. The local `.env` is gitignored and was never pushed, but the value is in this conversation's history.

7. **The corpus synthesis scripts haven't been re-run during this session.** `corpus/synthesis_scripts/synthesize.py`, `make_summary.py`, `taxonomy.py`, `aliases.py` are committed and presumably ran cleanly to produce the current `app/artifacts/`. Are they still expected to work as Pass B preparation, or has anything changed in `corpus/` that might invalidate them? Worth a smoke run before Pass B.

8. **Speech corpus location.** The build kit anticipates ~150 speeches from cjpanganiban.com — none are in `source_materials/` today. Do you have them collected somewhere (and we just haven't ingested), or is collection itself the next task?

---

## 11. How to use this handover

This document is **implementation truth as of 2026-05-15**. It describes
what actually exists on disk, what actually runs, and what I (Claude
Code) actually did during the build session.

It is the companion to a separate strategic/decision handover written
in another Claude conversation. Where the two disagree:

- For **what exists, what runs, what's installed where** → trust this
  document and the git tree.
- For **why we made an architectural choice, what the design intent
  was, what's still open as a design question** → trust the strategic
  handover.

When you (future-me or future-Claude) open this project again:

1. Read this document first. Then read PROJECT.md for runtime-tuning
   detail. Then read the strategic/decision handover for design intent.
2. Before assuming anything is true, run `git log --oneline -10` to see
   what's happened since `839a4d2`, and re-run the smoke test in §4 to
   verify the pipeline still works.
3. Any code referenced here by file:line is at the commit `839a4d2`.
   Subsequent commits may have moved things.
4. The 8 questions in §10 are the most likely places where ambiguity
   bites. Reconcile against this document before acting on the strategic
   handover's answers.

— Claude Code, 2026-05-15
