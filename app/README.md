# CJ Panganiban Conversation App

A voice conversation app that speaks as retired Philippine Chief Justice
Artemio V. Panganiban, grounded in his published corpus (65 columns + 1 book of
19 chapters + 4 appendices = 89 documents, ~150K words).

Built per `corpus/build_kit/README.md`. This directory is the runnable app.

## Pipeline

```
[mic]
  ↓ faster-whisper (local STT)
User question (text)
  ↓ Claude Haiku 4.5 (router)
1–3 canonical topic IDs from topic_map.json
  ↓ load topic data + 2-3 raw doc extractions
Context block
  ↓ Claude Sonnet 4.6 (inference, in CJ's voice)
Response text
  ↓ Piper (local TTS)
[speakers]
```

Two Claude API calls per turn. Everything else runs locally.

## Quick start

### Prerequisites

- Python 3.11 (3.12 also works; faster-whisper builds are most stable on 3.11)
- A working microphone and speakers
- An Anthropic API key in `.env` (file is gitignored)

### Run the smoke test (text-only — no audio)

```bash
.venv/Scripts/python.exe cj_chat.py --text "What is the rule of law?"
```

This skips STT/TTS and exercises the full router → inference pipeline. You
should see the routing decision (primary topic, secondary, confidence) and a
response written in CJ's voice (twin beacons, *Au contraire*, "Cheers!" etc.).

### Run the full voice loop

```bash
.venv/Scripts/python.exe cj_chat.py
```

Press Enter to start each turn. Speak your question. The recorder stops
automatically after ~1.2s of trailing silence. The app transcribes, routes,
generates, and speaks the response. Ctrl+C to exit.

### Run the chat dashboard (the demo UI)

The dashboard is a self-contained Streamlit chat app — mic input, text
fallback, inline playback of CJ's spoken response, and a Sources expander
showing which corpus topics matched. It's the primary UI for the demo.

```bash
.venv/Scripts/streamlit run dashboard.py
```

Then open the URL Streamlit prints (default `http://localhost:8501`). The
first time you click 🎤 in the browser, Chrome/Edge will ask for microphone
permission — accept it.

**How it works:**
- 🎤 records in the browser; click record, speak, click stop
- Or type into the "…or type it (fallback)" box at the bottom
- The same pipeline runs: faster-whisper → router (Haiku) → inference (Sonnet) → Piper TTS
- CJ's response plays inline; the Sources expander shows the primary topic,
  secondary topics, confidence, router reasoning, and the top 3 source
  documents that informed the answer
- Conversation history is kept in the browser session (last 10 turns are
  passed to the inference call for context); "🧹 Clear conversation" in the
  sidebar resets it
- Sidebar toggle "Generate Piper voice" — turn off to skip TTS (~5-10s
  faster per turn) if you only want text replies during testing

The CLI (`cj_chat.py`) is still available for headless / terminal use and
covers the same pipeline.

## Repo layout

```
app/
├── cj_chat.py              # CLI entrypoint (text + voice modes, drives audio I/O)
├── dashboard.py            # Streamlit chat app (mic + text fallback, the demo UI)
├── state/                  # Runtime artifacts e.g. generated TTS wavs (GITIGNORED)
│   └── tts/
├── README.md               # You are here
├── .env                    # ANTHROPIC_API_KEY + paths (GITIGNORED — never commit)
├── .gitignore
├── requirements.txt
├── artifacts/              # Corpus artifacts loaded at startup
│   ├── voice_card.md       # Inference system prompt (CJ's voice)
│   ├── router_prompt.md    # Router system prompt
│   ├── topic_map.json      # 37 canonical topics
│   ├── topic_graph.json
│   ├── entity_index.json   # 69 people + 16 cases + 15 laws
│   ├── frameworks.json     # 10 mnemonic frameworks
│   ├── signature_library.json
│   └── topics/             # 89 raw per-doc extractions
├── piper/                  # Local Piper TTS binary + dlls (Windows build)
│   └── piper.exe
└── voices/
    ├── en_US-ryan-high.onnx       # Voice model (~120 MB)
    └── en_US-ryan-high.onnx.json
```

