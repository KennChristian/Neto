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

# The second robot is NOT a blank machine: as of 2026-09-12 it runs a
# 2026-09-01 build of this same project — dashboard, supervaise, watchdogs, its
# own Bluetooth speaker, its own tuning. That build predates the operator
# console, so it has no floor lease and believes it is its own authority.
# This is therefore an UPDATE, and the rules follow from that:
#   * no --delete: it may hold files this tree does not
#   * its app/.env is left alone — it has working keys already
#   * its supervaise drop-in is left alone — that file carries per-MACHINE
#     tuning (its speaker's AEC delay, its mic thresholds) which is not ours
#     to overwrite; the diff is printed instead so a human can reconcile
#   * everything replaced is backed up first, next to the original
say "backing up what this will replace"
STAMP=$(date +%Y%m%d-%H%M%S)
run_remote "mkdir -p \$HOME/deploy-backups/$STAMP && \
  [ -d $REMOTE ] && tar czf \$HOME/deploy-backups/$STAMP/repo-config.tgz \
    -C \$HOME $NAME/config $NAME/app/.env 2>/dev/null; \
  sudo -n cp -r /etc/systemd/system/supervaise.service.d \$HOME/deploy-backups/$STAMP/ 2>/dev/null; \
  ls \$HOME/deploy-backups/$STAMP"

say "copying the repo (no venv, no git, no media, NO --delete)"
if [ "$MODE" = dry ]; then
  echo "  rsync -> $TARGET:$REMOTE  (excluding .venv .git data/prerendered/*.wav app/.env)"
else
  rsync -a --info=stats1 \
    --exclude '.venv' --exclude '.git' --exclude '__pycache__' \
    --exclude 'dashboard/assets' --exclude 'dashboard/certs' \
    --exclude 'data/prerendered/duet/*.wav' --exclude 'app/wake/data' \
    --exclude 'app/.env' \
    -e "ssh -o BatchMode=yes" "$HERE/" "$TARGET:$NAME/"
  # app/.env is NOT copied: that machine already has working keys, and its own
  # may differ. If it is ever made Panganiban and something is missing, the
  # persona loader says so at boot.
  echo "  app/.env left as it was on that machine"
fi

say "python environment (existing venv is reused, only new requirements install)"
run_remote "cd $REMOTE && [ -d app/.venv ] || python3 -m venv app/.venv"
run_remote "cd $REMOTE && app/.venv/bin/pip -q install --upgrade pip && app/.venv/bin/pip -q install -r app/requirements.txt"

say "dashboard + services"
run_remote "ln -sfn $REMOTE/dashboard \$HOME/pi_dashboard"
for unit in pi-dashboard wifi-fallback; do
  if [ "$MODE" = dry ]; then echo "  remote: install $unit.service"; else
    "${SSH[@]}" "$TARGET" "sudo -n install -m 644 $REMOTE/dashboard/$unit.service /etc/systemd/system/$unit.service"
  fi
done
# The drop-in is NOT overwritten: it holds per-machine tuning (that robot's
# speaker AEC delay, its mic thresholds) and it already exists there. What it
# is missing are the settings added since its build — the name pin especially,
# without which "Panganiban" would be said differently on the two robots. Those
# are appended as a separate drop-in file, which systemd merges, so the
# machine's own file is untouched and the change is one file to delete.
say "settings added since that machine's build"
if [ "$MODE" = dry ]; then
  echo "  remote: append zz-from-alpha.conf (name pin, voice lock)"
else
  PIN_SPEED=$(systemctl show supervaise.service -p Environment | tr ' ' '\n' | grep '^CJ_NAME_PIN_SPEED=' || true)
  PIN_SYL=$(systemctl show supervaise.service -p Environment | tr ' ' '\n' | grep '^CJ_NAME_PIN_SYLLABLE=' || true)
  LOCK=$(systemctl show supervaise.service -p Environment | tr ' ' '\n' | grep '^CJ_VOICE_LOCK_THRESHOLD=' || true)
  "${SSH[@]}" "$TARGET" "sudo -n mkdir -p /etc/systemd/system/supervaise.service.d && \
    printf '[Service]\n# Added by scripts/deploy_second_robot.sh from the authority machine.\n# Only settings this machine cannot have had at its build date. Its OWN\n# wakeword.conf is untouched: that file holds tuning specific to this\n# robot, its speaker and its room. Delete this file to undo.\n%s\n%s\n%s\n' \
      '${PIN_SPEED}' '${PIN_SYL}' '${LOCK}' \
      | sudo -n tee /etc/systemd/system/supervaise.service.d/zz-from-alpha.conf >/dev/null"
  echo "  wrote zz-from-alpha.conf; its own wakeword.conf left alone"
  echo "  differences between the two drop-ins (for a human to reconcile):"
  sudo -n cat /etc/systemd/system/supervaise.service.d/wakeword.conf | grep '^Environment=' | sort > /tmp/alpha.env.$$
  "${SSH[@]}" "$TARGET" "sudo -n cat /etc/systemd/system/supervaise.service.d/wakeword.conf 2>/dev/null | grep '^Environment=' | sort" > /tmp/beta.env.$$ || true
  diff /tmp/alpha.env.$$ /tmp/beta.env.$$ | sed 's/^/    /' | head -30 || true
  rm -f /tmp/alpha.env.$$ /tmp/beta.env.$$
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
