# ADR-0005: Defer robot embodiment for the May 30 demo

* Status: accepted
* Date: 2026-05-14
* Deciders: Doc, Janet

## Context and Problem Statement

The broader project arc includes a Reachy Mini embodiment — the local
HuggingFace cache holds `pollen-robotics/reachy-mini-dances-library`
and `reachy-mini-emotions-library`, confirming an embodiment track
exists. The question for the May 30, 2026 demo: do we ship the
conversation app standalone or attempt robot integration in time?

## Decision Drivers

* Demo date — May 30, 2026 is fixed.
* Risk surface — robot integration adds hardware, motion, embodied
  audio I/O, and synchronization concerns.
* Scope clarity — the build-kit README scopes May 30 as a
  *"desktop/laptop conversational interface"*, not a robot.
* Audience uncertainty — we don't yet know whether the demo audience
  expects a robot (see [handover 2026-05-16](../handover_claude_code_2026-05-16.md) §11 Q1).

## Considered Options

* Ship the conversation app on a laptop for May 30; robot deferred
* Attempt robot integration in time for May 30
* Ship a "robot-ready" but headless app and decide closer to the date

## Decision Outcome

Chosen option: **ship the conversation app on a laptop for May 30;
robot embodiment deferred**, because the demo date is fixed, robot
integration is a separable track with its own hardware/timing risks,
and the conversation app reaches the demo bar on its own.

### Consequences

* Good: scope is clear and de-risked for May 30.
* Good: the conversation app's pipeline is fully exercised end-to-end
  before any embodiment work begins.
* Good: audio I/O abstractions (`record_until_silence`,
  `synthesize_speech`, `play_audio`) are isolated functions — when the
  robot adapter lands, those are the single points of change.
* Bad: a separate robot integration project remains on the backlog.
* Neutral: HuggingFace cache contains Reachy assets but they are not
  referenced by the app today.

## Pros and Cons of the Options

### Ship conversation app on a laptop; robot deferred

* Good, because de-risks the fixed May 30 date.
* Good, because team can iterate on voice/router/cost in isolation.
* Bad, because the demo doesn't show the full vision.

### Attempt robot integration in time

* Good, because the demo is more striking with embodiment.
* Bad, because adds hardware coordination and motion timing on a fixed deadline.
* Bad, because no robot-adapter code exists in the repo today; building
  it is a several-day arc minimum.

### Ship "robot-ready" headless app

* Good, because preserves optionality.
* Bad, because adds abstractions for a use case we may or may not
  exercise — premature investment.

## More Information

[handover 2026-05-16](../handover_claude_code_2026-05-16.md) §2:
*"the build-kit README explicitly puts robot embodiment out of scope
for May 30"*; §4 row "Robot adapter (Reachy Mini)": *"not started — out
of scope for May 30 per build-kit README"*; §11 Q7: *"Reachy Mini scope.
Does the conversation app feed into the robot at some later stage, or
are the tracks fully independent?"* — still open. Strategic handover
doc not on disk; date is per the instruction set that scoped this ADR.
