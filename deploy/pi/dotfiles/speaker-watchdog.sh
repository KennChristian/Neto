#!/bin/bash
# Auto-connect the Sony ULT FIELD 1 and keep robot audio routed to it.
# Connected -> Bluetooth route (BlueALSA); unreachable -> internal XMOS,
# so the robot is never left mute. Route mechanics live in ~/bin/audio-out
# (rewrites ~/.asoundrc.route; new playback streams pick it up on open).
# To force the internal speaker while the BT speaker is on, stop this
# service first: sudo systemctl stop speaker-watchdog
MAC="50:1B:6A:8B:16:F2"
ROUTE="/home/pollen/.asoundrc.route"

connected() { bluetoothctl info "$MAC" | grep -q "Connected: yes"; }
bt_routed()  { grep -q "type bluealsa" "$ROUTE" 2>/dev/null; }

while true; do
  if ! connected; then
    bluetoothctl connect "$MAC" >/dev/null 2>&1
  fi
  if connected; then
    bt_routed || /home/pollen/bin/audio-out sony >/dev/null 2>&1
  else
    if bt_routed; then
      /home/pollen/bin/audio-out internal >/dev/null 2>&1
    fi
  fi
  sleep 15
done