`piper/` and `voices/` are gitignored — they're large binary assets installed
per-machine. See "From-scratch setup" below to reinstall.

## From-scratch setup

```bash
# 1. Create venv
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -U pip
.venv/Scripts/python.exe -m pip install -r requirements.txt

# 2. Create .env (DO NOT commit) — see .env.example for the format
cp .env.example .env
# Edit .env and paste your ANTHROPIC_API_KEY

# 3. Install Piper TTS (Windows binary)
#    Download piper_windows_amd64.zip from
#    https://github.com/rhasspy/piper/releases
#    and extract into ./piper/

# 4. Download the voice model
#    https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ryan/high
#    Save both files into ./voices/:
#       en_US-ryan-high.onnx
#       en_US-ryan-high.onnx.json

# 5. (Optional) Pre-fetch the whisper model — it auto-downloads on first run
.venv/Scripts/python.exe -c "from faster_whisper import WhisperModel; WhisperModel('medium', device='cpu', compute_type='int8')"
```

## Configuration

Set these in `.env`:

| Var | Default | What |
|---|---|---|
| `ANTHROPIC_API_KEY` | (required) | Claude API key |
| `WHISPER_MODEL` | `medium` | `small` (English-only) or `medium` (Filipino/English code-switch). 769 MB download. |
| `PIPER_BIN` | `./piper/piper.exe` | Path to the Piper executable |
| `PIPER_VOICE` | `./voices/en_US-ryan-high.onnx` | Voice model path |

## Sanity-check questions

From the build-kit README — verify the voice and routing before demo day:

| Question | Expected |
|---|---|
| "What is the rule of law?" | → `rule_of_law` high. Mentions twin beacons, 1987 Constitution. |
| "Tell me about your mentor." | → `mentor_salonga` high. Tells the 1956 FEU strike anecdote. |
| "What's your favorite color?" | → `personal_formation` low. Gracefully declines, redirects. |
| "Tell me about the Foundation." | → `flp_institutional_history` high. 2011 founding, twin beacons. |

## Cost & performance

A 50-turn demo session: ~$0.80 total (Haiku router + Sonnet inference).

Targets:
- End-to-end turn latency: ≤ 4s (TTS streaming is the typical bottleneck)
- Per-turn cost: ≤ $0.02
- Router accuracy: ≥ 85%

## Architecture notes

- **Two Claude calls (router + inference) instead of one** keeps the inference
  context small (10–20K tokens for 1–3 topics + 2–3 raw docs) rather than
  stuffing 320KB of topic_map into one giant call. ~$0.015/turn vs ~$3/turn.
- **Local STT/TTS** keeps audio off the network for cost, latency, privacy,
  and demo reliability (only Claude calls need wifi).
- **The voice card is the system prompt** on the inference call, not a user
  message. If CJ sounds generic, double-check that wiring first.

## What's not yet here

Per the build-kit README, these are deliberately out of scope for the May 30
demo:
- Speech corpus (~150 CJ speeches — Pass B addition)
- Multi-turn memory beyond last 10 turns (already trimmed in code)
- Robot embodiment (Reachy Mini wiring)
- Web UI (CLI only)
- Response caching
- Real-time interruption handling

## Troubleshooting

- **"Router output unparseable"** — Haiku occasionally adds preamble. The
  reference impl strips code fences; if it persists, drop router temperature
  to 0.
- **Whisper hallucinates "Thank you" on silence** — VAD is on by default.
  If still happening, bump `vad_parameters={"min_silence_duration_ms": 1000}`
  in `transcribe_audio`.
- **Piper sounds robotic** — that's Piper. Swap to OpenAI TTS `onyx` or
  ElevenLabs for production-quality voice. `synthesize_speech()` is the
  single point of change.
- **CJ sounds generic / not like himself** — confirm `voice_card.md` is being
  loaded as the `system=` parameter on the inference call (not a user
  message). Confirm model is `claude-sonnet-4-6` or better.

---

*Maraming salamat po.*
