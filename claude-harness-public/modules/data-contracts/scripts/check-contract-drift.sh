#!/usr/bin/env bash
# PostToolUse hook: warns Claude when an output file is modified without
# updating its corresponding ODCS data contract.
#
# Receives JSON on stdin from Claude Code with tool_input.file_path.
# Exits 2 + stderr warning if the file is in a tracked output/schema directory
# and its data contract has not been modified in the current unstaged diff.
# Exit 0 for irrelevant files or when contract is already updated.
#
# WARNING-ONLY: Never blocks. Exit 2 is a soft warning, not a hard failure.
#
# Installation: Add to .claude/settings.json PostToolUse hook for Write|Edit.
# See hooks/settings-with-contracts.json.example for the configuration.

set -euo pipefail

# ─── Configuration — adapt for your project ───────────────────────────
CONTRACTS_DIR="docs/datacontracts"
OUTPUT_DIRS="outputs|exports|data/out"
SCHEMA_DIRS="scripts|migrations|sql"
OUTPUT_EXTENSIONS="csv|parquet|json|yaml|yml|sql|py"
# ──────────────────────────────────────────────────────────────────────

# Read JSON from stdin
INPUT=$(cat)

# Extract the file path from tool input
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Determine project root
PROJECT_ROOT=$(echo "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
if [[ -z "$PROJECT_ROOT" ]]; then
  PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
fi
if [[ -z "$PROJECT_ROOT" ]]; then
  exit 0
fi

# Make path relative to project root
REL_PATH="${FILE_PATH#"$PROJECT_ROOT"/}"

# Skip if file is not in an output or schema directory
IN_TRACKED_DIR=false
IFS='|' read -ra OUTPUT_DIR_ARRAY <<< "$OUTPUT_DIRS"
for dir in "${OUTPUT_DIR_ARRAY[@]}"; do
  if [[ "$REL_PATH" == "$dir"/* ]]; then
    IN_TRACKED_DIR=true
    break
  fi
done

if [[ "$IN_TRACKED_DIR" == false ]]; then
  IFS='|' read -ra SCHEMA_DIR_ARRAY <<< "$SCHEMA_DIRS"
  for dir in "${SCHEMA_DIR_ARRAY[@]}"; do
    if [[ "$REL_PATH" == "$dir"/* ]]; then
      IN_TRACKED_DIR=true
      break
    fi
  done
fi

if [[ "$IN_TRACKED_DIR" == false ]]; then
  exit 0
fi

# Check file extension
BASENAME=$(basename "$FILE_PATH")
EXT="${BASENAME##*.}"
if [[ "$BASENAME" == "$EXT" ]]; then
  exit 0
fi
if ! echo "$EXT" | grep -qE "^($OUTPUT_EXTENSIONS)$"; then
  exit 0
fi

# Skip data contract files themselves (avoid self-referential warnings)
if [[ "$REL_PATH" == "$CONTRACTS_DIR"/* ]]; then
  exit 0
fi

# Check if contracts directory exists
if [[ ! -d "$PROJECT_ROOT/$CONTRACTS_DIR" ]]; then
  exit 0
fi

# Derive expected contract filename from the file stem:
# - Take the filename without extension
# - Replace underscores with hyphens
# - Append .odcs.yaml
STEM="${BASENAME%.*}"
CONTRACT_NAME=$(echo "$STEM" | tr '_' '-')
CONTRACT_FILE="$CONTRACTS_DIR/$CONTRACT_NAME.odcs.yaml"

# Check if a matching contract exists
if [[ ! -f "$PROJECT_ROOT/$CONTRACT_FILE" ]]; then
  # No contract for this file — not an error, just no governance yet
  exit 0
fi

# Check if the contract was already modified in the current unstaged diff
# (avoids false positives when user is updating both output and contract)
if git -C "$PROJECT_ROOT" diff --name-only 2>/dev/null | grep -qF "$CONTRACT_FILE"; then
  exit 0
fi

# Check staged diff too
if git -C "$PROJECT_ROOT" diff --cached --name-only 2>/dev/null | grep -qF "$CONTRACT_FILE"; then
  exit 0
fi

# Contract exists but hasn't been updated — warn
echo "Data contract drift: \`$REL_PATH\` was modified but its contract \`$CONTRACT_FILE\` has not been updated. If the output schema changed, please update the contract (version bump if needed)." >&2
exit 2
