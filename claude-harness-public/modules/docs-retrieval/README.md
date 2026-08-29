# docs-retrieval — Multi-Axis Markdown Retrieval Module

## Purpose

For projects whose `docs/` tree has grown past ~100 markdown artifacts, linear
MANIFEST scanning becomes expensive. This module installs:

- A closed axis vocabulary governed per-value via **Axis Value Records (AVRs)**
- Dual-block frontmatter on every authored artifact (state + axes + relational)
- Generated per-axis view files for cheap retrieval via intersection
- A frontmatter validator with rule categories R1..R6
- A hash-header hand-edit detector for generated files
- A 4-tier banded retrieval protocol (`docs/RETRIEVAL.md`) for future agents

## When to activate

| Signal | Weight |
|---|---|
| ≥100 markdown files under `docs/` | 4 |
| ≥300 markdown files | +2 (cumulative) |
| `docs/implementation-plans/` present | 2 |
| `docs/decisions/ADR-*.md` present | 2 |

Threshold: **score ≥6**. Below → skip activation; flat MANIFEST scanning is
still cheap enough at small scale.

## When NOT to activate

- Under 50 markdown artifacts (flat is fine)
- Single-author corpus with low churn
- Docs outside `docs/` (module assumes the conventional layout)

## Quick start (maintainer)

The harness bootstrap's EXECUTE phase runs the 9-step protocol in
[`prompt.md`](./prompt.md) automatically. Summary:

1. Create `docs/axes/records/AVR-TEMPLATE.md` (from harness template)
2. Seed baseline AVRs for `stage` + `depth` universal axes
3. Generate initial `docs/axes/registry.yaml`
4. Create `docs/_views/.gitkeep`
5. Copy module scripts into target project `scripts/`
6. Append retrieval-protocol section to project root `CLAUDE.md`
7. Create `docs/RETRIEVAL.md` from template
8. Register pre-commit hand-edit hook
9. STOP — no auto-backfill (human review non-negotiable per LL-068)

After install, run `scripts/propose_axis_seeds.py` for TF-IDF proposals on
unbackfilled artifacts; review each batch manually before applying.

## Post-install workflow

```
# Add a new axis value
$ vim docs/axes/records/AVR-NNN-<axis>-<value>.md
$ scripts/generate-axis-registry.sh
$ scripts/generate-axis-views.sh
$ git commit -m "Add new axis value NNN"
# Pre-commit hand-edit detector verifies views are fresh and untouched.

# Update a plan's status
$ vim docs/implementation-plans/NNN-<slug>.md  # edit frontmatter status:
$ scripts/generate-axis-views.sh                # refresh 00-index.md
$ git commit ...                                # atomic with frontmatter change
```

## Lessons (see `lessons/`)

- **Manifest schema drift** — extending harness templates without a writer contract (LL-064)
- **Closed-tag taxonomy collapse** — single-axis classification fails past ~100 artifacts (LL-065)
- **LSH as inspiration, not implementation** — borrowing principles across paradigms (LL-066)

## Pattern citations

Pattern-Ref: manifest-schema-drift, closed-tag-taxonomy, hand-edited-generated-artifact, multi-axis-vs-flat-taxonomy, generated-index-vs-hand-authored, frontmatter-as-single-source, frontmatter-schema-validator, generated-artifact-freshness, axis-coverage

(All 9 patterns live in `claude-harness/patterns/{anti-patterns,decision-guides,test-patterns}/`.)

## Origin

Extracted from the `rev1_2` form-grammar-scoring project after Plans 231–238
operationalized the architecture. See the project-side ADRs 141–146 and
Plans 231–241 for the originating design and execution history.
