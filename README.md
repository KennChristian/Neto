# Supervaise FLP Project — CJ Panganiban Conversation App

A voice conversation app that speaks as retired Philippine Chief Justice
Artemio V. Panganiban, grounded in his published corpus.

The corpus (65 columns + 1 book of 19 chapters + 4 appendices = 89 documents,
~150K words) has been pre-processed into 37 canonical topics, 78 topic
relationships, and a library of signature phrases and mnemonic frameworks.

**Demo target:** May 30, 2026.

## Repo layout

```
.
├── README.md                ← you are here
├── app/                     ← the runnable conversation app
│   ├── cj_chat.py           ← entrypoint (text + voice modes)
│   ├── artifacts/           ← copy of the corpus artifacts the app loads
│   └── README.md            ← run instructions
├── corpus/                  ← the source corpus and pre-processing pipeline
│   ├── build_kit/           ← starting point for builders (voice card, router prompt, reference impl)
│   ├── analysis/
│   │   ├── synthesis/       ← Stage 3 canonical artifacts (topic map, graph, frameworks, etc.)
│   │   └── topics/          ← Stage 1 per-doc extractions (89 docs)
│   ├── prompts/             ← the extraction/synthesis prompts
│   └── synthesis_scripts/   ← the deterministic Python that produced synthesis/
└── source_materials/        ← original published writing (books + columns)
```

## Pipeline

```
[mic]
  ↓ faster-whisper (local STT)
User question (text)
  ↓ Claude Haiku 4.5 (router) — picks 1-3 relevant topics
1-3 canonical topic IDs from topic_map.json
  ↓ retrieval: load topic data + 2-3 raw doc extractions
Context block (10-20K tokens, focused)
  ↓ Claude Sonnet 4.6 (inference, in CJ's voice)
Response text
  ↓ Piper (local TTS)
[speakers]
```

Two Claude API calls per turn. Everything else runs locally.

## Quick start

See [`app/README.md`](app/README.md) for full run instructions. The fastest
sanity check (no audio needed):

```bash
cd app
.venv/Scripts/python.exe cj_chat.py --text "What is the rule of law?"
```

For the full demo, run the Streamlit chat app (mic input, text fallback,
inline audio playback, sources expander):

```bash
cd app
.venv/Scripts/streamlit run dashboard.py
```

The CLI (`cj_chat.py`) is still available for headless / terminal use.

## Cost & performance targets

| Metric | Target |
|---|---|
| End-to-end turn latency | ≤ 4s |
| Per-turn cost | ≤ $0.02 |
| Router accuracy | ≥ 85% on demo questions |
| 50-turn demo cost | ~$0.80 |

## What's in scope for May 30

- Voice conversation interface (CLI; mic + speakers)
- 89-doc corpus (columns + book)
- Local STT/TTS, two Claude API calls per turn

## What's out of scope (deliberate)

- ~150 CJ speeches (Pass B addition)
- Robot embodiment (Reachy Mini wiring)
- Web UI
- Multi-user session management
- Memory beyond the last 10 turns

See [`PROJECT.md`](PROJECT.md) for the full project document — scope,
architecture, run instructions, verification suite, performance numbers,
cost model, tuning knobs, changelog, and troubleshooting.

See [`corpus/build_kit/README.md`](corpus/build_kit/README.md) for the
original build-kit spec and pipeline-stage rationale.

---

*Maraming salamat po.*
