# ADR-0016: Theme-anchored register selection — five themes drive default register & wit calibration

* Status: accepted
* Date: 2026-05-26
* Deciders: Janet

## Context and Problem Statement

The Sonnet composition step (Phase 4,
[PLAN-0001](../implementation-plans/PLAN-0001-runtime-app-haiku-router-sonnet-composer.md))
must compose responses *in CJP's voice*, but CJP doesn't speak the
same way on every topic. He is:

- *Ceremonial and doctrinal* when discussing constitutional law and
  rule of law (Theme A).
- *Case-analytical with measured openers* on economics and prosperity
  doctrine (Theme B).
- *Warm, testimonial, gently self-deprecating* on family and personal
  matters (Theme C).
- *Ceremonial with humour, head-table style* at FLP events (Theme D).
- *Reflective and pedagogical* in contemporary commentary (Theme E).

We need a register-selection mechanism that:
1. Lets the composer pick a register tailored to the question.
2. Is auditable — a reviewer can ask *"what register fired here?"* and
   get a deterministic answer.
3. Doesn't require a separate register-classifier model on every turn.

## Decision Drivers

* **Determinism**: register selection should be a lookup, not an
  inference. The composer can attend to the picked register without
  re-deciding.
* **Coverage**: every topic in the taxonomy must have a register,
  including the META topic for robot-identity questions.
* **Override surface**: when a topic genuinely cuts across theme
  defaults (e.g., `robot_identity_meta`), it carries its own register
  override.
* **Wit calibration**: register alone isn't enough — *how much wit* is
  topic-dependent. Wit on a death penalty column is sparing,
  diplomatic; wit at an FLP awards dinner is head-table-style.

## Considered Options

1. **Five theme-anchored defaults + per-topic override (chosen)** —
   each Theme letter maps to `(default_register, wit_calibration)`;
   each taxonomy entry carries an optional
   `default_register_override` tuple.
2. **Per-topic register, no theme defaults** — every one of the 35
   topics declares its own register.
3. **Register classifier on the question** — a Haiku call that picks
   a register tag from the user input alone.
4. **Hand-picked at runtime by the composer** — let Sonnet decide
   inside the prompt.

## Decision Outcome

Chosen option: **Five theme-anchored defaults + per-topic override**.

The mapping is defined once in `scripts/build_topic_map.py`:

```python
THEME_REGISTER = {
    "A": ("ceremonial_doctrinal", "sparing, diplomatic"),
    "B": ("case_analytical_with_openers", "professional warmth"),
    "C": ("testimonial", "gentle, self-deprecating"),
    "D": ("ceremonial_with_humor", "freely, head-table style"),
    "E": ("reflective_pedagogical", "thoughtful, warm"),
}
```

Each taxonomy entry inherits its theme anchor's register unless it
declares its own `default_register_override`. Currently only
`robot_identity_meta` overrides:

```python
"default_register_override": ("transparent_curatorial", "gentle, self-aware"),
```

The result is stamped into every topic node in
`corpus/voice/topic_map.json` as `default_register` and
`wit_calibration`. The Voice Card
([corpus/voice/voice_card.md](../../corpus/voice/voice_card.md))
documents the table for the composer.

### Consequences

* Good: register selection is a `O(1)` lookup on the routed topic.
  No extra model call per turn.
* Good: the rule is auditable. *"This response was composed in
  `case_analytical_with_openers` because the primary topic was
  `economic_governance_and_business_law`, which inherits the Theme B
  default."* — that sentence is the audit trail.
* Good: the META override pattern handles the robot-identity case
  cleanly without breaking the theme defaults for everything else.
* Bad: a question whose primary topic is split across themes (e.g.,
  `family_and_marriage` + `flp_donors_and_partners`) gets the register
  of the *first* primary topic. Compositional ambiguity remains —
  documented in
  [TS-004](../test-specs/TS-004-voice-card-protocol.md) §4 as a
  known eval scenario.
* Bad: any new theme (rare) requires adding a row to `THEME_REGISTER`.
  Caught by the schema-validation step in build (every taxonomy entry
  must reference a known theme anchor).
* Neutral: register names are semantic tags (`ceremonial_doctrinal`),
  not natural-language sentences. The Voice Card's worked examples and
  the §"Register selection table" connect tag → behaviour for the
  composer.

## Pros and Cons of the Options

### Theme-anchored defaults + per-topic override (chosen)

* Good, because lookup is `O(1)` and auditable.
* Good, because most topics inherit cleanly; only true cross-cutting
  topics need overrides.
* Good, because the override pattern scales (more META topics or
  cross-theme topics in future can declare overrides without
  affecting others).
* Bad, because cross-theme primary topics arbitrate by first-primary
  rule.

### Per-topic register, no theme defaults

* Good, because each topic can fine-tune its own register.
* Bad, because 35 topics × 2 fields = 70 register decisions to author.
* Bad, because thematic coherence is lost — small drift across same-theme
  topics is invisible.

### Register classifier on the question

* Good, because user-input-aware.
* Bad, because adds a second pre-composition Haiku call (latency +
  cost).
* Bad, because non-deterministic — same question yields different
  registers on different turns.

### Hand-picked by composer

* Good, because most flexible.
* Bad, because un-auditable — register choice lives inside model
  reasoning, not in artefacts.
* Bad, because shifts cost from build-time curation to per-turn
  reasoning.

## More Information

- Mapping: `scripts/build_topic_map.py` `THEME_REGISTER` constant.
- Voice Card consumer:
  [`corpus/voice/voice_card.md`](../../corpus/voice/voice_card.md)
  §"Register selection — driven by topic_paths".
- Theme labels and descriptions: [PROJECT.md](../../PROJECT.md) §3
  and §9.
- Test spec: [TS-004](../test-specs/TS-004-voice-card-protocol.md)
  §"Register selection accuracy".
- Related runtime decision:
  [ADR-0004](0004-pattern-1-topic-routed-two-stage-api.md).
