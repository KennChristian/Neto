# Migration Guide — Claude Harness Modular Restructuring

## What Changed

Claude-harness has been restructured from a flat file layout into a modular architecture with three tiers:

- **`core/`** — Always-active orchestration backbone
- **`modules/`** — Optional capability packages (data-contracts, verification)
- **`patterns/`** — Cross-cutting reusable knowledge library
- **`docs/`** — Self-documenting harness governance (ADRs, plans, lessons, guides)

## Path Mapping

| Old Path | New Path | Backward Compat |
|----------|----------|-----------------|
| `orchestration-prompt.md` | `core/orchestration-prompt.md` | Symlink at old path |
| `bootstrap-prompt.md` | `core/bootstrap-prompt.md` | Symlink at old path |
| `verifier-creator.md` | `modules/verification/prompt.md` | Symlink at old path |
| `data-contracts-prompt.md` | `modules/data-contracts/prompt.md` | Symlink at old path |
| `templates/root-claude-md.md` | `core/templates/root-claude-md.md` | Original kept |
| `templates/subdirectory-claude-md.md` | `core/templates/subdirectory-claude-md.md` | Original kept |
| `templates/manifest-md.md` | `core/templates/manifest-md.md` | Original kept |
| `templates/plan-index.md` | `core/templates/plan-index.md` | Original kept |
| `templates/plan-document.md` | `core/templates/plan-document.md` | Original kept |
| `templates/adr-template.md` | `core/templates/adr-template.md` | Original kept |
| `templates/project-orchestration-overlay.md` | `core/templates/project-orchestration-overlay.md` | Original kept |
| `templates/verification-audit-agent.md` | `modules/verification/templates/verification-audit-agent.md` | Original kept |
| `templates/verification-audit-agent-description.md` | `modules/verification/templates/verification-audit-agent-description.md` | Original kept |
| `templates/datacontracts-claude-md.md` | `modules/data-contracts/templates/datacontracts-claude-md.md` | Original kept |
| `templates/odcs-contract-*.yaml` | `modules/data-contracts/templates/odcs-contract-*.yaml` | Originals kept |
| `templates/odcs-quality-rules-catalog.md` | `modules/data-contracts/templates/odcs-quality-rules-catalog.md` | Original kept |
| `scripts/check-manifest.sh` | `core/scripts/check-manifest.sh` | Original kept |
| `scripts/validate-manifests.sh` | `core/scripts/validate-manifests.sh` | Original kept |
| `scripts/check-contract-drift.sh` | `modules/data-contracts/scripts/check-contract-drift.sh` | Original kept |
| `hooks/settings.json.example` | `core/hooks/settings.json.example` | Original kept |
| `hooks/settings-with-contracts.json.example` | _(deprecated — use module hook fragments)_ | Original kept |

## Migration Steps

### For Existing Consumers (No Action Required)

Root-level symlinks ensure all existing references continue to work:
- `claude-harness/orchestration-prompt.md` → resolves via symlink
- `claude-harness/bootstrap-prompt.md` → resolves via symlink
- `claude-harness/templates/*` → originals still present

**No changes are needed in downstream projects.** The symlinks provide transparent backward compatibility.

### For New Projects

New projects should reference the canonical paths:
- `claude-harness/core/orchestration-prompt.md`
- `claude-harness/core/bootstrap-prompt.md`
- `claude-harness/registry.yaml` (new — module routing entry point)

### Updating References (Optional)

To use canonical paths in an existing project, update your CLAUDE.md Deep Docs section:

```markdown
### Deep Docs
- **Orchestration:** `claude-harness/core/orchestration-prompt.md` (on-demand)
- **Patterns:** `claude-harness/patterns/README.md` — Anti-patterns, decision guides (on-demand)
```

## Platform Notes

### Windows

Git symlinks require either:
- Developer Mode enabled, or
- `git config core.symlinks true` before cloning

If symlinks don't work on Windows, you can copy the target files to the symlink locations instead.

### CI / Shallow Clones

Submodule must be initialized for symlinks to resolve:
```bash
git submodule update --init --recursive
```

## Timeline

- **Current**: Symlinks maintain backward compatibility. Original files in `templates/`, `scripts/`, `hooks/` are kept.
- **Future**: Original files in `templates/`, `scripts/`, `hooks/` may be removed once all known consumers have migrated to canonical paths.
