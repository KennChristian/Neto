# Docs Retrieval Module — Bootstrap EXECUTE Protocol

This module installs multi-axis frontmatter retrieval infrastructure into a
target project. It is activated by the harness bootstrap when the project's
markdown corpus crosses ~100 artifacts and retrieval cost becomes a concern.

## When to activate

| Condition | Weight |
|---|---|
| ≥100 markdown files under `docs/` | 4 |
| ≥300 markdown files under `docs/` | +2 (cumulative) |
| `docs/implementation-plans/` with `00-index.md` | 2 |
| `docs/decisions/ADR-*.md` present | 2 |
| `docs/test-specs/`, `docs/lessons/` populated | 1–2 |

Activation threshold: score ≥6. Below threshold → skip EXECUTE entirely.

## When NOT to activate

- <50 markdown artifacts (flat taxonomy is fine)
- Single-author, low-churn doc corpus
- Projects whose docs live outside `docs/` (module assumes the conventional layout)

## EXECUTE protocol (9 steps)

When activation passes, Claude runs these steps against the target project:

1. **Create `docs/axes/records/AVR-TEMPLATE.md`** from the harness-shipped
   `templates/avr-template.md`. This is the authoring template for new Axis
   Value Records.

2. **Seed baseline AVRs** for the universal axes `stage` and `depth` under
   `docs/axes/records/`:
   - `stage`: draft, active, completed, deferred, archived (5 AVRs)
   - `depth`: D0, D1, D2, D3 (4 AVRs)

   Do NOT seed project-specific axes (`layer`, `concern`, `persona`) — those
   depend on the project's domain vocabulary. Prompt the user to author them
   post-install, citing existing prose.

3. **Generate the initial `docs/axes/registry.yaml`** by running
   `scripts/generate-axis-registry.sh`. This produces a registry with just
   the baseline stage+depth values.

4. **Create `docs/_views/.gitkeep`** so the generated-views directory exists
   for the first `generate_axis_views.py` run.

5. **Copy the module's scripts into the target project's `scripts/`**
   directory:
   - `generate_axis_registry.py`, `generate_axis_views.py`
   - `validate_frontmatter.py`, `propose_axis_seeds.py`
   - `detect_hand_edits.sh`
   - `generate-axis-registry.sh`, `generate-axis-views.sh`

   Ensure the `grammar` or equivalent project conda env has `pyyaml`
   installed; update the target project's `requirements.txt` accordingly.

6. **Append the retrieval-protocol pointer section** to the project's root
   `CLAUDE.md` from `templates/retrieval-protocol-claude-md.md`. The pointer
   directs future-Claude sessions to read `docs/RETRIEVAL.md` before
   grep-scanning.

7. **Create `docs/RETRIEVAL.md`** from the harness template. This is the
   4-tier banded query procedure. It is an authored file, not generated —
   humans may edit it as the project's retrieval conventions evolve.

8. **Register the pre-commit hand-edit hook** by adding an entry to the
   project's `.claude/settings.json` PreCommit hooks that invokes
   `bash scripts/detect_hand_edits.sh --staged-only`.

9. **STOP. Do NOT auto-backfill frontmatter across the corpus.** Backfill
   is a human-review operation (LL-068 — bootstrap must not auto-apply).
   Emit a post-install note:
   > "Run `scripts/propose_axis_seeds.py` to generate TF-IDF axis
   > proposals for unbackfilled artifacts. Review each batch manually before
   > applying frontmatter. See the module's README for the review workflow."

## Post-install

- The pre-commit hook catches hand-edits to `_views/`, MANIFESTs,
  `00-index.md`, and `registry.yaml`.
- Run `scripts/generate-axis-views.sh` after any frontmatter change to
  refresh the views atomically.
- Future axis additions require new AVRs under `docs/axes/records/`; never
  hand-edit `registry.yaml`.

## References

- ADR-141 (multi-axis frontmatter retrieval architecture)
- ADR-142 (dual-block frontmatter — state vs signature separation)
- ADR-143 (generated views over hand-authored indexes)
- ADR-144 (AVR-driven axis vocabulary governance)
- ADR-145 (Python permitted in harness scripts)
- ADR-146 (docs-retrieval as a harness module)
- LL-068 (bootstrap must not auto-apply)
