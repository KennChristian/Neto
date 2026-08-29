# Decision Guide: Frontmatter as Single Source of Stateful Metadata

## The Decision

For an artifact whose state changes over time (a plan with lifecycle stages, an ADR with accepted/deprecated status, a document with revision metadata), where should the authoritative state live?

## When This Applies

Any artifact with mutable metadata: plans, ADRs, tickets, specs, lessons — anything that has a lifecycle or status field that multiple people/processes read.

## Options

### Option 1 — External Tracker

- Examples: a spreadsheet, a database, an `00-index.md` file, a ticket system
- **Pros:** Easy to query across many artifacts at once; human-readable summary view; existing tools (spreadsheets, trackers) already exist.
- **Cons:** The artifact file and the tracker are two writers for the same fact; reconciliation becomes a discipline problem; renames, moves, and deletes easily break the link; at scale, the tracker always disagrees with the artifact on something.

### Option 2 — Artifact Frontmatter

- The state lives in a YAML (or similar) frontmatter block inside the artifact file itself
- **Pros:** Single writer — the artifact file; automatic co-location (the state is never more than a few lines away from the content it describes); renames, moves, deletes don't orphan anything; all other state surfaces (indexes, summaries, dashboards) become derived views.
- **Cons:** Queries across many artifacts require a scanner or generator (must load every file to answer "which plans are completed?"); requires a frontmatter schema and validator.

## Recommendation

**Frontmatter is the single writer; external trackers are generated views.**

- The artifact owns its state. No other file may write to the same fact. This is the single-writer invariant.
- External trackers (MANIFEST files, status overviews, per-axis views) must be generated from the frontmatter, not authored alongside it.
- The generator runs as part of the commit that updates the frontmatter, so all views land atomically with the state change.
- Pre-commit hooks reject hand-edits to generated views and reject commits where frontmatter changed but views weren't regenerated.

## Design Checklist

1. **Dual-block frontmatter** — Separate the **state block** (fields managed by orchestration: id, kind, status, dates) from the **signature block** (fields managed by the author: axis values, related references). Distinct blocks, distinct writers, distinct update cadences.
2. **Schema validator** — Required fields, enum memberships, reference resolution.
3. **Generator for each derived view** — Status dashboard, per-axis views, MANIFEST files; all carry a hash header.
4. **Pre-commit atomicity** — Any commit that changes frontmatter must also refresh the derived views.

## Origin

`rev1_2` (ADR-142). Before this decision, plan status lived in `docs/implementation-plans/00-index.md` while MANIFEST files carried their own Status column. Drift was structural. The fix was to make per-plan frontmatter the single writer and regenerate 00-index.md and MANIFEST as derived views.

## Related

- `decision-guides/generated-index-vs-hand-authored.md` — how to build the derived view layer
- `anti-patterns/manifest-schema-drift.md` — the failure mode this decision prevents
- `test-patterns/frontmatter-schema-validator.md` — validation pattern
