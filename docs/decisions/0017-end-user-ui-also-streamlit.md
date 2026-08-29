# ADR-0017: End-user web chat UI is also Streamlit (single-stack)

* Status: accepted
* Date: 2026-05-26
* Deciders: Janet

## Context and Problem Statement

[ADR-0008](0008-streamlit-dashboard-operator-ui.md) chose Streamlit
for the **operator** UI. The end-user web chat surface introduced in
[PLAN-0002](../implementation-plans/PLAN-0002-web-chat-ui.md) was
deliberately left open: §4 listed three candidate stacks (Streamlit
page extension, Next.js + FastAPI, static + websocket).

The question: do we extend the same Streamlit deployment to the
end-user surface, or stand up a separate front-end stack?

This is decided now so PLAN-0002 can land without an interrupting
ADR step.

## Decision Drivers

* **Single-stack maintenance cost.** Two front-end frameworks
  doubles the deploy / dependency / Python-vs-Node ops surface for a
  small team.
* **Sharing the runtime.** Operator dashboard and end-user chat both
  call into `app/cj_chat.py` (Phase 4,
  [PLAN-0001](../implementation-plans/PLAN-0001-runtime-app-haiku-router-sonnet-composer.md)).
  Streamlit shares the Python process trivially; a Node front-end
  would require a FastAPI/HTTP layer in between.
* **May 30 demo timeline.** Streamlit is shippable today; Next.js
  would require a new repo, deploy target, and engineering ramp.
* **UX polish trade-off.** Streamlit's mobile UX is mediocre and its
  customisation surface is limited. Acceptable for an FLP-curated
  audience that arrives via a known link; not acceptable for a mass
  consumer launch (which isn't the target).
* **Accessibility ceiling.** Streamlit's ARIA / keyboard nav surface
  is limited but adequate for a chat textarea + button + history.
* **Future migration cost.** If the end-user UI later moves to
  Next.js, the migration is bounded because the runtime
  (`cj_chat.py`) is unchanged. The cost is reauthoring the UI
  layer, not the conversation pipeline.

## Considered Options

1. **Single Streamlit deployment with two pages — operator + end-user (chosen)**.
   The end-user page is a new route in the existing Streamlit app
   with its own session state, identity-disclosure banner, and source
   provenance panel. Operator-only routes are gated by a side-channel
   (URL parameter, env var, or basic auth).
2. **Two Streamlit deployments** — same code, different config.
   End-user deployment runs only the chat page; operator deployment
   runs both.
3. **Next.js + FastAPI** — modern front-end stack with a thin Python
   HTTP wrapper over `cj_chat.py`.
4. **Static page + websocket** — minimal hosting; least flexible
   for streaming responses.

## Decision Outcome

Chosen option: **Single Streamlit deployment with two pages**.

The end-user surface lives in the same Streamlit codebase as
`app/dashboard.py`. New file (suggested): `app/pages/0_chat.py` (the
Streamlit `pages/` convention places this as a sibling route). The
operator dashboard becomes a gated page (operator-only) or moves to
`app/pages/1_operator.py`.

Routing / authorisation is **out of scope** for this ADR — Streamlit
has multiple workable options (URL param, basic auth, query-string
gating); PLAN-0002 Workstream A documents the choice picked at
implementation time.

### Consequences

* Good: single deployment, single dependency tree, single
  observability surface.
* Good: end-user UX inherits the existing Piper / Whisper plumbing
  unchanged — the voice loop ([ADR-0006](0006-local-stt-faster-whisper.md),
  [ADR-0007](0007-local-tts-piper-ryan-high.md),
  [PLAN-0006](../implementation-plans/PLAN-0006-voice-tts-integration.md))
  drops in cleanly.
* Good: rendering quality is identical across operator and end-user
  views, which means the FLP reviewer pass
  ([GUIDE-reviewer.md](../guides/GUIDE-reviewer.md)) walks the same
  surface visitors will see.
* Bad: Streamlit's mobile UX (page reload on widget change, no SPA
  feel) is mediocre. Accepted for the FLP-curated launch audience.
* Bad: Streamlit's ARIA / accessibility surface caps the Lighthouse
  ceiling. PLAN-0002 §9 acceptance criterion (Lighthouse ≥90) may
  need to be revisited if Streamlit can't hit it; relaxed to
  "Lighthouse ≥80, with documented manual accessibility pass" if
  needed.
* Bad: a future mass-consumer launch would likely require a separate
  Next.js (or similar) front-end. That's a future ADR; this ADR
  intentionally optimises for the May 30 demo and the FLP Museum
  kiosk path
  ([PLAN-0006](../implementation-plans/PLAN-0006-voice-tts-integration.md)).
* Neutral: operator-mode pages can be gated by an env var so the
  end-user deployment doesn't expose them.

## Pros and Cons of the Options

### Single Streamlit deployment (chosen)

* Good, because single dependency tree and deploy target.
* Good, because shares runtime / Piper / Whisper / cache state.
* Good, because shippable for May 30 with no new stack.
* Bad, because UX ceiling is lower than Next.js.

### Two Streamlit deployments

* Good, because cleaner separation of operator-only widgets from
  end-user view.
* Bad, because doubles the deploy surface; two processes to monitor.
* Bad, because session state and cache do not share — every visitor
  warms a new cache.

### Next.js + FastAPI

* Good, because higher UX polish and accessibility ceiling.
* Bad, because new stack, new deploy target, new ops burden.
* Bad, because requires authoring + maintaining a FastAPI shim that
  Streamlit doesn't need.
* Bad, because doesn't fit the May 30 timeline without dropping
  scope elsewhere.

### Static page + websocket

* Good, because cheapest hosting.
* Bad, because streaming responses, session memory, and sources
  panel all require custom JS — at which point we're rebuilding
  Streamlit poorly.

## More Information

- Operator-UI counterpart: [ADR-0008](0008-streamlit-dashboard-operator-ui.md).
- Plan that depends on this:
  [PLAN-0002](../implementation-plans/PLAN-0002-web-chat-ui.md) §4
  (Workstream A — Frontend stack selection).
- Voice loop integration:
  [PLAN-0006](../implementation-plans/PLAN-0006-voice-tts-integration.md).
