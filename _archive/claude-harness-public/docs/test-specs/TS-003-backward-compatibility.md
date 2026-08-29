# TS-003: Backward Compatibility

## Model

Verify that the modular restructuring does not break existing consumers who reference root-level file paths.

## Test Cases

| ID | Case | Invariant |
|----|------|-----------|
| T1 | Symlink resolution | `cat claude-harness/orchestration-prompt.md` produces identical content to `cat claude-harness/core/orchestration-prompt.md` |
| T2 | Git tracking | `git ls-files claude-harness/` includes symlink entries (not just targets) |
| T3 | Downstream refs | Paths referenced in downstream project CLAUDE.md (e.g., `claude-harness/orchestration-prompt.md`) resolve to actual files |
| T4 | Template paths | Internal `../templates/` references in pre-existing downstream project files still work from their original locations |
| T5 | Hook scripts | `check-manifest.sh` and `validate-manifests.sh` work when invoked from the downstream project root |
| T6 | Registry fallback | When `registry.yaml` is missing or invalid, bootstrap falls back to legacy behavior (Phases 1-8.5) |

## Verification Method

### T1: Symlink Resolution
```bash
diff <(cat claude-harness/orchestration-prompt.md) <(cat claude-harness/core/orchestration-prompt.md)
# Expected: no output (identical)
```

### T2: Git Tracking
```bash
git ls-files claude-harness/ | grep -E "^claude-harness/(orchestration-prompt|bootstrap-prompt|verifier-creator|data-contracts-prompt)\.md$"
# Expected: 4 lines (symlinks tracked)
```

### T3: Downstream Refs
```bash
# For each path in downstream CLAUDE.md Deep Docs section:
test -f "claude-harness/orchestration-prompt.md" && echo "OK" || echo "FAIL"
```

### T4: Template Paths
Verify that no downstream project file references `claude-harness/templates/` directly (they should use the canonical path or the symlink resolves it).

### T5: Hook Scripts
```bash
# From project root:
echo '{"tool_input":{"file_path":"test.py"},"cwd":"'$(pwd)'"}' | bash claude-harness/scripts/check-manifest.sh
# Expected: exits 0 (no manifest to check)
```

### T6: Registry Fallback
```bash
# Temporarily rename registry.yaml
mv claude-harness/registry.yaml claude-harness/registry.yaml.bak
# Run bootstrap — should proceed with legacy phases
# Restore
mv claude-harness/registry.yaml.bak claude-harness/registry.yaml
```

## Platform Notes

- **Windows**: Symlinks may require developer mode or elevated permissions. `MIGRATION.md` documents the copy alternative.
- **CI shallow clones**: Symlinks may not resolve if submodule is not checked out. Document `git submodule update --init` requirement.
