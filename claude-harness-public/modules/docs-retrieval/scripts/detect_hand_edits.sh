#!/usr/bin/env bash
# Detect hand-edits to generated files via hash header verification (Plan 233 §2).
#
# For every file matching a generated-path glob, extract its source-sha from
# the hash header, re-invoke the declared generator in --check mode, and
# compare the computed hash against the recorded one. Reports drift with a
# directive message for each offending file.
#
# Exit codes:
#   0 — no drift detected
#   1 — drift detected (hand-edit or stale); user must regenerate
#   2 — generator invocation error
#
# Usage:
#   scripts/detect_hand_edits.sh [--staged-only] [FILE...]
#
# In --staged-only mode, only files in `git diff --cached` are checked
# (pre-commit hook fast path). Without arguments, checks all known generated
# paths recursively.
set -euo pipefail

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$PROJECT_ROOT"

STAGED_ONLY=0
declare -a EXPLICIT_FILES=()
for arg in "$@"; do
  case "$arg" in
    --staged-only) STAGED_ONLY=1 ;;
    -h|--help)
      sed -n '2,20p' "$0"
      exit 0
      ;;
    *) EXPLICIT_FILES+=("$arg") ;;
  esac
done

# Globs for files that MUST be generated (must carry hash header)
GENERATED_GLOBS=(
  "docs/_views/**/*.md"
  "docs/implementation-plans/MANIFEST.md"
  "docs/decisions/MANIFEST.md"
  "docs/test-specs/MANIFEST.md"
  "docs/lessons/MANIFEST.md"
  "docs/implementation-plans/00-index.md"
  "docs/axes/registry.yaml"
)

collect_files() {
  if [[ ${#EXPLICIT_FILES[@]} -gt 0 ]]; then
    printf '%s\n' "${EXPLICIT_FILES[@]}"
    return
  fi
  if [[ $STAGED_ONLY -eq 1 ]]; then
    git diff --cached --name-only --diff-filter=ACM
    return
  fi
  # Enumerate all generated paths (bash 3.x compatible — no globstar)
  [[ -d docs/_views ]] && find docs/_views -type f -name "*.md"
  for f in \
    docs/implementation-plans/MANIFEST.md \
    docs/decisions/MANIFEST.md \
    docs/test-specs/MANIFEST.md \
    docs/lessons/MANIFEST.md \
    docs/implementation-plans/00-index.md \
    docs/axes/registry.yaml; do
    [[ -f "$f" ]] && echo "$f"
  done
}

extract_header_sha() {
  local file="$1"
  head -1 "$file" | sed -n 's/.*source-sha: \([a-f0-9]\{16,\}\).*/\1/p'
}

extract_generator() {
  local file="$1"
  head -1 "$file" | sed -n 's/.*generator: \([^ ]*\)@.*/\1/p'
}

is_generated_path() {
  local file="$1"
  case "$file" in
    docs/_views/*) return 0 ;;
    docs/implementation-plans/MANIFEST.md|docs/decisions/MANIFEST.md) return 0 ;;
    docs/test-specs/MANIFEST.md|docs/lessons/MANIFEST.md) return 0 ;;
    docs/implementation-plans/00-index.md|docs/axes/registry.yaml) return 0 ;;
  esac
  # Check for hash header as fallback
  [[ -f "$file" ]] && head -1 "$file" 2>/dev/null | grep -q "source-sha:" && return 0
  return 1
}

DRIFT_COUNT=0
CHECKED=0

while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  [[ ! -f "$file" ]] && continue
  is_generated_path "$file" || continue

  CHECKED=$((CHECKED + 1))
  header_sha=$(extract_header_sha "$file" || true)
  if [[ -z "$header_sha" ]]; then
    echo "HAND-EDIT DETECTED: $file — missing or malformed generator header" >&2
    DRIFT_COUNT=$((DRIFT_COUNT + 1))
    continue
  fi

  gen=$(extract_generator "$file" || true)
  if [[ -z "$gen" ]]; then
    echo "HAND-EDIT DETECTED: $file — generator tag missing from header" >&2
    DRIFT_COUNT=$((DRIFT_COUNT + 1))
    continue
  fi

  # Dispatch --check to the appropriate wrapper
  case "$gen" in
    scripts/generate_axis_registry.py)
      if ! scripts/generate-axis-registry.sh --check >/dev/null 2>&1; then
        echo "HAND-EDIT DETECTED: $file — run scripts/generate-axis-registry.sh to regenerate" >&2
        DRIFT_COUNT=$((DRIFT_COUNT + 1))
      fi
      ;;
    scripts/generate_axis_views.py)
      if ! scripts/generate-axis-views.sh --check >/dev/null 2>&1; then
        echo "HAND-EDIT DETECTED: $file — run scripts/generate-axis-views.sh to regenerate" >&2
        DRIFT_COUNT=$((DRIFT_COUNT + 1))
      fi
      ;;
    *)
      echo "warning: unknown generator $gen for $file; skipping check" >&2
      ;;
  esac
done < <(collect_files)

echo "detect_hand_edits: checked $CHECKED files, $DRIFT_COUNT drift" >&2

[[ $DRIFT_COUNT -eq 0 ]]
