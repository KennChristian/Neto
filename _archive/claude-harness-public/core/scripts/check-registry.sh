#!/usr/bin/env bash
# PostToolUse hook: reminds Claude to update registry.yaml when a module
# is created or modified.
#
# Receives JSON on stdin from Claude Code with tool_input.file_path.
# Exits 2 + stderr message if a module's module.yaml is missing from registry.yaml,
# or if registry.yaml was edited without updating module files.
#
# Installation: Add to .claude/settings.json PostToolUse hook for Write|Edit.

set -euo pipefail

# Read JSON from stdin
INPUT=$(cat)

# Extract the file path from tool input
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Determine the harness root (directory containing registry.yaml)
# Walk up from the file to find it
HARNESS_ROOT=""
SEARCH_DIR=$(dirname "$FILE_PATH")
while [[ -n "$SEARCH_DIR" ]] && [[ "$SEARCH_DIR" != "/" ]]; do
  if [[ -f "$SEARCH_DIR/registry.yaml" ]]; then
    HARNESS_ROOT="$SEARCH_DIR"
    break
  fi
  SEARCH_DIR=$(dirname "$SEARCH_DIR")
done

# Not inside a harness — nothing to check
if [[ -z "$HARNESS_ROOT" ]]; then
  exit 0
fi

REGISTRY="$HARNESS_ROOT/registry.yaml"
REL_PATH="${FILE_PATH#"$HARNESS_ROOT"/}"

# ─── Case 1: A file inside modules/ was created or edited ─────────────
if [[ "$REL_PATH" == modules/* ]]; then
  # Extract the module directory name (modules/<name>/...)
  MODULE_DIR=$(echo "$REL_PATH" | cut -d'/' -f1-2)
  MODULE_YAML="$MODULE_DIR/module.yaml"

  # Check if the module.yaml exists
  if [[ ! -f "$HARNESS_ROOT/$MODULE_YAML" ]]; then
    # Editing a module that has no module.yaml yet — remind to create it
    if [[ "$REL_PATH" != *"module.yaml" ]]; then
      echo "Registry: \`$MODULE_DIR/module.yaml\` does not exist. Create it to register this module." >&2
      exit 2
    fi
  fi

  # Check if registry.yaml references this module
  if ! grep -qF "$MODULE_YAML" "$REGISTRY"; then
    echo "Registry update needed: \`$MODULE_YAML\` is not listed in \`registry.yaml\`. Please add it to the modules list." >&2
    exit 2
  fi
fi

# ─── Case 2: registry.yaml itself was edited ──────────────────────────
if [[ "$REL_PATH" == "registry.yaml" ]]; then
  # Validate all referenced module.yaml files exist
  MISSING=()
  while IFS= read -r module_ref; do
    module_ref=$(echo "$module_ref" | xargs)  # trim whitespace
    if [[ ! -f "$HARNESS_ROOT/$module_ref" ]]; then
      MISSING+=("$module_ref")
    fi
  done < <(grep -oP '(?<=- )modules/[^\s]+/module\.yaml' "$REGISTRY" 2>/dev/null)

  if [[ ${#MISSING[@]} -gt 0 ]]; then
    MSG="Registry references missing module files:"
    for m in "${MISSING[@]}"; do
      MSG="$MSG \`$m\`"
    done
    echo "$MSG" >&2
    exit 2
  fi

  # Check for unregistered modules
  UNREGISTERED=()
  while IFS= read -r module_yaml; do
    rel_module="${module_yaml#"$HARNESS_ROOT"/}"
    if ! grep -qF "$rel_module" "$REGISTRY"; then
      UNREGISTERED+=("$rel_module")
    fi
  done < <(find "$HARNESS_ROOT/modules" -name "module.yaml" -type f 2>/dev/null)

  if [[ ${#UNREGISTERED[@]} -gt 0 ]]; then
    MSG="Unregistered modules found:"
    for u in "${UNREGISTERED[@]}"; do
      MSG="$MSG \`$u\`"
    done
    echo "$MSG" >&2
    exit 2
  fi
fi

# ─── Case 3: A module.yaml was deleted (file no longer exists) ────────
if [[ "$REL_PATH" == modules/*/module.yaml ]] && [[ ! -f "$FILE_PATH" ]]; then
  if grep -qF "$REL_PATH" "$REGISTRY"; then
    echo "Registry cleanup needed: \`$REL_PATH\` was deleted but is still listed in \`registry.yaml\`. Please remove it." >&2
    exit 2
  fi
fi

exit 0
