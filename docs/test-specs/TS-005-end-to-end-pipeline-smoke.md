# TS-005: End-to-end pipeline smoke — CSV → corpus → topic_map → router → composer → response

* Status: draft
* Verifies: Phases 1-3 collectively (i.e., that the artifacts shipped
  by `cbf155b`, `795f59a`, and `2527161` compose correctly when wired
  into a runtime via
  [PLAN-0001](../implementation-plans/PLAN-0001-runtime-app-haiku-router-sonnet-composer.md))
* Subject: the complete pipeline once PLAN-0001 lands
* Style: integration / smoke — fewer, larger scenarios that exercise
  many steps end-to-end

## 1. Scope

This spec exercises the full Phase 1-4 pipeline. It assumes:

- Phase 1: `corpus/{columns,speeches}/**/*` exist (79 .md + 79 .json).
- Phase 2: `corpus/voice/topic_map.json` exists; `topic_paths`
  backfilled.
- Phase 3: `corpus/voice/voice_card.md` exists.
- PLAN-0001: runtime is wired to consume these.

The cheaper unit-level invariants (frontmatter parses, JSON
validates, matcher word-boundaries fire correctly) are covered by
TS-001/TS-002/TS-003. This spec checks that the *composition* of
those holds at runtime.

## 2. Smoke — the six build-kit sanity questions

For each question, the smoke test verifies that:

1. The Haiku router returns ≥1 primary topic id present in
   `topic_map.json`.
2. The intersection of router primary topics with each doc's
   `topic_paths` produces ≥1 source doc id.
3. The composer's response is ≥40 words and ≤400 words.
4. Per-turn cost ≤ $0.05.
5. Warm-turn latency ≤ 25s (target ≤ 15s).
6. Operator dashboard shows the Sources panel populated with the
   routed doc ids.

The six questions are listed in TS-004 §2. This spec doesn't grade
the *quality* of responses (TS-004 does); it grades only that the
pipeline *produces* a structurally valid response.

## 3. State-machine model

```
Input → InputGate → Router → ContextBuilder → Composer → FidelityCheck → Output
```

Each transition has its own observability point:

| Transition | Observable | Threshold |
|---|---|---|
| Input → Input-Gate | scope decision; identity flag | <500ms |
| Gate → Router | gate output | <500ms |
| Router → ContextBuilder | router JSON (primary, secondary, confidence, reasoning) | <2000ms |
| ContextBuilder → Composer | assembled context (≤12K tokens) | <300ms |
| Composer → FidelityCheck | Sonnet draft | <15000ms |
| FidelityCheck → Output | flags (hallucination, voice_drift, guardrail) | <2000ms |
| Output | final response | total ≤25s |

## 4. Integration scenarios

### 4.1 Happy path — well-covered topic

**Given** the question *"What is the twin-beacons doctrine?"*,
**When** the pipeline runs end-to-end,
**Then**:
- Router primary includes `twin_beacons_doctrine` (anchor).
- Source docs include at least one of `CA001`, `SA136`, `SD002`.
- Response includes the doctrine and at least one chiasmic doublet.
- Fidelity check passes without flagging.

### 4.2 Routing to META

**Given** *"Are you AI?"*,
**When** pipeline runs,
**Then**:
- Input Gate flags `identity_probe`.
- Router primary forced to `robot_identity_meta`.
- Source docs panel is *empty* (META has 0 corpus docs by design).
- Response uses the canonical *"robot rendering of my own voice"*
  phrasing.

### 4.3 OOC question

**Given** *"Who is the current US Speaker of the House?"*,
**When** pipeline runs,
**Then**:
- Router primary either falls back to wide route or
  flags low confidence.
- Composer adopts OOC reasoning policy:
  *"I have not written specifically on this; let me speak to the
  principle…"*
- Response stays under 200 words.

### 4.4 Multi-topic question

**Given** *"What's the connection between FLP and the rule of
law?"*,
**When** pipeline runs,
**Then**:
- Router primary includes both
  `foundation_for_liberty_and_prosperity` and `rule_of_law`.
- Source docs span both topics' `doc_ids` intersections.
- Composer register defaults to first primary
  ([ADR-0016](../decisions/0016-theme-anchored-register-selection.md)).

### 4.5 Cross-theme question

**Given** *"How does CJP's faith inform his work as Chief
Justice?"*,
**When** pipeline runs,
**Then**:
- Router primary spans theme C (`faith_journey`) and theme A
  (`supreme_court_history` or similar).
- Composer adopts `testimonial` register (Theme C lead).
- Response weaves the two themes coherently.

## 5. Cache observability

After 2 turns within a session, the third turn's input includes the
cached voice-card prefix:

- **Cache hit:** Anthropic API response metadata shows
  `cache_read_input_tokens > 0`.
- **Effective per-turn savings:** ~18% per
  [LL-001](../lessons/LL-001-cache-savings-18-not-55.md).

## 6. Per-doc routing spot checks (specific to Phase 2 backfill)

For 6 docs across themes — `SA136`, `CA001`, `CA004`, `CC001`,
`SD002`, `SE001` — manually craft a question that *should* route to
that doc's `topic_paths.primary[0]`, run it through the router, and
confirm that doc appears in the assembled context.

Pass: ≥5 of 6 route as expected. The one that misses is investigated
per
[PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md).

## 7. Idempotency

Two consecutive invocations of the pipeline with the same input
(no memory):
- Router output: not strictly equal (LLM sampling), but topic ids
  should overlap ≥80%.
- Composer response: not strictly equal; should preserve the same
  doctrinal anchors and register.

Run with `temperature=0`:
- Router output: bit-identical.
- Composer response: text-identical.

## 8. Failure modes

| Failure mode | Detection | Smoke verifies |
|---|---|---|
| API rate-limit hit mid-pipeline | 429 surfaces from Anthropic | Pipeline retries with backoff; eventual success |
| Voice card file missing | Pre-flight check at startup | Process exits with clear error before serving |
| Topic map file missing | Pre-flight check | Process exits with clear error |
| Corpus is empty | Pre-flight check | Process exits |
| Single .json malformed | Per-doc load try/except | Skip that doc; warn |

## 9. Acceptance for full Phase 4 readiness

- All six build-kit questions yield structurally valid responses.
- ≥5 of 6 per-doc routing spot checks pass.
- Per-turn cost over 30-turn sample ≤ $0.05 mean.
- p95 warm latency ≤25s.
- Identity-probe scenarios route to META.
- OOC scenarios stay grounded (no fabricated facts).

## 10. Out-of-scope

- LLM-graded response quality (TS-004).
- Voice / TTS smoke (PLAN-0006 acceptance).
- Web UI smoke (PLAN-0002 acceptance).
