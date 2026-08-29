# First-run guide — install, configure, smoke-test

Audience: **a developer or operator opening this repo for the first
time** and trying to get the chat app — with both **voice input
(STT)** and **voice output (TTS)** — running in the browser.

The intended flow:

```
   venv on the right drive  →  install deps  →  set API key  →
   install Piper + voice model  →  launch dashboard  →  smoke test
```

If the dashboard takes minutes to load, you almost certainly hit one
of the pitfalls in §1. Read §1 first, then walk §2 → §6 in order.

The app's surfaces:

- **Reachy Mini avatar** at the top — a stylised SVG of the robot with
  a subtle eye-pulse to signal it's alive between turns.
- **Mic input** — record in the browser; faster-whisper transcribes
  locally.
- **Text input** — type in the chat box (a fallback for mic).
- **Streaming transcript** — Sonnet's response renders **token by
  token** as it composes, via `st.write_stream`. You read it forming
  in real time, no waiting for the full draft.
- **Piper audio output** — once the full response is composed, Piper
  synthesises it and the audio player auto-plays inline. The
  Reachy Mini speaker grille below the avatar isn't animated, but the
  audio waveform in the player serves as the visible "speaking" cue.
- **Sources panel** — collapsed by default under each response; shows
  the routed topics and which source documents the composer used.

All surfaces are designed to work together. The smoke test in §6
exercises all of them.

---

## 1. Pitfall — Don't run `cj_chat.py` through Streamlit

`cj_chat.py` is the **CLI entrypoint**, not a Streamlit app. If you
run:

```
streamlit run cj_chat.py     ❌  DO NOT
```

Streamlit will execute `cj_chat.py` top-to-bottom, eagerly load the
1.5 GB faster-whisper model in `main()`, then block forever on
`input("Press Enter to speak…")`. That's the long hang you saw.

The dashboard is **`app/dashboard.py`**:

```
streamlit run app/dashboard.py                  ✅  from the repo root
streamlit run dashboard.py                      ✅  from inside app/
```

The dashboard loads Whisper **lazily** — it only loads on the first
mic recording, never on page open. So opening the dashboard is fast
regardless of which Whisper model is configured.

(There's a guard in `cj_chat.py` that detects `streamlit run` and
exits with a clear message — if you saw a hang instead, you were on
a pre-guard version. The latest exits with instructions.)

---

## 2. Set up the venv (works on any drive)

If your `.venv` lives on D:, E:, or anywhere off C:, that's fine —
absolute paths only.

PowerShell, venv on D:

```powershell
# 1. Pick a location for the venv
cd D:\projects\flp\cj-app

# 2. Create the venv with your Python
C:\Users\ASUS\AppData\Local\Programs\Python\Python311\python.exe -m venv .venv

# 3. Activate
.\.venv\Scripts\Activate.ps1

# 4. Install runtime deps
pip install -r app\requirements.txt

# 5. Verify
python -c "import anthropic, streamlit, faster_whisper, sounddevice, scipy; print('OK')"
```

The venv has its own `python.exe` and `streamlit.exe`. Use those:

```
.\.venv\Scripts\python.exe scripts\run_smoke_test.py
.\.venv\Scripts\streamlit.exe run app\dashboard.py
```

Or `Activate.ps1` once per shell and drop the explicit path.

---

## 3. Voice loop is fully hosted — no local model downloads

[ADR-0018](../decisions/0018-openai-stt-tts-with-claude-chat.md)
replaced the local Whisper + Piper stack with **OpenAI Whisper**
(STT) + **OpenAI TTS** (`tts-1` with the `nova` voice by default).
Both calls happen through `app/voice_io.py`:

- **STT** is one Whisper call per recording — push-to-talk, no
  always-on mic, no per-minute Realtime API.
- **TTS** fires per-sentence in parallel (`asyncio.gather`) and
  concatenates the MP3 chunks. Total wall-clock TTS time ≈ slowest
  single sentence, not the sum.

This costs ~$0.001 per STT call and ~$0.003-$0.005 per response in
TTS — about $0.005 of voice-loop overhead per turn, 10-20× cheaper
than the Realtime API.

No model downloads. No `HF_HOME`. No Piper install. Just the
`OPENAI_API_KEY` in your `.env`.

---

