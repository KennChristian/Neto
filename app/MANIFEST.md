# app/ — MANIFEST

The runnable conversation app. Two entrypoints share one pipeline:
`cj_chat.py` (CLI) for smoke tests and headless voice loop, and
`dashboard.py` (Streamlit) as the primary UI. Both load corpus
artifacts from `../corpus/voice/` and `../corpus/{type}/{theme}/`
(per PLAN-0001 §A). The local Piper / Whisper assets live in
`app/voices/` and `app/piper/`.

| ID | File | Description |
|---|---|---|
| 0001 | [README.md](README.md) | App-scoped run instructions — touch when install steps, env vars, or the quick-start commands change. |
| 0002 | [cj_chat.py](cj_chat.py) | CLI entrypoint plus all pipeline functions (input gate, router, retrieval, streaming composer, fidelity check, STT, TTS, cache stats). Touch when changing pipeline behavior; the dashboard imports from here. Artifact paths resolve via `Config` (defaults: `../corpus/voice/` and `../corpus/{type}/{theme_folder}/`). Env overrides: `CORPUS_ROOT`, `VOICE_DIR`, `ROUTER_PROMPT`, `ROUTER_MODEL`, `INFERENCE_MODEL`, `WHISPER_MODEL`, `PIPER_BIN`, `PIPER_VOICE`, `DOTENV_PATH`, `ANTHROPIC_API_KEY`. |
| 0003 | [dashboard.py](dashboard.py) | Streamlit chat UI — mic input (lazy-loaded Whisper), text fallback, streaming composer output, autoplay Piper TTS, Sources expander, cache savings panel, env diagnostic sidebar, pre-flight API-key check. Reachy Mini SVG avatar at the top. |
| 0004 | [requirements.txt](requirements.txt) | Pinned core Python deps (anthropic, python-dotenv, faster-whisper, sounddevice, scipy, numpy, streamlit). Touch when adding a runtime dep. |

## Subdirectories

| ID | Path | Description |
|---|---|---|
| S0001 | piper/ | Piper TTS Windows binary plus dlls. Gitignored (~38 MB). Install from the Piper release bundle per [README.md](README.md). |
| S0002 | voices/ | Piper ONNX voice model (`en_US-ryan-high`) plus its `.onnx.json` config. Gitignored (~116 MB). Source: HuggingFace `rhasspy/piper-voices`. |

## Removed

`app/artifacts/` previously held the 89-doc legacy pipeline's
materialised topic map, voice card, router prompt, frameworks,
entity index, signature library, topic graph, and per-doc
extractions. PLAN-0001 §A migrated the runtime to consume
`corpus/voice/` and `corpus/{columns,speeches}/` directly, and the
legacy directory was deleted in the cleanup commit that followed.
