# Decision Guide: Generated Index vs. Hand-Authored

## The Decision

When you need an index file that summarizes, cross-references, or catalogs other artifacts (a MANIFEST, a table of contents, a dependency graph, a status overview), should you hand-author it or generate it from the underlying artifacts?

## When This Applies

Any of these structures:
- MANIFEST files listing a directory's contents with per-file descriptions
- Status overviews tracking which plans/tickets are in which state
- Cross-reference indexes (X cites Y, Y is implemented by Z)
- Navigation summaries (per-axis view files, topic indexes)
- Dependency graphs visualized as tables or adjacency lists

## Options

### Option 1 — Hand-Authored

- **Pros:** Simple to bootstrap; no generator needed; allows nuanced phrasing; works at small scale.
- **Cons:** Drifts from the underlying artifacts as they change; reviewers must remember to update the index whenever they touch a referenced file; the same fact lives in multiple places with no reconciliation; at scale, drift becomes structural rather than a discipline failure.

### Option 2 — Generated

- **Pros:** Drift-proof by construction — regenerate after any change to the source artifacts; the fact has a single writer (the underlying artifact), and the index is a view; hash header verifies freshness; reviewers never edit the index directly.
- **Cons:** Requires writing a generator (one-time investment); requires a pre-commit hook to catch hand-edits (otherwise the discipline slips); slightly harder to debug when the generator itself has a bug.

## Recommendation

**Generate when the same fact appears in more than one source.** If the index's content is a pure summary of what is already in the underlying artifacts (titles, descriptions, dependencies, statuses, axis values), the index is a view and must be generated. Hand-editing it creates the opportunity for drift that `anti-patterns/manifest-schema-drift.md` catalogs.

**Hand-author only when the index is genuinely single-source** — when it contains information that exists nowhere else (e.g., a top-level README explaining the project's purpose, a getting-started guide). If you find yourself copy-pasting titles or descriptions from artifact files into the index, stop — the index should be generated.

## Design Checklist for Generated Indexes

1. **Hash header at the top** — generator name, source hash, timestamp. Makes generated files visually distinctive.
2. **Deterministic output** — same inputs produce byte-identical output (modulo the timestamp in the header). Sort rows lexicographically; don't rely on filesystem order.
3. **Pre-commit hand-edit detection** — a hook that recomputes the source hash and rejects the commit if it doesn't match.
4. **Single-writer contract** — document which script writes the index; refuse all other writers.
5. **Fail fast on missing inputs** — if an underlying artifact is missing a required field (e.g., no description), the generator errors out with a clear message rather than producing a partial index.

## Origin

`rev1_2` (ADR-143, LL-064). MANIFEST files with a hand-maintained `Status` column drifted from the true plan status tracked in `00-index.md`; the fix was to generate both files from per-plan frontmatter with hash headers.

## Related

- `anti-patterns/manifest-schema-drift.md` — drift failure mode
- `anti-patterns/hand-edited-generated-artifact.md` — sibling failure mode
- `decision-guides/frontmatter-as-single-source.md` — where the authoritative fact lives
- `test-patterns/generated-artifact-freshness.md` — freshness verification pattern
