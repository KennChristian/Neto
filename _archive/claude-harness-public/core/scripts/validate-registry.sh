#!/usr/bin/env bash
# Validate registry.yaml against actual module directories.
# Checks for: missing module.yaml files, unregistered modules,
# and module.yaml structural requirements.
# Usage: bash scripts/validate-registry.sh
#
# Suitable for CI pipelines or manual checks.

set -euo pipefail

# Find the harness root (directory containing registry.yaml)
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
HARNESS_ROOT=""
SEARCH_DIR="$SCRIPT_DIR"
while [[ -n "$SEARCH_DIR" ]] && [[ "$SEARCH_DIR" != "/" ]]; do
  if [[ -f "$SEARCH_DIR/registry.yaml" ]]; then
    HARNESS_ROOT="$SEARCH_DIR"
    break
  fi
  SEARCH_DIR=$(dirname "$SEARCH_DIR")
done

if [[ -z "$HARNESS_ROOT" ]]; then
  echo "ERROR: registry.yaml not found in any ancestor directory"
  exit 1
fi

REGISTRY="$HARNESS_ROOT/registry.yaml"
ERRORS=0
WARNINGS=0

echo "Validating registry.yaml..."
echo "================================"

# ─── Check 1: All registry entries point to existing files ────────────
echo ""
echo "Check 1: Registry references → existing files"
while IFS= read -r module_ref; do
  module_ref=$(echo "$module_ref" | xargs)
  if [[ -f "$HARNESS_ROOT/$module_ref" ]]; then
    echo "  OK:   $module_ref"
  else
    echo "  FAIL: $module_ref (file not found)"
    ERRORS=$((ERRORS + 1))
  fi
done < <(grep -oP '(?<=- )modules/[^\s]+/module\.yaml' "$REGISTRY" 2>/dev/null)

# ─── Check 2: All module.yaml files are registered ───────────────────
echo ""
echo "Check 2: Existing modules → registered in registry"
while IFS= read -r module_yaml; do
  rel_module="${module_yaml#"$HARNESS_ROOT"/}"
  if grep -qF "$rel_module" "$REGISTRY"; then
    echo "  OK:   $rel_module"
  else
    echo "  FAIL: $rel_module (not in registry.yaml)"
    ERRORS=$((ERRORS + 1))
  fi
done < <(find "$HARNESS_ROOT/modules" -name "module.yaml" -type f 2>/dev/null | sort)

# ─── Check 3: Each module.yaml has required fields ───────────────────
echo ""
echo "Check 3: Module structure validation"
REQUIRED_FIELDS=("id" "name" "version" "description")
while IFS= read -r module_yaml; do
  rel_module="${module_yaml#"$HARNESS_ROOT"/}"
  missing_fields=()
  for field in "${REQUIRED_FIELDS[@]}"; do
    if ! grep -qE "^${field}:" "$module_yaml"; then
      missing_fields+=("$field")
    fi
  done
  if [[ ${#missing_fields[@]} -gt 0 ]]; then
    echo "  FAIL: $rel_module (missing: ${missing_fields[*]})"
    ERRORS=$((ERRORS + 1))
  else
    echo "  OK:   $rel_module"
  fi
done < <(find "$HARNESS_ROOT/modules" -name "module.yaml" -type f 2>/dev/null | sort)

# ─── Check 4: Module asset references exist ──────────────────────────
echo ""
echo "Check 4: Module asset references"
while IFS= read -r module_yaml; do
  rel_module="${module_yaml#"$HARNESS_ROOT"/}"
  module_dir=$(dirname "$module_yaml")

  # Check prompt file (POSIX sed — portable across BSD/GNU grep)
  prompt_file=$(sed -n 's/^prompt:[[:space:]]*//p' "$module_yaml" 2>/dev/null | head -1 | xargs)
  if [[ -n "$prompt_file" ]]; then
    if [[ -f "$module_dir/$prompt_file" ]]; then
      echo "  OK:   $rel_module → $prompt_file"
    else
      echo "  FAIL: $rel_module → $prompt_file (not found)"
      ERRORS=$((ERRORS + 1))
    fi
  fi

  # Check hook files
  while IFS= read -r hook_file; do
    hook_file=$(echo "$hook_file" | sed 's/^[[:space:]]*- //' | xargs)
    [[ -z "$hook_file" ]] && continue
    if [[ -f "$module_dir/hooks/$hook_file" ]]; then
      echo "  OK:   $rel_module → hooks/$hook_file"
    else
      echo "  WARN: $rel_module → hooks/$hook_file (not found)"
      WARNINGS=$((WARNINGS + 1))
    fi
  done < <(sed -n '/^hooks:/,/^[^[:space:]]/{ /^[[:space:]]*- /p }' "$module_yaml" 2>/dev/null)

done < <(find "$HARNESS_ROOT/modules" -name "module.yaml" -type f 2>/dev/null | sort)

# ─── Summary ─────────────────────────────────────────────────────────
echo ""
echo "================================"
echo "Results: $ERRORS errors, $WARNINGS warnings"

if [[ $ERRORS -gt 0 ]]; then
  echo "FAILED: Registry and module definitions are out of sync"
  exit 1
fi

echo "PASSED: Registry is consistent with module definitions"
exit 0
