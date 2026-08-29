# docs/implementation-plans/ — MANIFEST

Implementation plans, one per concern. Each plan is single-purpose,
states scope-in / scope-out clearly, and defers verification to a
test spec in [`../test-specs/`](../test-specs/). Plans are designed
for later orchestrated execution — not run by the planning session
itself.

Plans cite ADRs as the *why*, lessons as the *what to avoid*, and
test specs as the *how to know it worked*.

| ID | File | Phase | Concern |
|---|---|---|---|
| PLAN-0001 | [PLAN-0001-runtime-app-haiku-router-sonnet-composer.md](PLAN-0001-runtime-app-haiku-router-sonnet-composer.md) | 4 | Evolve `app/cj_chat.py` + `dashboard.py` to consume Phase 1-3 artifacts under `corpus/voice/`. Haiku router → Sonnet composer with the new 35-topic taxonomy and voice card. |
| PLAN-0002 | [PLAN-0002-web-chat-ui.md](PLAN-0002-web-chat-ui.md) | 5 | Public-facing web chat UI for end users (distinct from operator dashboard). |
| PLAN-0003 | [PLAN-0003-embedding-audit-offline.md](PLAN-0003-embedding-audit-offline.md) | 6 | One-shot offline embedding audit to sanity-check the hand-curated taxonomy; report-only. |
| PLAN-0004 | [PLAN-0004-biography-gc001-ingestion.md](PLAN-0004-biography-gc001-ingestion.md) | 7a | Resolve `GC001`'s missing-date question, ingest the biography, route it. |
| PLAN-0005 | [PLAN-0005-book-corpus-addition.md](PLAN-0005-book-corpus-addition.md) | 7b | Ingest *A Centenary of Justice* — 24-25 book sections. Introduces a new type letter `B`. |
| PLAN-0006 | [PLAN-0006-voice-tts-integration.md](PLAN-0006-voice-tts-integration.md) | 8 | Voice / TTS surface for the FLP Museum hub kiosk. |
| PLAN-0007 | [PLAN-0007-topic-map-evolution-process.md](PLAN-0007-topic-map-evolution-process.md) | cross-cutting | Process for adding / retiring / tightening / loosening / splitting / merging topics in the curated taxonomy. |

## How to read these plans

- **Each plan is self-contained.** It states its goal, scope, work-
  streams, failure modes, edge cases, and acceptance criteria
  without requiring the reader to load other plans first.
- **Cross-references are advisory.** A plan may say *"see PLAN-X §3
  for context"* — that's a pointer, not a dependency.
- **Phase ordering is suggestive, not enforced.** PLAN-0001 + PLAN-
  0007 are foundational; the others can interleave based on FLP
  priorities and curator availability.
- **A plan is a hypothesis until execution.** Treat the acceptance
  criteria as the falsifier; if a plan's execution surfaces facts
  that contradict its hypothesis, file an ADR amendment or a new
  plan.
