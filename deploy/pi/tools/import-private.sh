#!/bin/bash
# import-private.sh — restore a bundle made by export-private.sh on a robot
# that has already run deploy/pi/install.sh.
#
#   import-private.sh private-xxx.tar.gz.enc [--restart]
#
# Extracts into $HOME (same relative paths), fixes permissions, and with
# --restart restarts supervaise + pi-dashboard so the keys take effect.
set -euo pipefail
IN="${1:?usage: import-private.sh <bundle.enc> [--restart]}"
if [ $# -gt 2 ] || { [ -n "${2:-}" ] && [ "$2" != "--restart" ]; }; then
  echo "one bundle at a time (got: $*) — name the file explicitly, e.g. the newest:"
  echo "  import-private.sh \"\$(ls -t ~/private-*.tar.gz.enc | head -1)\" --restart"; exit 2
fi
[ -s "$IN" ] || { echo "no such bundle: $IN"; exit 2; }
PASSARG=(); [ -n "${PRIVATE_PASS:-}" ] && PASSARG=(-pass env:PRIVATE_PASS)
cd "$HOME"
openssl enc -d -aes-256-cbc -pbkdf2 "${PASSARG[@]}" -in "$IN" | tar xzvf - | sed 's/^/  restored: /'
M="Supervaise-Reachy-Mini-Project-main"
chmod 600 "$M/app/.env" "$M/voice/config.py" pi_dashboard/certs/key.pem 2>/dev/null || true
chmod 600 pi_dashboard/assets/*.json 2>/dev/null || true
if grep -qE '^(ANTHROPIC|OPENAI|ELEVEN)_API_KEY=$' "$M/app/.env" 2>/dev/null; then
  echo "WARNING: $M/app/.env still has an empty API key"
fi
if [ "${2:-}" = "--restart" ]; then
  sudo systemctl restart pi-dashboard supervaise
  echo "services restarted"
fi
echo "done — run verify.sh to check the robot end to end"
