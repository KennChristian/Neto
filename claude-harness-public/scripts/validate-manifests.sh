#!/usr/bin/env bash
# Validate all MANIFEST.md files against actual directory contents.
# Exits non-zero if any files are missing from their nearest MANIFEST.md.
# Usage: ./scripts/validate-manifests.sh
#
# Suitable for CI pipelines or manual checks.

set -euo pipefail

# ─── Configuration — adapt for your project ───────────────────────────
SOURCE_EXTENSIONS="py|ts|tsx|js|jsx|yml|yaml|json|toml|cfg|ini|sh"
SKIP_DIRS="__pycache__|node_modules|.git|dist|build|.venv|vendor|target"
SKIP_FILES="__init__.py|MANIFEST.md|CLAUDE.md"
# ──────────────────────────────────────────────────────────────────────

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

ERRORS=0
WARNINGS=0

should_skip() {
  local path="$1"
  IFS='|' read -ra DIR_SKIP_ARRAY <<< "$SKIP_DIRS"
  for skip_dir in "${DIR_SKIP_ARRAY[@]}"; do
    if [[ "$path" == */"$skip_dir"/* ]] || [[ "$path" == "$skip_dir"/* ]]; then
      return 0
    fi
  done
  return 1
}

is_skip_file() {
  local basename="$1"
  IFS='|' read -ra FILE_SKIP_ARRAY <<< "$SKIP_FILES"
  for skip in "${FILE_SKIP_ARRAY[@]}"; do
    if [[ "$basename" == "$skip" ]]; then
      return 0
    fi
  done
  return 1
}

echo "Validating MANIFEST.md files..."
echo "================================"

# Find all MANIFEST.md files
while IFS= read -r manifest; do
  manifest_dir=$(dirname "$manifest")
  rel_manifest=${manifest#"$PROJECT_ROOT"/}
  missing_files=()

  # Get all source files in the manifest's directory (depth=1 only)
  while IFS= read -r file; do
    [[ -z "$file" ]] && continue
    should_skip "$file" && continue

    basename=$(basename "$file")

    # Skip hidden files and configured skip files
    [[ "$basename" == .* ]] && continue
    is_skip_file "$basename" && continue

    # Check if filename appears in the MANIFEST
    if ! grep -qF "$basename" "$manifest"; then
      missing_files+=("${file#"$PROJECT_ROOT"/}")
    fi
  done < <(find "$manifest_dir" -maxdepth 1 -type f 2>/dev/null | while IFS= read -r candidate; do
    ext="${candidate##*.}"
    [[ "$candidate" == "$ext" ]] && continue
    echo "$ext" | grep -qE "^($SOURCE_EXTENSIONS)$" && echo "$candidate"
  done)

  # Report results for this manifest
  if [[ ${#missing_files[@]} -gt 0 ]]; then
    echo ""
    echo "FAIL: $rel_manifest"
    for f in "${missing_files[@]}"; do
      echo "  - Missing: $f"
      ERRORS=$((ERRORS + 1))
    done
  else
    echo "OK:   $rel_manifest"
  fi

  # Check for stale entries — files listed in table rows (| `file` |) that don't exist
  while IFS= read -r listed_file; do
    [[ -z "$listed_file" ]] && continue
    # Skip directory references (ending with /)
    [[ "$listed_file" == */ ]] && continue
    # Skip non-file references (no extension)
    [[ "$listed_file" != *.* ]] && continue
    check_path="$manifest_dir/$listed_file"
    if [[ ! -e "$check_path" ]]; then
      # Also search subdirectories for the basename
      basename_only=$(basename "$listed_file")
      if ! find "$manifest_dir" -name "$basename_only" -type f -print -quit 2>/dev/null | grep -q .; then
        echo "  - Stale? $listed_file (not found under $manifest_dir/)"
        WARNINGS=$((WARNINGS + 1))
      fi
    fi
  done < <(sed -n 's/^| `\([^`]*\)`.*/\1/p' "$manifest" 2>/dev/null | sort -u)

done < <(find "$PROJECT_ROOT" -name "MANIFEST.md" -not -path "*/.git/*" -not -path "*/node_modules/*" | sort)

echo ""
echo "================================"
echo "Results: $ERRORS missing entries, $WARNINGS stale warnings"

if [[ $ERRORS -gt 0 ]]; then
  echo "FAILED: Some files are not listed in their MANIFEST.md"
  exit 1
fi

echo "PASSED: All MANIFEST.md files are up to date"
exit 0
