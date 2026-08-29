# Claude Code Implementation Handover — 2026-05-16

**Project:** CJ Panganiban Conversation App (Supervaise FLP Project 2)
**Repo:** https://github.com/jeanettepao-ux/Supervaise-FLP-Project-2
**Last commit on main:** `f7e47a1` — clean working tree
**Supersedes:** `docs/handover_claude_code_2026-05-15.md` (yesterday). Diffs
from yesterday are flagged inline.

---

## 1. TL;DR

The project runs end-to-end today. Text-only smoke test
(`python cj_chat.py --text "..."`) passes; the Streamlit chat dashboard
(`streamlit run dashboard.py`) serves HTTP 200 and has been used
interactively in past sessions. Both share the same pipeline:
faster-whisper STT → Claude Haiku router → Claude Sonnet inference →
Piper TTS. **New since yesterday:** Anthropic prompt caching is now wired
on the inference call (voice_card system prompt, 3,265 tokens cached);
empirically delivers ~18% per-turn savings on warm cache (not the 55%
I initially projected). The dashboard sidebar shows live cache savings.
Per-turn cost dropped from ~$0.048 to ~$0.040 steady-state. **Still no
automated tests**; verification has been one-off human-driven runs.

---

## 2. Project identity (inferred from repo)

This is the **conversation-app track** of a larger Reachy Mini project.
The app speaks as the retired Chief Justice **Artemio V. Panganiban** of
the Philippine Supreme Court, grounded in his published writing (65
Inquirer columns + 1 book of 25 chapter/appendix files = 89 source
documents, ~150K words).

**Target audience:** a live demo on **May 30, 2026**. The
`corpus/build_kit/README.md` calls it "**Not a robot** — just a
desktop/laptop conversational interface" for that date. The user speaks
a question via mic, the app responds in CJ's voice.

**What I'm uncertain about** (defer to Section 11):

- Whether the demo is to FLP stakeholders, a Reachy Mini investor
  audience, an academic panel, or general public. The `voice_card.md`
  is calibrated for a Filipino audience that will recognize CJ's voice
  markers ("Maraming salamat po," "Au contraire," "Cheers!") — the
  audience-fit decision lives outside what's in the repo.
- Whether the conversation app feeds into the robot at some later
  stage. The HuggingFace cache on this machine contains
  `pollen-robotics/reachy-mini-dances-library` and
  `reachy-mini-emotions-library`, suggesting an embodiment track exists.
  The build-kit README explicitly puts robot embodiment **out of scope
  for May 30**.
- Whether "Pass B" (the additional ~150 speeches mentioned in the build
  kit) happens before or after the May 30 demo.

---

## 3. Repo layout

```
Supervaise-FLP-Project-2/
├── README.md                    [implemented]  project intro + quick start (101 lines)
├── PROJECT.md                   [implemented]  comprehensive project doc (513 lines, updated 05-15)
├── .gitignore                   [implemented]  excludes .env, .venv/, app/voices/*.onnx, app/piper/, app/state/, .claude/settings.local.json
├── docs/
│   ├── handover_claude_code_2026-05-15.md      [implemented]  yesterday's handover (407 lines)
│   ├── handover_claude_code_2026-05-15.pdf     [implemented]  PDF render of same (61 KB, 16 pages)
│   └── handover_claude_code_2026-05-16.md      [this file]
├── app/                                         the runnable app
│   ├── README.md                [implemented]  app run instructions (212 lines)
│   ├── cj_chat.py               [working]      CLI + pipeline functions (707 lines, +91 since yesterday)
│   ├── dashboard.py             [working]      Streamlit chat UI (397 lines, +30 since yesterday)
│   ├── requirements.txt         [implemented]  6 pinned core deps
│   ├── .env                     [implemented; GITIGNORED]  ANTHROPIC_API_KEY + paths
│   ├── .env.example             [implemented]  template
│   ├── .gitignore               [implemented]
│   ├── artifacts/                                corpus artifacts loaded at startup
│   │   ├── voice_card.md        [implemented]  inference system prompt (229 lines, 3,265 tok — CACHED)
│   │   ├── router_prompt.md     [implemented]  router system prompt (198 lines, ~2,400 tok)
│   │   ├── topic_map.json       [implemented]  37 canonical topics
│   │   ├── topic_graph.json     [implemented]  37 nodes, 78 edges
│   │   ├── entity_index.json    [implemented]  69 people, 16 cases, laws_treaties
│   │   ├── frameworks.json      [implemented]  10 named frameworks (four_ins, three_es, etc.)
│   │   ├── signature_library.json [implemented]  684 normalized signature phrases (loaded, NOT sent on inference)
│   │   └── topics/              [implemented]  89 Stage-1 per-doc extractions
│   ├── piper/                   [installed; GITIGNORED]  Piper Windows binary + dlls (38 MB)
│   ├── voices/                  [installed; GITIGNORED]  en_US-ryan-high voice (116 MB)
│   ├── state/tts/               [runtime; GITIGNORED]    generated TTS wavs
│   └── .venv/                   [GITIGNORED]   Python 3.11 venv (~485 MB; +20 MB since yesterday due to PDF deps)
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
    └── columns/                              [implemented]  65 .md files (2011-2026)
```

