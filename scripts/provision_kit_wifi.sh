#!/bin/bash
# Join this robot to the venue kit's travel router (2026-09-12).
#
# WHY A TRAVEL ROUTER: the two robots only need a LAN between them — the floor
# lease is one small HTTP poll per second — while ONLY the Panganiban robot
# needs the internet. Carrying your own router means the robot-to-robot link
# never depends on the venue: same network name everywhere, saved before you
# travel, and immune to the guest-network client isolation that would silently
# break the lease (the mic fails closed, so that outage stops the exhibit).
# The router uplinks to venue WiFi or a phone; that part may fail freely.
#
#   authority robot:  sudo scripts/provision_kit_wifi.sh --authority "KitSSID" "secret"
#   second robot:     sudo scripts/provision_kit_wifi.sh --secondary "KitSSID" "secret"
#   see the commands:  add --dry-run  (changes nothing)
#
# --authority  the machine config/robots.json names in `authority.host`. It
#              leases to itself over loopback, so it survives any network loss.
# --secondary  the other machine. Also saves the authority's "CJAP Reachy"
#              hotspot as a LOWER-priority client profile, so if the router
#              dies it follows the authority onto its hotspot and keeps the
#              lease alive (no internet then: duet, not conversation). Its own
#              setup-hotspot is delayed 10 min so the authority wins that race.
#
# Afterwards, on the router: give the authority robot a DHCP reservation and
# put that address in config/robots.json `authority.ip` — that removes mDNS,
# which is the last venue-dependent piece. See docs/RUNBOOK-venue-network.md.
set -euo pipefail

ROLE="" ; DRY=0 ; SSID="" ; PSK=""
KIT_CON="KitRouter"          # profile name; the SSID can change without renaming it
AP_CLIENT_CON="CJAP-Reachy-client"
AP_SSID="${CJ_SETUP_SSID:-CJAP Reachy}"
AP_PW="${CJ_SETUP_PW:-reachymini}"
KIT_PRIORITY=100             # every venue profile on this Pi sits at 10 or below
AP_PRIORITY=50               # below the kit router, above every venue network
UNIT_DROPIN=/etc/systemd/system/wifi-fallback.service.d/secondary.conf

usage() { sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//' ; exit "${1:-1}" ; }
for a in "$@"; do case "$a" in
  --authority) ROLE=authority ;; --secondary) ROLE=secondary ;;
  --dry-run)   DRY=1 ;;        -h|--help) usage 0 ;;
  -*)          echo "unknown flag: $a" >&2 ; usage ;;
  *)           if [ -z "$SSID" ]; then SSID="$a"; elif [ -z "$PSK" ]; then PSK="$a"; else echo "too many arguments" >&2; usage; fi ;;
esac; done
[ -n "$ROLE" ] && [ -n "$SSID" ] || usage
[ ${#SSID} -le 32 ] || { echo "SSID longer than 32 bytes" >&2; exit 1; }
if [ -n "$PSK" ] && [ ${#PSK} -lt 8 ]; then echo "WPA passphrase must be 8+ characters" >&2; exit 1; fi

run() {   # echo every command; execute unless --dry-run
  printf '  %q' "$@" ; printf '\n'
  [ "$DRY" = 1 ] || "$@"
}
have_con() { nmcli -t -f NAME connection show 2>/dev/null | grep -qxF "$1"; }

# One profile per role, rewritten in place so re-running is safe (a new venue,
# a changed passphrase) and never leaves a second profile for the same SSID.
provision() {   # <con-name> <ssid> <psk|""> <priority>
  local con="$1" ssid="$2" psk="$3" prio="$4"
  if have_con "$con"; then
    echo "updating profile $con -> \"$ssid\""
    run nmcli connection modify "$con" 802-11-wireless.ssid "$ssid" \
        connection.autoconnect yes connection.autoconnect-priority "$prio"
  else
    echo "creating profile $con -> \"$ssid\""
    run nmcli connection add type wifi con-name "$con" ifname wlan0 ssid "$ssid" \
        connection.autoconnect yes connection.autoconnect-priority "$prio"
  fi
  if [ -n "$psk" ]; then
    run nmcli connection modify "$con" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$psk"
  else
    run nmcli connection modify "$con" wifi-sec.key-mgmt "" wifi-sec.psk ""
  fi
}

echo "== kit router =="
provision "$KIT_CON" "$SSID" "$PSK" "$KIT_PRIORITY"

if [ "$ROLE" = secondary ]; then
  echo "== fallback: follow the authority onto its own hotspot =="
  provision "$AP_CLIENT_CON" "$AP_SSID" "$AP_PW" "$AP_PRIORITY"
  echo "== delay this machine's own setup-hotspot (the authority must win) =="
  if [ "$DRY" = 1 ]; then
    echo "  write $UNIT_DROPIN with CJ_SETUP_MISSES=30"
  else
    mkdir -p "$(dirname "$UNIT_DROPIN")"
    printf '[Service]\n# 2026-09-12 venue kit: the SECOND robot waits 10 min before raising its own\n# AP, so the authority raises the fallback LAN first and this machine joins it.\nEnvironment=CJ_SETUP_MISSES=30\n' > "$UNIT_DROPIN"
    echo "  wrote $UNIT_DROPIN"
  fi
  run systemctl daemon-reload
  run systemctl restart wifi-fallback.service
fi

echo
echo "saved WiFi profiles by priority (highest wins):"
if [ "$DRY" = 1 ]; then echo "  (dry run — nothing changed)"; else
  for c in $(nmcli -t -f NAME,TYPE connection show | awk -F: '$2 ~ /wireless/ {print $1}'); do
    printf '  %-24s prio=%-5s auto=%s\n' "$c" \
      "$(nmcli -g connection.autoconnect-priority connection show "$c")" \
      "$(nmcli -g connection.autoconnect connection show "$c")"
  done | sort -t= -k2 -rn
fi
echo
echo "next: reserve the authority robot's address on the router, then set"
echo "      authority.ip in config/robots.json on BOTH machines and restart"
echo "      pi-dashboard + supervaise."