## 4. (Removed in ADR-0018) — Piper / Whisper local install

The old guide steps for `HF_HOME`, `WHISPER_MODEL=small`, and the
Piper binary + voice download are no longer required for the online
voice loop. They remain valid only for the offline kiosk fallback
captured in
[PLAN-0006](../implementation-plans/PLAN-0006-voice-tts-integration.md).

---

## 5. `.env` configuration (required)

The router + composer call the Anthropic API. `cj_chat.py` searches
for a `.env` in **three locations** at import time and merges them
(later values win):

1. `<cwd>/.env`
2. `<repo>/.env`
3. `<repo>/app/.env`  ← most specific, recommended

`DOTENV_PATH=<absolute path>` overrides all three.

Minimum required keys (both):

```
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
```

Anthropic powers chat (router + composer + fidelity); OpenAI powers
STT + TTS per [ADR-0018](../decisions/0018-openai-stt-tts-with-claude-chat.md).
A canonical template is at `.env.example` in the repo root.

Optional overrides (defaults shown):

```
ROUTER_MODEL=claude-haiku-4-5-20251001
INFERENCE_MODEL=claude-sonnet-4-6
OPENAI_STT_MODEL=whisper-1
OPENAI_TTS_MODEL=tts-1
OPENAI_TTS_VOICE=spruce              # CJP default — calm male. Other male: onyx, echo, fable, ash, ballad, sage, verse.
OPENAI_TTS_SPEED=0.80                # relaxed judicial cadence (80% of normal)
```

The dashboard's sidebar shows which `.env` files were loaded and
which models are active — easy to verify at a glance once Streamlit
is up.

Verify the key resolves before launching:

```
.\.venv\Scripts\python.exe -c "import os; print(bool(os.environ.get('ANTHROPIC_API_KEY')))"
```

If that prints `False`, the dashboard's pre-flight banner will tell
you exactly which `.env` files were searched. Add the key to one of
them and reload.

---

## 6. Launch + smoke-test in the browser

Once §2–§5 are done:

```
.\.venv\Scripts\streamlit.exe run app\dashboard.py
```

The browser opens at `http://localhost:8501`. You should see:

- **Header**: an SVG **Reachy Mini avatar** beside the title
  ("⚖️ With Due Respect — Reachy Mini × retired Chief Justice Artemio
  V. Panganiban"). The two green eyes pulse gently between turns.
- **Sidebar**:
  - **Generate Piper voice** toggle (on by default)
  - **Show TTS chunks (debug)** toggle (off by default)
  - **🧹 Clear conversation** button
  - Pipeline summary + Whisper model name + Topics loaded count
- **Input row**:
  - 🎤 mic recorder
  - 💬 chat input ("…or type it (fallback)")

### 6a. Text + TTS smoke (no Whisper needed)

Type into the chat box: *"What is the rule of law, and why does it
matter today?"*

Expected, in order:

1. Your message renders immediately (transcript).
2. Status block: *"🚪 Scope: in_corpus"* — the Input Gate clears the
   question for routing.
3. Status block: *"🧭 Routed to rule_of_law (high)"*.
4. **CJ's response streams in token by token** under a "💭 CJ:"
   header — you can read it forming in real time.
5. (Quick) Status block: *"🔊 Synthesizing voice…"* (~5-10s on CPU
   after streaming finishes).
6. Audio player appears below the response and **auto-plays**.
7. If the fidelity check flags anything (it normally won't for clean
   in-corpus questions), an inline ⚠ warning appears below the
   response — the response itself stays visible.
8. **Sources** expander below the audio — click to verify the
   routing matched expectations.

This validates: Input Gate + router + streaming composer + advisory
fidelity + Piper TTS. **No Whisper involved** because you typed.

### 6b. Mic + STT + TTS smoke (full voice loop)

Click the mic button. Speak your question. Stop the recording.

Expected:

1. First time only: *"Loading faster-whisper (first time downloads
   the model)…"* — this is the ~470 MB download for `small` or
   1.5 GB for `medium`. Subsequent recordings reuse the cache.
2. *"Transcribing your question…"* — faster-whisper runs locally.
3. Your transcribed text renders as the user message.
4. Pipeline proceeds as in §6a.

This validates: faster-whisper + router + composer + fidelity + Piper.

### 6c. Identity-probe smoke