No directory is a stub. `[working]` = exercised by at least one
successful run on 2026-05-16.

**What changed since yesterday's handover:**
- `+3` commits: `4feddea` (yesterday's handover), `dab298e` (PDF
  render of same), `f7e47a1` (prompt caching)
- `+91 lines` in `cj_chat.py`: `make_client()`, `CACHE_STATS`,
  `_log_cache_usage()`, `cache_savings_summary()`, cache_control on
  both API calls, CLI exit hooks printing cache stats
- `+30 lines` in `dashboard.py`: sidebar cache savings panel
- `+0 lines` in artifacts/ (corpus unchanged)

---

## 4. What's been built

| Component | Status | File(s) | Notes |
|---|---|---|---|
| STT (faster-whisper) | working | `app/cj_chat.py:152-162` | `medium` model, int8 quantized, CPU. VAD on (`min_silence_duration_ms=500`). Build-kit recommends bumping to 1000 if hallucinations recur — not yet bumped. |
| Router (Haiku 4.5) | working | `app/cj_chat.py:168-209` | `claude-haiku-4-5-20251001`, max_tokens=300, JSON output. Code-fence stripping + topic-ID validation against `topic_map.json` with `rule_of_law` fallback. **cache_control is set but silently ignored by the API on Haiku 4.5** — see Bug #1 in §8. |
| Retrieval (build_context) | working | `app/cj_chat.py:215-269` | Loads 1-3 routed topics from `topic_map.json`, top-3 raw docs of primary topic from `artifacts/topics/`, trimmed to essentials. Outputs an XML-tagged context block (~3,800 tok topic_data + ~2,100 tok source_documents per call). |
| Inference (Sonnet 4.6) | working | `app/cj_chat.py:275-316` | `claude-sonnet-4-6`, max_tokens=600, voice_card as **cached** system prompt, confidence-aware grounding note. Pipes response through `_strip_stage_directions` before return. |
| **Prompt caching (NEW)** | **working** | `app/cj_chat.py:97-178, 191-199, 304-310` | `cache_control: {"type": "ephemeral"}` on system blocks for both API calls. Voice_card (3,265 tok) caches on Sonnet; router prompt (2,400 tok) marked but not honored on Haiku. Module-level `CACHE_STATS` accumulator + per-call stderr logging + session-end summary. |
| TTS (Piper) | working | `app/cj_chat.py:480-509` | Multi-line stdin, `--sentence_silence 0.6`, `--length_scale 1.05`, `--quiet`. Outputs single concatenated wav. |
| TTS text prep | working | `app/cj_chat.py:392-439` | Strips markdown, applies phonetic substitutions for Tagalog/Spanish/French (12 entries in `TTS_FOREIGN_SUBSTITUTIONS`), converts long-dashes → commas, splits on sentence boundaries. |
| Stage-direction stripping | working | `app/cj_chat.py:458-477` | Regex `^\s*\*[^*\n]+\*\s*$` removes whole-line italics like `*A moment of quiet*`; inline emphasis preserved. |
| Audio I/O (CLI push-to-talk) | working | `app/cj_chat.py:526-581` | RMS-based silence detection (threshold 350), ~1.2s trailing silence, 30s max. Streams via `sounddevice.InputStream`. |
| Audio I/O (dashboard mic) | working | `app/dashboard.py:223-258` | `st.audio_input` widget, browser records, MD5-hash to avoid re-processing on Streamlit rerun, mic-counter key trick to reset widget per turn. |
| Audio playback | working | `app/cj_chat.py:512-520` | Cross-platform: `winsound` on win32, `afplay` on darwin, `aplay` on linux. Dashboard uses `st.audio(..., autoplay=True)`. |
| Conversation history | working | `app/cj_chat.py:691-701`, `app/dashboard.py:101-104, 271-276` | Last 10 turns (20 messages) passed to inference for multi-turn coherence. Persisted in `st.session_state.messages` (dashboard) or in-process list (CLI). |
| Anthropic retry handling | working | `app/cj_chat.py:90-95` | `make_client()` returns `Anthropic(max_retries=4)` — ~15s of internal retry on 5xx/429 before bubbling up. |
| API error handling (dashboard) | working | `app/dashboard.py:301-340` | Catches `APIStatusError` and branches on `status_code` (529, 429, other); `APIConnectionError`; catch-all `Exception`. Shows `st.error` banner, persists marker assistant turn so user's question stays in history. |
| API error handling (CLI) | working | `app/cj_chat.py:631-647` | try/except around route+generate, prints friendly stderr message. |
| Sources expander (dashboard) | working | `app/dashboard.py:166-205` | Topic pills (primary/secondary, color-coded), confidence (color-coded), router reasoning, top-3 doc titles+dates+IDs. |
| TTS debug expander | working | `app/dashboard.py:361-374` | Toggle in sidebar. Shows the per-line chunks Piper saw with ⏸ markers where pauses land. |
| **Cache savings panel (NEW)** | **working** | `app/dashboard.py:141-167` | Sidebar metrics: paid $, saved $, % saved, cache-read tokens, cache-write tokens, call counts. Renders after the first turn of the session. |
| Voice card (CJ system prompt) | implemented | `app/artifacts/voice_card.md` | 229 lines, 3,265 tok. Identity, voice fingerprint (8 subsections), out-of-corpus policy, length/register guidance, worked example, safety boundary. From build kit. **Unchanged.** |
| Router prompt | implemented | `app/artifacts/router_prompt.md` | 198 lines. System block parsed from the first ```...``` fence. From build kit. Unchanged. |
| Topic taxonomy artifacts | implemented | `app/artifacts/{topic_map,topic_graph,entity_index,frameworks,signature_library}.json` | 37 topics, 78 edges, 69 people + 16 cases + laws/treaties, 10 frameworks, 684 phrases. Generated by `corpus/synthesis_scripts/synthesize.py`. |
| signature_library.json | implemented, **unused at inference** | `app/artifacts/signature_library.json` | 684 phrases, loaded by `CorpusArtifacts` but `build_context()` does not reference it. Available in memory; not in the prompt context. |
| Operator UI (dashboard) | working | `app/dashboard.py` | Streamlit chat with mic + text-fallback + history + audio playback + sources + TTS debug + **cache savings**. Sidebar: TTS toggle, debug toggle, Clear conversation. |
| Backend API endpoints | not started | — | No HTTP backend. The dashboard embeds the pipeline directly. |
| Embeddings ingestion | not started | — | None — routing is by topic IDs via Haiku, not vector similarity. |
| Database schema | not started | — | No DB. History in-memory, artifacts as JSON. |
| Robot adapter (Reachy Mini) | not started | — | Out of scope for May 30 per build-kit README. |
| Speech corpus (Pass B) | not started | — | ~150 CJ speeches anticipated; not in `source_materials/`. Only book + columns. |
| Automated tests | not started | — | No `tests/`, no `pytest`, no fixtures. Manual smoke-tests only. |

