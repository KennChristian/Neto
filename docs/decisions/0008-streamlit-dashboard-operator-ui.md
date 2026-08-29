# ADR-0008: Streamlit dashboard as operator UI

* Status: accepted
* Date: 2026-05-14
* Deciders: Doc, Janet

## Context and Problem Statement

The build kit's reference implementation is a CLI (`cj_chat.py`).
Demoing from a terminal is awkward — no per-turn sources visible, no
visible cost meter, no easy mic affordance. We considered staying
CLI-only, building a custom FastAPI + frontend, or using Streamlit.

## Decision Drivers

* Time-to-demo — May 30, 2026.
* Operator needs — see routed topics, confidence, source docs, and
  cost per turn at a glance.
* Mic affordance — browser mic is easier for a demo audience than a
  CLI push-to-talk loop.
* Implementation surface — minimize lines of code for the UI layer.

## Considered Options

* CLI-only (the reference implementation)
* Custom FastAPI backend + small frontend (HTMX or React)
* Streamlit single-file dashboard

## Decision Outcome

Chosen option: **Streamlit single-file dashboard**, because it gives
mic affordance (`st.audio_input`), audio playback, chat history,
sidebar sources, and the cache-savings panel in ~400 lines without a
separate backend service. The CLI is preserved as `cj_chat.py` for
headless smoke tests.

### Consequences

* Good: single-file UI in ~397 lines; no separate backend/frontend
  build step.
* Good: browser mic via `st.audio_input` — no native packaging story.
* Good: `@st.cache_resource` caches the artifacts, whisper model, and
  Anthropic client across reruns.
* Good: the CLI is preserved for headless / terminal scenarios.
* Bad: Streamlit reruns the whole script on every interaction —
  cognitive overhead when reading the code.
* Bad: imported-module caching — see [LL-004](../lessons/LL-004-streamlit-caches-imported-modules.md):
  edits to `cj_chat.py` require Ctrl+C + relaunch, not just dashboard
  reload.
* Bad: conversation history lives in `st.session_state` — a refresh
  loses context.
* Neutral: a `mic_counter` key trick is required to reset the
  `st.audio_input` widget between turns.

## Pros and Cons of the Options

### CLI-only

* Good, because matches the build kit's reference impl.
* Good, because zero UI dependencies.
* Bad, because no per-turn sources or cost meter visible to operator.
* Bad, because demo affordance is poor.

### Custom FastAPI + frontend

* Good, because full control over UX and protocol.
* Bad, because builds a separate backend service for a demo.
* Bad, because doubles or triples the code surface — more files, more
  toolchain.

### Streamlit single-file dashboard

* Good, because covers the operator needs in one file.
* Good, because browser mic without native packaging.
* Bad, because Streamlit's rerun model has its own gotchas (see
  consequences).

## More Information

[handover 2026-05-16](../handover_claude_code_2026-05-16.md) §6 row
"Streamlit `st.audio_input` for browser-side recording": *"Originally
I built a two-terminal CLI + read-only dashboard with file polling.
User asked for the dashboard to BE the input UI. `st.audio_input` is
Streamlit-native, no extra deps."*; §7 row "Streamlit dashboard added
to scope": *"User asked for my recommendation; I suggested a hybrid;
user said 'Build your recommendation.'"* Strategic handover doc not on
disk; date is per the instruction set that scoped this ADR.
