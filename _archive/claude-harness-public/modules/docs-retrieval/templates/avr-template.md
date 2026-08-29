---
id: AVR-NNN
kind: axis-value-record
axis: <stage|depth|layer|concern|persona>
value: <kebab-case-value>
status: proposed
created: YYYY-MM-DD
supersedes:
superseded_by:
---

<!--
IMPORTANT: This is an AVR (Axis Value Record) for retrieval-vocabulary
governance. It is NOT a DDR. If your project uses DDRs for domain decisions,
keep them in their own directory (e.g., `docs/decisions/ddrs/`); AVRs live
under `docs/axes/records/`. The two artifact types are structurally
independent: separate directory, separate ledger, separate template,
separate `kind` field, separate MANIFEST.
-->

# AVR-NNN: `<axis>=<value>`

## Rationale

Why this is a new value on the `<axis>` axis, and not a variant of an
existing one. State the question this value answers and why no current
value on this axis already answers it.

## Example Artifacts

Cite at least 2 existing files that would carry this value in their
signature block. Prefer files drawn from different layers or lifecycle
stages to demonstrate the value is not a synonym for a single artifact.

- `docs/<path>/<file-a>.md` — why it carries this value
- `docs/<path>/<file-b>.md` — why it carries this value

## Alternatives Considered

Which close-by values on the SAME axis were rejected, and why. If the term
is canonical and has no close neighbors, state explicitly: "no alternatives
— canonical term."

- `<alternative-value>` — rejected because ...

## Orthogonality Check

How this value does NOT overlap with values on the other four axes. For
each of the other axes, state whether it is independent or whether there
is correlation to watch for.

- vs `stage`: ...
- vs `depth`: ...
- vs `layer`: ...
- vs `concern`: ...
- vs `persona`: ...

(Omit the row corresponding to the axis this AVR is on.)

## Origin

What brought this proposal forward — task, PR, lesson, refactor, harvest
from existing prose. Cite the originating artifact if any.