Type: *"Are you really Chief Justice Panganiban?"*

Expected:

1. Status: *"🚪 Scope: identity_probe"* — Input Gate caught it.
2. Status: *"🧭 Identity probe → META path"* — router bypassed.
3. Streaming response includes *"I am a robot rendering of my own
   voice"* (or a close paraphrase) — the honesty rule fires.
4. Sources panel below shows the `robot_identity_meta` topic with no
   source docs (META has zero corpus docs by design).

### 6d. Run the automated 30-question smoke (CLI)

Once the browser smoke is green, the headless 30-question run
captures full metrics across all themes:

```
.\.venv\Scripts\python.exe scripts\run_smoke_test.py
```

Outputs `reports/smoke_test_run.json` and
`reports/smoke_test_summary.json`. Verdict GREEN / YELLOW / RED;
exit code 0 / 1 / 2. Takes ~10 minutes, costs ~$1.80.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Browser hangs on Streamlit "Running..." for minutes | You ran `cj_chat.py` instead of `dashboard.py` | `Ctrl+C` and use `app/dashboard.py` (§1) |
| First mic recording downloads 1.5 GB | Default `WHISPER_MODEL=medium` | Set `WHISPER_MODEL=small` (and `HF_HOME` to keep it off C:) per §3 |
| `ImportError: No module named anthropic` | Wrong venv active | `.\.venv\Scripts\Activate.ps1` per §2 |
| `ANTHROPIC_API_KEY` missing error | `.env` not loaded | Check `app\.env` exists and has the key (§5) |
| 429 / 529 from Anthropic | Rate limit / overloaded | SDK auto-retries 4×; wait 30s and try again |
| TTS toggle on but no audio | Piper binary not found | Check `PIPER_BIN` and `PIPER_VOICE` (§4) — also try running `& $env:PIPER_BIN --help` |
| TTS audio mangles Tagalog | Piper Ryan-high is English-only — Tagalog gets phonetic substitution per `TTS_FOREIGN_SUBSTITUTIONS` | Known limitation; tweak the table in `cj_chat.py` or wait for [PLAN-0006](../implementation-plans/PLAN-0006-voice-tts-integration.md) §4 |
| Sources panel empty | Routing returned a topic with no docs | Click "Show TTS chunks (debug)" sidebar toggle for more diagnostic info; check `reports/topic_map_report.json` |
| `streamlit` command not found | venv not activated | `.\.venv\Scripts\streamlit.exe run app\dashboard.py` (full path) |
| Mic button silent / no recording | Browser denied mic permission | Check the address bar for the camera/mic icon; allow it for `localhost:8501` |
| Response stream stalls mid-sentence | Streaming network hiccup | Anthropic SDK auto-retries; if it errors out the API-error banner shows. Retry the same question. |
| Fidelity ⚠ banner appears on a normal question | Haiku flagged something conservatively | Read the banner reason; if it's a sub-judice catch on a live case that's expected (TS-006 §4 shows the same pattern). The response stays — fidelity is advisory in the browser, strict on the CLI smoke runner. |
| Reachy Mini avatar not animating | Browser blocking SVG `<animate>` | Some strict CSP policies block SMIL animations; the avatar still renders statically. Cosmetic only. |

---

## 8. What runs where (mental model)

```
Browser
  ↑↓ (mic capture + audio playback in the page)
  │
Streamlit Python process
  ├── Local network: Anthropic API     (Haiku gate/router/fidelity + Sonnet composer)
  ├── Local file:    corpus/voice/*    (topic_map, voice_card, router_prompt)
  ├── Local file:    corpus/{columns,speeches}/*  (per-doc bodies + JSON)
  ├── Local CPU:     faster-whisper    (STT, lazy-loaded on first mic click)
  └── Local CPU:     piper.exe         (TTS, invoked per response when toggle on)

Disk layout (all configurable via env):
  ANTHROPIC_API_KEY   →  app\.env
  faster-whisper model→  $HF_HOME/hub/models--Systran--faster-whisper-{size}/
  Piper binary        →  $PIPER_BIN
  Piper voice         →  $PIPER_VOICE
```

The runtime needs the Anthropic API (network) plus the artifacts in
`corpus/voice/` and `corpus/{columns,speeches}/`. faster-whisper and
Piper are local — once installed, they run offline.
