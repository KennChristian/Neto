# CLAUDE.md

A conversation app that speaks as retired Philippine Chief Justice
Artemio V. Panganiban, grounded in his published corpus; demo target
**May 30, 2026**.

This file is the navigational entry point for any Claude Code or LLM
agent opening this repo. It points to where things live — not what
they do.

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
| [`app/`](app/) | The runnable conversation app — `cj_chat.py` (CLI + pipeline functions), `dashboard.py` (Streamlit UI), requirements, voice/Piper local assets. Reads corpus from `../corpus/voice/` and `../corpus/{type}/{theme}/`. | [app/MANIFEST.md](app/MANIFEST.md) |
| [`app/wake/`](app/wake/) | Wake-word stack (PLAN-0008). `engine.py` is the openWakeWord runtime wrapper; `wake_test.py` is the dev dashboard. `models/hey_cj.onnx` is the committed v2 classifier (locked threshold **0.40**); `models/hey_cj.v1.onnx` is the rollback. Training pipeline lives under `training/` (gN gates + Phase 1/2 retrain scripts); `data/` and `training/oww_*` trees are git-ignored — regenerated locally. | — |
| [`corpus/`](corpus/) | The runtime corpus: `voice/` (topic map, voice card, router prompt), `columns/` (64 paired `.md` + `.json`), `speeches/` (15 paired `.md` + `.json`). | [corpus/MANIFEST.md](corpus/MANIFEST.md) |
| [`scripts/`](scripts/) | The Phase 1-3 pipeline scripts: `generate_corpus_files.py`, `build_topic_map.py`, `apply_topic_paths.py`, plus the `run_smoke_test.py` and `check_paths.py` diagnostics. Idempotent. | — |
| [`data/`](data/) | Phase 1 inputs: `data/csv/` (3 curated CSVs) and `data/text/` (80 source `.txt` files). | — |
| [`docs/`](docs/) | Handover docs, ADRs (`docs/decisions/`), lessons (`docs/lessons/`), implementation plans (`docs/implementation-plans/`), test specs (`docs/test-specs/`), persona guides (`docs/guides/`). | [docs/MANIFEST.md](docs/MANIFEST.md) |
| [`reports/`](reports/) | Output reports from each pipeline run — `generation_report.json`, `validation_errors.log`, `topic_map_report.json`, `smoke_test_run.json`, `smoke_test_summary.json`. Regenerated on every run. | — |

> The earlier 89-doc pipeline (`app/artifacts/`, `corpus/build_kit/`,
> `corpus/prompts/`, `corpus/synthesis_scripts/`, `corpus/analysis/`,
> `corpus/manifest.json`) and `source_materials/` tree were removed
> when PLAN-0001 §A migrated the runtime to consume the Phase 1-3
> outputs directly. Book sections will return under `corpus/books/`
> per [PLAN-0005](docs/implementation-plans/PLAN-0005-book-corpus-addition.md).

## Conflict resolution

When documents disagree:

- **Implementation facts** (what code exists, file:line, what runs) → the latest Claude Code handover wins ([docs/handover_claude_code_2026-05-16.md](docs/handover_claude_code_2026-05-16.md)).
- **Design intent** (why a choice was made, scope, audience, the May 30 target) → the strategic handover wins when present; otherwise [PROJECT.md](PROJECT.md) and the relevant ADR in [docs/decisions/](docs/decisions/).
- **Runtime pipeline mechanics** → [PLAN-0001](docs/implementation-plans/PLAN-0001-runtime-app-haiku-router-sonnet-composer.md) and [`corpus/voice/voice_card.md`](corpus/voice/voice_card.md).

## What this repo is NOT

- **Not RAG / no embeddings.** Routing is a Haiku call against a hand-curated taxonomy (35 topics post-Phase-2; previously 37); there is no vector store and no similarity search.
- **Not a robot embodiment for May 30.** Reachy Mini integration is explicitly out of scope per the build-kit README; the demo is a conversation app on a laptop. See [ADR-0005](docs/decisions/0005-defer-robot-embodiment-for-may-30.md).
- **Not a multi-trigger wake word.** PLAN-0008 Phase 2 locked the wake phrase down to a single **"Hey CJ"** trigger; CJP / Hey CJP were dropped as voice targets and are surfaced by an on-screen prompt instead. The v2 classifier was retrained with real-voice positives (recall on held-out real clips: ~25-38% v1 → 100% offline / 80-90% live at threshold 0.40). See [PLAN-0008 progress](docs/implementation-plans/PLAN-0008-progress.md).
- **No automated tests yet.** Verification is currently manual via the six build-kit sanity questions plus interactive dashboard runs. Test *specifications* exist in [docs/test-specs/](docs/test-specs/); converting them into a runnable suite is part of the runtime work in [PLAN-0001](docs/implementation-plans/PLAN-0001-runtime-app-haiku-router-sonnet-composer.md).
