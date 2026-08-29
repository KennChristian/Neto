#!/usr/bin/env bash
# PostToolUse hook: reminds Claude to update MANIFEST.md when a new file
# is created in a MANIFEST-tracked directory.
#
# Receives JSON on stdin from Claude Code with tool_input.file_path.
# Exits 2 + stderr message if the file is missing from its nearest MANIFEST.md.
#
# Installation: Add to .claude/settings.json PostToolUse hook for Write|Edit.
# See hooks/settings.json.example for the configuration.

set -euo pipefail

# ─── Configuration — adapt for your project ───────────────────────────
SOURCE_EXTENSIONS="py|ts|tsx|js|jsx|yml|yaml|json|toml|cfg|ini|sh"
SKIP_DIRS="__pycache__|node_modules|.git|dist|build|.venv|vendor|target"
SKIP_FILES="__init__.py|MANIFEST.md|CLAUDE.md"
# ──────────────────────────────────────────────────────────────────────

# Read JSON from stdin
INPUT=$(cat)

# Extract the file path from tool input
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

BASENAME=$(basename "$FILE_PATH")

# Skip MANIFEST.md, CLAUDE.md, and other skip files
IFS='|' read -ra SKIP_ARRAY <<< "$SKIP_FILES"
for skip in "${SKIP_ARRAY[@]}"; do
  if [[ "$BASENAME" == "$skip" ]]; then
    exit 0
  fi
done

# Skip hidden files
if [[ "$BASENAME" == .* ]]; then
  exit 0
fi

# Skip non-source files (check extension)
EXT="${BASENAME##*.}"
if [[ "$BASENAME" == "$EXT" ]]; then
  # No extension
  exit 0
fi
if ! echo "$EXT" | grep -qE "^($SOURCE_EXTENSIONS)$"; then
  exit 0
fi

# Skip files in excluded directories
IFS='|' read -ra DIR_SKIP_ARRAY <<< "$SKIP_DIRS"
for skip_dir in "${DIR_SKIP_ARRAY[@]}"; do
  if [[ "$FILE_PATH" == */"$skip_dir"/* ]]; then
    exit 0
  fi
done

# Walk up from the file's directory to find the nearest MANIFEST.md
DIR=$(dirname "$FILE_PATH")
PROJECT_ROOT=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
if [[ -z "$PROJECT_ROOT" ]]; then
  PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
fi

MANIFEST=""
SEARCH_DIR="$DIR"
while [[ -n "$SEARCH_DIR" ]] && [[ "$SEARCH_DIR" == "$PROJECT_ROOT"* ]]; do
  if [[ -f "$SEARCH_DIR/MANIFEST.md" ]]; then
    MANIFEST="$SEARCH_DIR/MANIFEST.md"
    break
  fi
  PARENT=$(dirname "$SEARCH_DIR")
  if [[ "$PARENT" == "$SEARCH_DIR" ]]; then
    break
  fi
  SEARCH_DIR="$PARENT"
done

# No MANIFEST.md found in ancestry — nothing to check
if [[ -z "$MANIFEST" ]]; then
  exit 0
fi

# Check if the filename appears in the MANIFEST.md
if ! grep -qF "$BASENAME" "$MANIFEST"; then
  REL_MANIFEST=${MANIFEST#"$PROJECT_ROOT"/}
  REL_FILE=${FILE_PATH#"$PROJECT_ROOT"/}
  echo "MANIFEST update needed: \`$REL_FILE\` is not listed in \`$REL_MANIFEST\`. Please add it." >&2
  exit 2
fi

exit 0
