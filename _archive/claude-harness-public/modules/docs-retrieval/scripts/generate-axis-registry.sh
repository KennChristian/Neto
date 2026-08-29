#!/usr/bin/env bash
# Bash wrapper for generate_axis_registry.py (Plan 231b).
# Runs the generator inside the `grammar` conda env.
# Propagates all arguments and exit codes.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec conda run -n grammar --no-capture-output python "$SCRIPT_DIR/generate_axis_registry.py" "$@"
