#!/bin/bash
# Put this repo on the SECOND Reachy Mini and make it run there (2026-09-12).
#
#   scripts/deploy_second_robot.sh [user@host]        default: pollen@reachy2
#   scripts/deploy_second_robot.sh --check            reachability + identity only
#   scripts/deploy_second_robot.sh --dry-run          print every remote step
#
# NEEDS KEY-BASED SSH FIRST. Run once, on THIS machine, and type the password:
#     ssh-copy-id pollen@<the second robot>
#
# Both machines run the SAME image and the same branch: the role is not baked
# in. Which one is Panganiban is `cjap_is`, held by the lease authority and
# switchable from /maintain. So this copies the repo, builds the venv, installs
# the two services, and leaves the machine as the Host until the console says
# otherwise.
#
# It does NOT rename the machine. config/robots.json maps the slot to whatever
# the hostname is (beta -> reachy2), because the machine's identity is the
# fact and the config is what bends.
#
# It does NOT touch: the reachy-mini daemon, audio routing, the LiveAvatar
# assets, or anything under /etc that this script does not create by name.
set -euo pipefail

TARGET="${1:-pollen@reachy2}"
MODE=run
case "${1:-}" in --check) MODE=check; TARGET="${2:-pollen@reachy2}";; --dry-run) MODE=dry; TARGET="${2:-pollen@reachy2}";; esac
case "${2:-}" in --check) MODE=check;; --dry-run) MODE=dry;; esac

HERE="$(cd "$(dirname "$0")/.." && pwd)"
NAME="$(basename "$HERE")"
REMOTE="\$HOME/$NAME"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8)

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
run_remote() {
  if [ "$MODE" = dry ]; then printf '  remote: %s\n' "$1"; else "${SSH[@]}" "$TARGET" "$1"; fi
}

say "reachability"
if ! "${SSH[@]}" "$TARGET" true 2>/dev/null; then
  echo "cannot log in to $TARGET without a password." >&2
  echo "Run this once on THIS machine, type the password, then re-run me:" >&2
  echo "    ssh-copy-id ${TARGET}" >&2
  exit 2
fi
RHOST=$("${SSH[@]}" "$TARGET" 'hostname -s')
RIP=$("${SSH[@]}" "$TARGET" "hostname -I | awk '{print \$1}'")
RMODEL=$("${SSH[@]}" "$TARGET" 'tr -d "\0" < /proc/device-tree/model 2>/dev/null || echo unknown')
echo "  $TARGET is '$RHOST' at $RIP ($RMODEL)"

# the slot comes from the hostname via config/robots.json — check it lines up
SLOT=$(python3 - "$HERE/config/robots.json" "$RHOST" <<'PY'
import json, sys
slots = json.load(open(sys.argv[1]))["slots"]
print(next((k for k, v in slots.items() if str(v).lower() == sys.argv[2].lower()), ""))
PY
)
if [ -z "$SLOT" ]; then
  echo "  config/robots.json has no slot for hostname '$RHOST'." >&2
  echo "  Add it (slots.beta = \"$RHOST\") rather than renaming the machine." >&2
  exit 3
fi
echo "  slot: $SLOT"

# how will it reach the lease authority? prefer the name, fall back to an address
AUTH_HOST=$(python3 -c "import json;print(json.load(open('$HERE/config/robots.json'))['authority']['host'])")
AUTH_PORT=$(python3 -c "import json;print(json.load(open('$HERE/config/robots.json'))['authority']['port'])")
MY_IP=$(hostname -I | awk '{print $1}')
if "${SSH[@]}" "$TARGET" "getent hosts ${AUTH_HOST}.local >/dev/null 2>&1"; then
  echo "  authority: ${AUTH_HOST}.local resolves from there — mDNS is fine"
else
  echo "  authority: ${AUTH_HOST}.local does NOT resolve from there."
  echo "            Set authority.ip to $MY_IP in config/robots.json on BOTH"
  echo "            machines (and reserve that address on the router)."
fi
[ "$MODE" = check ] && exit 0

say "copying the repo (no venv, no git, no media)"
if [ "$MODE" = dry ]; then
  echo "  rsync -> $TARGET:$REMOTE  (excluding .venv .git data/prerendered/*.wav)"
