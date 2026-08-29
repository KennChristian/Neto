# PLAN-0002: Web chat UI for end users

* Status: draft
* Phase: 5
* Owner: TBD
* Depends on: [PLAN-0001](PLAN-0001-runtime-app-haiku-router-sonnet-composer.md)
  (runtime app must be wired to Phase 1-3 artifacts)
* Verified by: manual UX walkthroughs from
  [GUIDE-end-user.md](../guides/GUIDE-end-user.md);
  [TS-005](../test-specs/TS-005-end-to-end-pipeline-smoke.md) for
  pipeline correctness
* Related ADRs:
  [0008](../decisions/0008-streamlit-dashboard-operator-ui.md)
  (operator UI — sibling page in the same Streamlit deployment);
  [0017](../decisions/0017-end-user-ui-also-streamlit.md) (locks
  end-user UI to Streamlit too)

## 1. Goal

A web chat interface aimed at the **end-user persona** described in
[GUIDE-end-user.md](../guides/GUIDE-end-user.md) — a Filipino civic
reader, law student, FLP stakeholder, or curious visitor — interacting
with the CJP conversation app in a browser.

This is distinct from `app/dashboard.py`, which is the **operator**
UI ([ADR-0008](../decisions/0008-streamlit-dashboard-operator-ui.md)).

## 2. Scope

**In scope**
1. Public-facing chat page: text input, response rendering, history
   scroll, "new conversation" button.
2. Identity disclosure UI affordances — first response on a new
   session always carries the "I am a robot rendering of my own
   voice…" line, plus a persistent "About this app" link.
3. Topic / source provenance display (collapsed by default): "this
   response drew on SA136, CA001". Clickable expansion shows title
   + date + 1-paragraph summary.
4. Rate-limit + soft moderation at the gateway (no PII, no harassment).
5. Mobile-responsive layout.
6. Accessibility: keyboard navigation, ARIA labels, screen-reader pass.
7. Light theming aligned with FLP branding (colors / logo / mark).

**Out of scope**
- Voice input / output ([PLAN-0006](PLAN-0006-voice-tts-integration.md)).
- User accounts / login.
- Multi-language UI (English only at launch; Tagalog responses come
  from the voice card's code-switching, not from UI strings).
- Comment / share features.

## 3. Architecture

```
Browser  ←HTTPS→  Streamlit page  ──in-process──→  cj_chat runtime  ←→  Anthropic API
                  (app/pages/0_chat.py)             (PLAN-0001)
```

Locked by [ADR-0017](../decisions/0017-end-user-ui-also-streamlit.md):
the end-user UI runs in the same Streamlit deployment as the operator
dashboard ([ADR-0008](../decisions/0008-streamlit-dashboard-operator-ui.md)),
with operator-only widgets gated.

## 4. Workstream A — Frontend page (Streamlit)

Per [ADR-0017](../decisions/0017-end-user-ui-also-streamlit.md):

1. Add `app/pages/0_chat.py` as the end-user route in the existing
   Streamlit `app/`. Streamlit's `pages/` convention multi-routes
   automatically.
2. Move operator-only widgets (Sources expander details, cost panel,
   cache-savings panel, per-turn timeline) behind a gating flag
   (`OPERATOR_MODE=1` env var or `?operator=1` URL param) so the
   end-user route shows only the chat surface.
3. The end-user route consumes `cj_chat.py`'s pipeline functions
   directly — no HTTP shim required.
4. Apply FLP branding (logo, colors) per FLP design assets.

## 5. Workstream B — Identity disclosure UI

The honesty rule (voice_card.md §"Honesty rule") is a *content*
guarantee. The UI augments it:

1. **First-message banner**: every new session shows, above the input
   box: *"You are chatting with an AI built by the Foundation for
   Liberty and Prosperity. Its voice is drawn from Chief Justice
   Panganiban's published writings."*
2. **Persistent footer link** to an "About this app" page that
   reproduces the canonical *"I am a robot rendering of my own
   voice…"* statement.
3. **System message** rendered before the first model turn: *"I am
   here to share Chief Justice Panganiban's published views. Ask me
   anything about constitutional law, FLP's work, or his life."*

## 6. Workstream C — Source provenance display

Each response carries a collapsed "Sources" accordion below the text.
Expansion reveals, per source doc:

- ID (e.g., `SA136`)
- Title (e.g., *"Maraming Salamat Po"*)
- Date (e.g., 2006-12-06)
- One-paragraph summary
- Outbound link (if `source_url` is present)

This makes the corpus-grounded nature of the app legible to skeptical
readers and is itself a partial answer to the honesty rule.

## 7. Failure modes and observability

| Failure mode | Detection | UX response |
|---|---|---|
| Runtime API down | Healthcheck endpoint | "I'm temporarily unavailable. Please try again in a moment." |
| Rate limit hit | 429 from gateway | "I'm receiving too many questions right now. Please wait 30 seconds." |
| Content policy violation | Moderation pre-pass | "I cannot respond to that request." (with a "What can I ask?" hint) |
| Response too long for UI | Token cap (e.g., 600 tokens) | Truncate with "Read full response" expander |
| Streaming hiccup | Timeout | Fall back to non-streaming render after 8s |
| Sources panel empty (no docs grounded) | Pipeline result | Show "Responding from established principles — no specific document grounded." |

Observability:
- Per-session: turn count, total $, average latency.
- Anonymous error logs (no user input recorded beyond session-id).
- Dashboard for FLP admin: weekly active sessions, top topics
  routed, refusal rate.

## 8. Edge cases

- **User asks "are you Chief Justice Panganiban?"** — META path fires;
  honesty rule response.
- **User pastes ~5K-character question** — gateway truncates at 2K
  characters, banner notifies user.
- **User asks in pure Tagalog** — composer responds in
  English-primary with Tagalog ornaments (voice card §"Code-switching
  to Tagalog" does not authorise pure-Tagalog composition).
- **User asks about future events** — out-of-corpus policy applies.
- **Mobile-only user with intermittent connectivity** — chat history
  resumes from local storage; in-flight turn shows "reconnecting".

## 9. Acceptance

- End-to-end smoke from a mobile browser at 4G:
  [GUIDE-end-user.md](../guides/GUIDE-end-user.md) §"First-time visit"
  walkthrough completes without error.
- 6 build-kit sanity questions yield substantive responses with
  source panel populated.
- Identity probe questions trigger the honesty rule UI banner +
  response.
- Lighthouse accessibility ≥80 with a documented manual
  accessibility pass (Streamlit ceiling per
  [ADR-0017](../decisions/0017-end-user-ui-also-streamlit.md)).

## 10. Out-of-scope discoveries to surface

- User accounts / saved history — separate plan when needed.
- Multi-tenant FLP staff access — separate plan.
- Analytics on response quality (thumbs up/down) — separate plan.
