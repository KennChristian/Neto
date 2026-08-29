# Anti-Pattern: Manifest Schema Drift

## The Pattern

A project adopts a harness template (e.g., `manifest-md.md` with `File | Purpose` columns) and extends it with project-specific columns (e.g., adding `Status`). No process is established to maintain the added column. Over time the column diverges from the true state tracked elsewhere (a per-artifact status field, a 00-index file, or a separate tracker).

## Symptoms

- MANIFEST column shows stale values that contradict the artifact's current state
- Reviewers cross-check two files to trust either
- Bug reports cite "the MANIFEST says X but the actual state is Y"
- Multiple fixes to individual rows don't converge — drift returns after each generation
- New authors don't know which file is authoritative

## Root Cause

Template subclassing without a maintenance contract. Adding a column creates a write obligation that nobody explicitly adopts. Without a single-writer guarantee, every process that touches the fact is a potential source of drift, and reconciliation is impossible because there is no authoritative source.

## Prevention Rules

1. **Never add columns to a harness template without also declaring a writer contract** — who writes this column, when, and via what mechanism.
2. **Prefer generated views over extended templates** — if the new fact can be derived from elsewhere (per-artifact frontmatter, a source-of-truth file), make the MANIFEST a generated view with a hash header, not a hand-authored file with extra columns.
3. **Validator enforces schema match** — a harness-aware validator rejects MANIFEST files whose column schema diverges from the template.
4. **Single writer per fact** — every stateful metadata fact has exactly one authoritative writer; all other surfaces showing the fact are derived.

## Detection

- Grep for MANIFEST column headers that don't match the harness template exactly
- Compare MANIFEST column contents against any other file claiming to track the same fact; divergence = drift
- Automated check in CI: `diff <(extract-manifest-columns) <(harness-template-columns)` must be empty

## Origin

Extracted from `rev1_2` (LL-064, ADR-143). Observed after ~200 plans accumulated with divergent `Status` across MANIFEST and `00-index.md`, and the `Status` column had no writer contract at all.

## Related

- `decision-guides/generated-index-vs-hand-authored.md` — when to prefer generation
- `decision-guides/frontmatter-as-single-source.md` — where the authoritative fact lives
- `anti-patterns/hand-edited-generated-artifact.md` — the sibling failure mode