else
  rsync -a --delete --info=stats1 \
    --exclude '.venv' --exclude '.git' --exclude '__pycache__' \
    --exclude 'dashboard/assets' --exclude 'dashboard/certs' \
    --exclude 'data/prerendered/duet/*.wav' --exclude 'app/wake/data' \
    -e "ssh -o BatchMode=yes" "$HERE/" "$TARGET:$NAME/"
  # app/.env carries the API keys. The Host plays pre-rendered audio and needs
  # none of them — but a role swap makes this machine Panganiban, and then it
  # needs all of them. Copied deliberately, not by accident.
  scp -q -o BatchMode=yes "$HERE/app/.env" "$TARGET:$NAME/app/.env"
fi

say "python environment"
run_remote "cd $REMOTE && [ -d app/.venv ] || python3 -m venv app/.venv"
run_remote "cd $REMOTE && app/.venv/bin/pip -q install --upgrade pip && app/.venv/bin/pip -q install -r app/requirements.txt"

say "dashboard + services"
run_remote "ln -sfn $REMOTE/dashboard \$HOME/pi_dashboard"
for unit in pi-dashboard wifi-fallback; do
  if [ "$MODE" = dry ]; then echo "  remote: install $unit.service"; else
    "${SSH[@]}" "$TARGET" "sudo -n install -m 644 $REMOTE/dashboard/$unit.service /etc/systemd/system/$unit.service"
  fi
done
# supervaise.service and its drop-in are root-owned on THIS machine and not in
# the repo, so they are shipped explicitly. The drop-in carries the tuning:
# wake thresholds, the name pin, the voice lock.
if [ "$MODE" = dry ]; then
  echo "  remote: install supervaise.service + wakeword.conf drop-in"
else
  "${SSH[@]}" "$TARGET" "sudo -n mkdir -p /etc/systemd/system/supervaise.service.d"
  sudo -n cat /etc/systemd/system/supervaise.service |
    "${SSH[@]}" "$TARGET" "cat | sudo -n tee /etc/systemd/system/supervaise.service >/dev/null"
  sudo -n cat /etc/systemd/system/supervaise.service.d/wakeword.conf |
    "${SSH[@]}" "$TARGET" "cat | sudo -n tee /etc/systemd/system/supervaise.service.d/wakeword.conf >/dev/null"
fi
# Its own setup hotspot, named after the machine (2026-09-12, user: "change the
# wifi to reachy2, password reachy2, in case it is not connected to any wifi
# yet"). Both robots run the same fallback service, so without this they would
# both raise "CJAP Reachy" and you could not tell which one you had joined.
# Also delays its AP so the authority wins the race when a venue router dies —
# two APs at once and neither robot can join the other.
AP_SSID="${CJ_SETUP_SSID_REMOTE:-$RHOST}"
AP_PW="${CJ_SETUP_PW_REMOTE:-$RHOST}"
if [ ${#AP_PW} -lt 8 ]; then
  echo "  note: WPA needs 8+ characters — hotspot password padded to '${AP_PW}12345678'" >&2
  AP_PW="${AP_PW}12345678"
fi
say "setup hotspot: \"$AP_SSID\" / $AP_PW"
if [ "$MODE" = dry ]; then
  echo "  remote: wifi-fallback drop-in with CJ_SETUP_SSID=$AP_SSID"
else
  "${SSH[@]}" "$TARGET" "sudo -n mkdir -p /etc/systemd/system/wifi-fallback.service.d && \
    printf '[Service]\n# 2026-09-12: this machine raises its OWN named hotspot so the two\n# robots are distinguishable, and waits longer than the authority so it\n# joins that AP instead of raising a competing one.\nEnvironment=CJ_SETUP_SSID=$AP_SSID\nEnvironment=CJ_SETUP_PW=$AP_PW\nEnvironment=CJ_SETUP_MISSES=30\n' | sudo -n tee /etc/systemd/system/wifi-fallback.service.d/secondary.conf >/dev/null"
fi

run_remote "sudo -n systemctl daemon-reload"
run_remote "sudo -n systemctl enable --now pi-dashboard.service wifi-fallback.service"
run_remote "sudo -n systemctl enable --now supervaise.service"

say "checks"
run_remote "systemctl is-active pi-dashboard.service supervaise.service | paste -sd' '"
run_remote "cd $REMOTE && app/.venv/bin/python -m pytest tests/ -q 2>&1 | tail -1"
if [ "$MODE" != dry ]; then
  echo "  lease reachable from there:"
  "${SSH[@]}" "$TARGET" "curl -s -m 5 -o /dev/null -w '    %{http_code} in %{time_total}s\n' http://${AUTH_HOST}.local:${AUTH_PORT}/api/state" || echo "    FAILED — set authority.ip"
  echo
  echo "Now open /console on this machine: $RHOST should appear as $SLOT and start reporting."
fi
