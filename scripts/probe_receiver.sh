#!/bin/bash
# Does the wireless mic receiver expose its MUTE state to the OS?
#
# Run once with the receiver unplugged, once plugged in and unmuted, once
# plugged in and muted, and diff the three outputs. What to look for:
#   * a NEW USB device (lsusb) and/or a new ALSA capture card — a USB
#     receiver; an analog receiver into the headset jack shows nothing here
#     and can only be judged by signal level (no hard gate available);
#   * a hidraw / input device belonging to it — some receivers report mute
#     as a HID consumer-control key (KEY_MICMUTE) or a vendor HID report;
#   * a mixer "Capture Switch" on its card that flips with the mute button;
#   * failing all of that, the mute is only visible as the audio level
#     (silence or a fixed tone) — then the loudness threshold is the only
#     gate and the console's speech-onset trigger must be tuned against it.
set -u
echo "== $(date '+%F %T') host $(hostname) =="
echo "-- USB --"; lsusb
echo "-- ALSA capture cards --"; arecord -l 2>/dev/null
echo "-- input devices --"; ls -la /dev/input/by-id/ 2>/dev/null
echo "-- hidraw --"
for h in /sys/class/hidraw/*; do
  [ -e "$h" ] || continue
  echo "$h: $(grep -hE 'HID_NAME|HID_ID' "$h/device/uevent" 2>/dev/null | tr '\n' ' ')"
done
echo "-- mixer capture switches per card --"
for c in /proc/asound/card*; do
  n=$(basename "$c"); idx=${n#card}
  echo "card $idx: $(cat "$c/id" 2>/dev/null)"
  amixer -c "$idx" contents 2>/dev/null | grep -iE "Capture Switch|Mute" -A2 | grep -E "name=|values" | sed 's/^/   /'
done
echo "-- KEY_MICMUTE watch (10 s; press the receiver's mute button now) --"
if command -v evtest >/dev/null; then
  for d in /dev/input/event*; do
    timeout 10 evtest --grab "$d" 2>/dev/null | grep -iE "MICMUTE|MUTE" & done; wait
else
  echo "   evtest not installed: sudo apt install evtest"
fi