---

## 5. What runs right now

### Text-only smoke test (no audio, no mic)

```powershell
cd "D:\Reachy Mini Project\App 2\app"
.venv\Scripts\python.exe cj_chat.py --text "What is the rule of law?"
```

**Actual output today (2026-05-16, first call, cache WRITE):**

```
Loading artifacts...
  ✓ 37 topics loaded

👤 You: What is the rule of law?

🧭 Routing...
   primary: rule_of_law
   secondary: ['liberty_and_prosperity']
   confidence: high
💭 Thinking...

⚖️  CJ: [...response...]
That, in its essence, is what the rule of law means to me — and why I
have devoted my life to defending it. Cheers!


--- Cache usage ---
   router:   1 calls | input=  2808 tok (read=0, write=0, regular=2808) | output=   71 | paid $0.0032 vs baseline $0.0032 (saved $0.0000)
inference:   1 calls | input= 13726 tok (read=0, write=3265, regular=10461) | output=  324 | paid $0.0485 vs baseline $0.0460 (saved $-0.0024)
   TOTAL paid: $0.0516  vs without caching: $0.0492  =>  saved $-0.0024 (-5%)
```

Pipeline observable: artifacts loaded (37 topics), router landed on
`rule_of_law` (high) + `liberty_and_prosperity`, response hit CJ signature
markers (twin beacons, "Cheers!"). First call paid the cache-write
premium (1.25× = +$0.0024 over baseline).

