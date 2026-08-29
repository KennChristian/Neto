# Plan-001: Core Module Extraction

## Objective

Create `core/` directory containing the always-active orchestration backbone.

## Dependencies

- ADR-001 (Modular Architecture)

## Scope

1. Create `core/module.yaml` (id: core, always_active: true, no relevance scoring)
2. Copy to `core/`: `orchestration-prompt.md`, `bootstrap-prompt.md`
3. Copy to `core/templates/`: 7 documentation templates (root-claude-md, subdirectory-claude-md, manifest-md, plan-index, plan-document, adr-template, project-orchestration-overlay)
4. Copy to `core/scripts/`: `check-manifest.sh`, `validate-manifests.sh`
5. Copy to `core/hooks/`: `settings.json.example`
6. Update template path references in copied files (`templates/` → `core/templates/`)

## Key Decisions

Files are **copied** (originals kept at root level for backward compatibility, addressed in Plan-006).

## Verification Criteria

- [ ] `core/module.yaml` parses as valid YAML with required fields (id, name, version, description, templates, scripts)
- [ ] All 12+ files exist in `core/` subdirectories
- [ ] Root-level originals still exist (not moved)
- [ ] No broken `../templates/` relative references in copied files
- [ ] `find core/ -type f | wc -l` returns ≥12

## Failure Modes

- Relative path references inside `bootstrap-prompt.md` break → update to `core/templates/` in the copy
- `check-manifest.sh` assumes it runs from project root → verify script uses `$0` dirname or explicit paths
