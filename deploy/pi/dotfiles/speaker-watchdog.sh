#!/bin/bash
# speaker-watchdog - keep robot audio on a Bluetooth speaker whenever one is
# connected, otherwise on the internal XMOS speaker, so the robot is never mute.
#
# Priority (first usable wins): Sony ULT FIELD 1, then Marshall EMBERTON.
# "Usable" = bluetoothctl says Connected AND BlueALSA exposes its A2DP PCM
# (a speaker can be "connected" with no audio endpoint yet -> would be mute).
# Route mechanics live in ~/bin/audio-out (rewrites ~/.asoundrc.route; only
# newly opened playback streams follow a switch, i.e. the next utterance).
# To force the internal speaker while a BT speaker is on, stop this service
# first: sudo systemctl stop speaker-watchdog
# 2026-08-26: generalised from Sony-only to both paired speakers + PCM check.
set -u
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"

SONY_MAC="50:1B:6A:8B:16:F2"       # Sony ULT FIELD 1
MARSHALL_MAC="04:21:44:84:1F:C1"   # Marshall EMBERTON
# Same per-robot override file audio-out uses (other speakers' MACs).
[ -f "$HOME/bin/audio-out.local" ] && . "$HOME/bin/audio-out.local"
SPEAKERS=("$SONY_MAC|sony" "$MARSHALL_MAC|marshall")   # priority order

ROUTE="$HOME/.asoundrc.route"
AUDIO_OUT="$HOME/bin/audio-out"
INTERVAL=15

connected()   { bluetoothctl info "$1" 2>/dev/null | grep -q "Connected: yes"; }
has_pcm()     { bluealsa-aplay -L 2>/dev/null | grep -q "DEV=$1,PROFILE=a2dp"; }
routed_mac()  { awk -F'"' '/type bluealsa/ {bt=1} bt && /device/ {print $2; exit}' "$ROUTE" 2>/dev/null; }

echo "speaker-watchdog: start (priority: ${SPEAKERS[*]})"
while true; do
    want_mac=""; want_name=""
    for entry in "${SPEAKERS[@]}"; do
        mac="${entry%%|*}"; name="${entry#*|}"
        if connected "$mac" && has_pcm "$mac"; then
            want_mac="$mac"; want_name="$name"; break
        fi
    done

    if [ -z "$want_mac" ]; then
        # nothing usable: try to (re)connect in priority order, one per pass
        for entry in "${SPEAKERS[@]}"; do
            mac="${entry%%|*}"
            connected "$mac" && continue
            if bluetoothctl connect "$mac" >/dev/null 2>&1; then
                sleep 2   # let BlueALSA register the A2DP endpoint
                break
            fi
        done
        for entry in "${SPEAKERS[@]}"; do
            mac="${entry%%|*}"; name="${entry#*|}"
            if connected "$mac" && has_pcm "$mac"; then
                want_mac="$mac"; want_name="$name"; break
            fi
        done
    fi

    cur="$(routed_mac)"
    if [ -n "$want_mac" ]; then
        if [ "$cur" != "$want_mac" ]; then
            echo "speaker-watchdog: $want_name ($want_mac) usable -> routing audio to it"
            "$AUDIO_OUT" "$want_name" >/dev/null 2>&1 || echo "speaker-watchdog: audio-out $want_name failed"
        fi
    elif [ -n "$cur" ]; then
        echo "speaker-watchdog: no usable Bluetooth speaker (was $cur) -> internal speaker"
        "$AUDIO_OUT" internal >/dev/null 2>&1 || echo "speaker-watchdog: audio-out internal failed"
    fi
    sleep "$INTERVAL"
done