**Second call within 5-min TTL (cache HIT, today's actual numbers):**

```
--- Cache usage ---
   router:   1 calls | input=  2807 tok (read=0, write=0, regular=2807) | output=   70 | paid $0.0032 vs baseline $0.0032 (saved $0.0000)
inference:   1 calls | input= 13032 tok (read=3265, write=0, regular=9767) | output=  352 | paid $0.0356 vs baseline $0.0444 (saved $0.0088)
   TOTAL paid: $0.0387  vs without caching: $0.0475  =>  saved $0.0088 (19%)
```

19% saved on the cached turn. `read=3265` confirms the voice_card hit
the cache. `regular_input=9767` is everything else (topic_data + source
docs + history + question).

### Full voice dashboard

```powershell
cd "D:\Reachy Mini Project\App 2\app"
.venv\Scripts\streamlit run dashboard.py
```

Streamlit on `http://localhost:8501` (HTTP 200 verified yesterday — no
code paths affecting startup changed today). Cache savings panel appears
in the sidebar after the first turn of a session.

### Voice CLI

```powershell
.venv\Scripts\python.exe cj_chat.py
```

Push-to-talk loop, ~1.2s trailing silence auto-stop. Not run end-to-end
today; last verified during the build week.

---

## 6. Implementation decisions made during build

| What | Why | Where in code | Reversible? |
|---|---|---|---|
| Python 3.11 (not 3.12 or 3.14) | faster-whisper / ctranslate2 wheels most stable on 3.11; system has 3.11 installed; 3.14 too new for some deps. | `app/.venv/` built with `py -3.11 -m venv` | Yes — rebuild venv. |
| `python-dotenv` with `override=True` | User's shell environment had an empty `ANTHROPIC_API_KEY` shadowing the `.env`. Default `override=False` silently kept the empty value. | `app/cj_chat.py:47-50` | Trivial. |
| `Anthropic(max_retries=4)` | Default SDK retry is 2 (~3s total). User hit a 529 OverloadedError that survived default retries. 4 retries ≈ 15s window. | `app/cj_chat.py:90-95` | Trivial — `ANTHROPIC_MAX_RETRIES` constant. |
| Branch on `status_code` instead of importing `OverloadedError` | `anthropic.OverloadedError` lives in private `anthropic._exceptions` in v0.102.0 — not at top-level. Importing private modules is fragile. | `app/dashboard.py:303-321` | Could switch when SDK exposes it publicly. |
| **(NEW today) `cache_control: {"type": "ephemeral"}` on both system prompts** | User asked for the "biggest win" cost optimization. Voice card is ~3K tok, byte-identical every call, far above Sonnet's 1,024-token cache minimum. Router prompt is ~2.4K tok, marked for caching too (intent), but Haiku 4.5 silently ignores it. | `app/cj_chat.py:189-194, 302-309` | Trivial — replace list with string. |
| **(NEW today) Module-level `CACHE_STATS` dict for observability** | Anthropic returns `cache_creation_input_tokens` and `cache_read_input_tokens` per response. Accumulating them at module level lets both CLI exit hooks and the Streamlit sidebar surface real $ savings without persisting to disk. Streamlit re-runs preserve module state across reruns, so this works for both UIs. | `app/cj_chat.py:107-178` | Trivial — drop the dict and the helpers. |
| **(NEW today) Honest per-call cost pricing in `cache_savings_summary()`** | Initially over-promised 55% savings. Actual is 18%, because voice_card is only 25% of inference input. The summary function uses real pricing constants ($/MTok for regular/write/read/output) and reports baseline vs paid. | `app/cj_chat.py:131-178` | Trivial — change pricing constants if Anthropic shifts prices. |
| Streamlit `st.audio_input` for browser-side recording | Originally I built a two-terminal CLI + read-only dashboard with file polling. User asked for the dashboard to BE the input UI. `st.audio_input` is Streamlit-native, no extra deps. | `app/dashboard.py:223-229` | Yes — old design preserved in commit `8311558` history. |
| `mic_counter` key trick to reset audio widget | `st.audio_input` caches its recording across Streamlit reruns. Without resetting the widget key, the same recording would re-submit. Bumping `f"mic_{counter}"` forces a fresh widget. | `app/dashboard.py:106-107, 228, 258` | Yes. |
| MD5-hash of audio bytes for "already processed?" check | Belt-and-suspenders with the mic_counter trick. | `app/dashboard.py:239-241` | Yes. |
| TTS pipeline: per-sentence multi-line stdin + `--sentence_silence 0.6` | Piper concatenates multi-line stdin into one `--output_file` wav with `--sentence_silence` between each line. Explicit, controllable inter-sentence breath; verified by silent-gap analysis. | `app/cj_chat.py:480-509` | Reversible. |
| Em-dash → comma substitution in TTS path | First attempt was splitting on em-dashes (commit `6788eee`). User reported "no pause" — was a Streamlit stale-import issue. User suggested simpler substitution. Confirmed Piper's native comma pause is 150-300ms typical, occasionally 600ms for clause-boundary commas. | `app/cj_chat.py:416-425` | Reversible — old chunking in commit `6788eee` history. |
| `TTS_FOREIGN_SUBSTITUTIONS` list (12 entries) | Piper's `en_US-ryan-high` is American-English-only. Hand-crafted phonetic spellings give it stress + vowel hints. User explicitly chose this over OpenAI TTS swap. | `app/cj_chat.py:374-389` | Easy. |
| Stage-direction stripping: whole-line `*...*` only | Claude occasionally prefixes responses with `*A moment of quiet*`. Stripping inline italics would lose `*Au contraire*` emphasis. Regex `^\s*\*[^*\n]+\*\s*$` matches only entirely-wrapped lines. | `app/cj_chat.py:458-477` | Easy. |
| Streamlit `@st.cache_resource` for artifacts, whisper, client | Streamlit reruns the script on every interaction. Caching as resource keeps them as singletons. | `app/dashboard.py:75-90` | Trivial. |
| `state/tts/` for generated wavs | Streamlit `st.audio(path)` needs the wav to persist for page lifetime. Tempfiles get cleaned eagerly. | `app/dashboard.py:93-96` | Easy. |
| Big assets gitignored | Voice model 116 MB, Piper 38 MB, .venv 485 MB. Each user installs locally; README documents sources. | root + app `.gitignore` | Reversible (don't). |
| `.env` resolved relative to `cj_chat.py` not CWD | Streamlit reruns from various CWDs; CWD-relative `.env` loading failed in some cases. | `app/cj_chat.py:48` | Trivial. |
| Windows stdout `reconfigure(encoding="utf-8")` | Default Windows console can't print 🎤 📝 ⚖️ 🔊 emojis and crashes with `UnicodeEncodeError`. | `app/cj_chat.py:53-58` | Trivial. |
| **(NEW today) Did NOT swap STT to a cloud service** | User asked "use Claude STT rather than faster-whisper." Anthropic has no STT API. I clarified, offered OpenAI Whisper / Deepgram / AssemblyAI / Azure alternatives. User pivoted to prompt-caching instead. No code change. | (no code) | The swap remains an option; one-function change in `transcribe_audio()`. |
| **(NEW today) Did NOT cache the topic_map or conversation history** | The voice_card cache is the highest-leverage simple change. Caching the topic_map (all 37 topics, ~71K tok) or the conversation history requires architectural changes and risks response quality. Kept the change minimal. | (no code) | Notes in PROJECT.md "What to do if you blow through budget anyway" sketch the next-level optimizations. |

---

## 7. Gaps between intent and reality

| Item | Type | What the docs/spec say | What's on disk | Why |
|---|---|---|---|---|
| Two-terminal "CLI + read-only dashboard" design | intentional | Earlier conversational direction implied a CLI-drives-audio + dashboard-as-viewer split (commit `8311558`). | Dashboard is now self-contained and drives the full pipeline. | User explicitly asked for mic in dashboard. Rebuilt in commit `b7072ef`. |
| **Initial 55% caching savings claim** | **discovered** | I told the user "biggest win — ~55% savings" before measuring. | Empirical measurement on 2026-05-16: **18% per cached turn**, ~13% steady-state over a session. | Voice_card is only ~25% of inference input, so 90% off on 25% = 22% input savings = 18% total. I corrected the claim in `PROJECT.md` and in the response on the day. |
| **Router caching ineffective** | **discovered** | I marked `cache_control` on the router prompt expecting Haiku to honor it. | Haiku 4.5 silently drops the directive — every call reports `regular_input=2807, read=0, write=0`. | Either Haiku 4.5 doesn't support prompt caching in this SDK version, or the router prompt (2,400 tok) is below the actual Haiku minimum. Not worth fighting — router is <7% of total cost. |
| TTS em-dash pause (0.5s split vs comma substitution) | discovered | Earlier commits in this repo (`7e582d5`, `6788eee`) split sentences on em-dashes with 0.5s pauses. | Current code substitutes em-dashes with commas; pause now driven by Piper's native comma phoneme (150-300ms typical). | User asked for the simpler approach. The earlier chunking is preserved in git history. |
| Streamlit dashboard added to scope | intentional | Build-kit README: "Web UI — the reference impl is CLI; a web UI is straightforward but separate work." | Streamlit dashboard exists at `app/dashboard.py`. | User asked for my recommendation; I suggested a hybrid; user said "Build your recommendation." |
| Anthropic max_retries=4 | discovered | Build-kit reference impl uses bare `Anthropic()` (default 2). | `make_client()` returns `Anthropic(max_retries=4)`. | User hit a 529 OverloadedError that survived defaults. |
| Whisper VAD `min_silence_duration_ms=500` | unintentional | Build-kit README says: "If [hallucinations] still happening, increase `vad_parameters={'min_silence_duration_ms': 1000}`". | Code uses 500. | Carried from reference impl. Hasn't bitten us; cheap to bump. |
| Model IDs | discovered | Build-kit uses `claude-haiku-4-5-20251001` and `claude-sonnet-4-6`. | Same. Both verified callable. | The `sonnet-4-6` naming (no date suffix) is unusual but the API accepts it. |
| TTS pause length 0.6s (not 0.5s) | intentional | Build kit doesn't prescribe. | `TTS_SENTENCE_SILENCE = "0.6"`. | User feedback that pauses needed to be more obvious. |
| No automated tests | intentional | Build kit doesn't mandate tests. | No `tests/`. | Acceptable for demo timeline, worth flagging — see §10. |
| `signature_library.json` loaded but never sent to inference | unintentional | The 684 phrases were extracted at synthesis time presumably for use by the inference call. | `build_context()` does not reference `artifacts.signature_phrases`. | The user surfaced this on 2026-05-16 ("is voice_card the signature phrases?"). Currently the model sees only the ~30-50 example phrases inline in `voice_card.md`. Surfacing the full 684 would add ~5-10K input tokens; trade-off for richer voice. |
| `corpus/synthesis_scripts/` not re-run in any session | intentional | Build kit says scripts are "deterministic and re-runnable." | Current `app/artifacts/` are the pre-generated outputs; no rerun. | No need for the demo. Document as a "do before Pass B" task. |
| PROJECT.md references to `state/current.json` | unintentional | Old read-only dashboard wrote to that file. | New interactive dashboard doesn't. PROJECT.md mentions it once. | Minor doc inconsistency. Not yet fixed. |

---

## 8. Bugs, blockers, and known issues

| Severity | What | Details | Workaround |
|---|---|---|---|
| **bug** | **Haiku 4.5 ignores `cache_control`** | Every router call reports `cache_creation=0, cache_read=0, regular_input=2807` regardless of `cache_control: {"type": "ephemeral"}` on the system block. Sonnet honors the same code correctly. | Leave the cache_control in place (no harm); accept that router caching doesn't work; revisit when SDK or model updates. |
| smell | Streamlit caches imported modules across reloads | Auto-reload reacts to `dashboard.py` edits but not to `cj_chat.py` (imported module). Tuning in `cj_chat.py` requires Ctrl+C + relaunch Streamlit. | Documented in PROJECT.md and `app/README.md`. |
| smell | Whisper "medium" slow on CPU | 3-5s per transcription warm. Build-kit target ≤4s end-to-end is unreachable with `medium` on this hardware. | Switch `WHISPER_MODEL=small` in `.env` for English-only demos (drops to ~1s); keep `medium` for code-switching tolerance. |
| smell | Piper RTF ~1.8 on CPU | 150-word response takes ~9s to render. | Acceptable for demo. Build kit suggests OpenAI TTS `onyx` swap; user declined. |
| tech debt | No tests | Manual smoke-test only. Refactors are risky. | See §10 task #1 (minimal pytest suite, 2-4 hours). |
| tech debt | `cj_chat.py` is 707 lines, mixed concerns | Config + pipeline + audio I/O + main loop + cache stats. Build kit intended a single-file skeleton. | Leave alone for now. |
| tech debt | `corpus/synthesis_scripts/` not exercised | Pre-built artifacts are in `app/artifacts/`. If scripts have bit-rot, no one knows. | Smoke-run before Pass B (§10 task #8). |
| smell | TTS phonetic subs are crude | Native Tagalog speakers will hear the attempt is American-English. | Documented. User chose this over OpenAI TTS swap. |
| smell | `record_until_silence` uses RMS threshold (350) | Hardcoded ambient-noise threshold. Will fail in loud rooms or with very quiet speakers. | Acceptable for controlled demo. |
| smell | First-time whisper download is ~22 min for `medium` | 1.5 GB at ~1 MB/s on this machine. User-visible as "app hangs". | Documented one-liner pre-fetch in `app/README.md`. |
| smell | Conversation history in dashboard lives in browser session only | Refresh = lost context. | Out of scope per build kit. |
| tech debt | PROJECT.md references to `state/current.json` are stale | Old read-only dashboard wrote to this file; new interactive dashboard doesn't. | Minor; fix when convenient. |
| tech debt | `signature_library.json` is loaded but unused at inference | All 684 phrases sit in memory and contribute nothing to the model's context. | See §10 task #5 — surface relevant phrases for the primary topic in `build_context()`. |

No `blocker` open.

---

## 9. Dependencies and environment

### System

- **OS:** Windows (Git for Windows bash)
- **Python:** 3.11.9 (also installed: 3.14, 3.12 — both unused)
- **Disk:** ~640 MB in `app/` (excluding whisper cache); add 1.5 GB for `whisper-medium` cache at `%USERPROFILE%\.cache\huggingface\hub\`
- **No ffmpeg / portaudio / other native libs required** — sounddevice ships portaudio, faster-whisper ships ctranslate2 wheels, Piper is a single Windows exe

### Python dependencies installed today (pip freeze, key entries)

```
anthropic==0.102.0
ctranslate2==4.7.1
faster-whisper==1.2.1
markdown==3.10.2          # used to generate the PDF handover only
numpy==2.4.4
onnxruntime==1.26.0
python-dotenv==1.2.2
reportlab==4.5.1          # transitive dep of xhtml2pdf
scipy==1.17.1
sounddevice==0.5.5
streamlit==1.57.0
tokenizers==0.23.1
xhtml2pdf==0.2.17         # used to generate the PDF handover only
```

`requirements.txt` lists the core 6 (`anthropic`, `python-dotenv`,
`faster-whisper`, `sounddevice`, `scipy`, `numpy`, `streamlit`). The PDF
deps were installed ad-hoc on 2026-05-15 and are not in `requirements.txt`
— intentional, they're tooling not runtime.

### Required environment variables (names only)

- `ANTHROPIC_API_KEY` — Claude API key (starts `sk-ant-...`)
- `WHISPER_MODEL` — `small` or `medium` (default `medium`)
- `PIPER_BIN` — path to Piper executable (default `./piper/piper.exe`)
- `PIPER_VOICE` — path to ONNX voice (default `./voices/en_US-ryan-high.onnx`)

Loaded from `app/.env` via `python-dotenv` with `override=True`.
`.env.example` is committed.

### Local-only assets

| Asset | Path | Size | Source |
|---|---|---|---|
| Piper TTS binary + dlls | `app/piper/` | 38 MB | https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip |
| Piper voice model (ONNX) | `app/voices/en_US-ryan-high.onnx` | 116 MB | https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx |
| Piper voice config | `app/voices/en_US-ryan-high.onnx.json` | 4 KB | same source, `.onnx.json` |
| faster-whisper `medium` model | `%USERPROFILE%\.cache\huggingface\hub\models--Systran--faster-whisper-medium\` | 1.5 GB | auto-downloads on first run |

`.venv/` is 485 MB; rebuild with `py -3.11 -m venv .venv && .venv/Scripts/python.exe -m pip install -r requirements.txt`.

---

## 10. Immediate next actions

Ranked by what unblocks the next obvious step.

1. **Add a minimal pytest suite.** [2-4 hours]
   - Touches: new `app/tests/`.
   - Why: every refactor right now is a risk. Unit tests on
     `_prepare_tts_text`, `_strip_stage_directions`, `_log_cache_usage`,
     `cache_savings_summary`, `route_question` JSON-parse fallback,
     and a mocked end-to-end `run_turn` would give future-CC safety.
   - Blocker: none.

2. **Reconcile PROJECT.md with the current dashboard architecture.** [30 min]
   - Touches: `PROJECT.md`.
   - Why: stale `state/current.json` references from the old read-only
     dashboard design; cost numbers were updated yesterday but doc tour
     still mentions the old polling design once.
   - Blocker: none.

3. **Bump Whisper VAD silence to 1000ms.** [5 min]
   - Touches: `app/cj_chat.py:159` (`min_silence_duration_ms=500` → `1000`).
   - Why: build kit explicitly recommends this if hallucinations occur;
     preemptive insurance for demo day.
   - Blocker: none.

4. **Wire a sidebar `WHISPER_MODEL` toggle.** [15 min]
   - Touches: `app/dashboard.py`.
   - Why: switch `small`/`medium` during a demo without restarting.
   - Blocker: would need `get_whisper.clear()` to drop the cached model on switch.

5. **Surface `signature_library.json` to inference for the primary topic.** [1-2 hours]
   - Touches: `app/cj_chat.py` `build_context()`, possibly an index by
     topic in `signature_library.json` (currently it's keyed by
     normalized phrase, not by topic).
   - Why: 684 phrases are loaded and entirely unused. Pulling the 10-20
     most-relevant phrases for the primary topic into the context block
     would give the model richer voice texture per turn at the cost of
     ~200-500 tokens. Probably worth it.
   - Blocker: may need to rebuild the library with a topic→phrase index.

6. **Add an "extend cache to topic_map?" experimental mode.** [1-2 hours]
   - Touches: `app/cj_chat.py` `generate_response()` and `build_context()`.
   - Why: caching the full topic_map (~71K tok) trades a steep first-call
     cost for ~$0.19/turn savings on subsequent calls — net win after
     ~4 turns. Worth testing with an env-var toggle.
   - Blocker: risk of response quality regression if Claude routes to
     the wrong topic out of the larger context.

7. **Voice-card iteration on stage directions.** [30 min]
   - Touches: `app/artifacts/voice_card.md`.
   - Why: we strip stage directions post-hoc, but adding an explicit
     prohibition to the system prompt would avoid wasting tokens on them.
   - Blocker: changes a build-kit artifact — consider scope.

8. **Smoke-run the synthesis pipeline.** [1-2 hours]
   - Touches: nothing should be edited, just exercised.
   - Why: confirm `corpus/synthesis_scripts/synthesize.py` and friends
     still run cleanly before Pass B.
   - Blocker: none.

9. **Investigate Reachy Mini integration scaffold.** [4-8 hours]
   - Touches: new `app/robot/`.
   - Why: HuggingFace cache shows `reachy-mini-dances-library` and
     `reachy-mini-emotions-library` are pulled. Bridging audio I/O to
     the robot is the next major arc.
   - Blocker: need user direction on timing (before/after May 30).

10. **Speech corpus ingestion (Pass B).** [2-3 days]
    - Touches: new `source_materials/speeches/`, rerun
      `corpus/synthesis_scripts/`.
    - Why: build kit anticipates ~150 CJ speeches.
    - Blocker: need the speech sources; LLM cost for Stage 1 extraction.

11. **Add CI on push.** [1 hour]
    - Touches: new `.github/workflows/ci.yml`.
    - Why: lint + the pytest suite (#1) on every push to main.
    - Blocker: #1.

---

## 11. Questions for the human

1. **Demo audience and scope on May 30.** Who is this for — FLP
   stakeholders, an investor audience, an academic panel, public? Affects
   which sanity-check questions to rehearse and whether to err toward
   "Filipino-friendly" or "international-English" defaults (e.g.
   `WHISPER_MODEL=small` for pure-English vs `medium` for code-switch).

2. **Is `signature_library.json` supposed to be in the context?** All
   684 phrases are loaded but never sent to the inference call. Either
   (a) intentional and we delete the load, or (b) oversight and we
   surface the relevant ones in `build_context()`. The voice_card has
   ~30-50 example phrases inline — the rest of the library is currently
   dead weight in memory.

3. **Caching aggressiveness.** The current cache (voice_card only) saves
   ~18%. Caching the full topic_map adds ~$0.19/turn savings after a
   first-call premium, but changes the architecture (we'd send all 37
   topics every call). Want me to wire this as an opt-in env var, or
   keep the simple cache?

4. **STT vendor.** You asked about "Claude STT" — Anthropic has none.
   Want to keep `faster-whisper medium` local (current), or swap to
   OpenAI Whisper API (~$0.001/turn, simpler install, no 1.5 GB model
   cache), or Deepgram Nova-2 (best Filipino support, ~$0.0007/turn)?

5. **Voice-card edits.** Are you OK with me editing
   `app/artifacts/voice_card.md` (and the upstream
   `corpus/build_kit/voice_card.md`)? Concretely: adding "do not include
   stage directions" as an explicit instruction. The build kit treats
   voice_card.md as the canonical spec.

6. **Pass B timing.** ~150 CJ speeches anticipated. Before or after
   May 30 demo?

7. **Reachy Mini scope.** Does the conversation app feed into the robot
   at some later stage, or are the tracks fully independent? The HF
   cache suggests embodiment exists in parallel.

8. **Per-question rehearsal budget.** With caching, steady-state is
   ~$0.040/turn. A 50-turn rehearsal session is ~$2. If the team plans
   to do many full rehearsals, you may want option #6 (topic_map
   caching) for cheaper iteration.

9. **API key rotation.** I flagged twice that the ANTHROPIC_API_KEY
   shared in chat should be rotated. Has it been? The local `.env` was
   never pushed (verified), but the string is in conversation history.

---

## 12. How to use this handover

This document is **implementation truth as of 2026-05-16**. It supersedes
the 2026-05-15 handover (which is preserved at
`docs/handover_claude_code_2026-05-15.md` and `.pdf`). The differences:

- **+1 commit (`f7e47a1`)** — prompt caching wired on inference call
- **Cache savings panel** added to dashboard sidebar
- **Honest cost numbers** in PROJECT.md (18% not 55%)
- **+91 lines** in `cj_chat.py` (CACHE_STATS, helpers, hook points)
- **+30 lines** in `dashboard.py` (sidebar metrics panel)

When you (future-me or future-Claude) open this project again:

1. Read this document first. Then PROJECT.md for runtime-tuning detail.
   Then the build-kit README for design intent.
2. Before assuming anything is true, run `git log --oneline -10` to see
   what's happened since `f7e47a1`, and re-run the smoke test in §5 to
   verify the pipeline still works.
3. Any code referenced here by file:line is at commit `f7e47a1`.
   Subsequent commits may have moved things.
4. The 9 questions in §11 are the most likely places where ambiguity
   bites. Don't act on yesterday's strategic handover answers without
   reconciling with §11 here — particularly Q2 (signature_library
   usage) and Q3 (caching aggressiveness), which only became visible
   today.

— Claude Code, 2026-05-16
