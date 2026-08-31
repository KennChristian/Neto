#!/bin/bash
# bt-keepalive - stop a connected Bluetooth speaker from auto-standby while
# the robot is idle.  Sony ULT FIELD 1 powers itself off after ~15 min with
# no audio, Marshall EMBERTON after ~20 min; between answers the robot sends
# nothing, so the speaker quietly dies.  This loop plays a short INAUDIBLE
# pulse (20 Hz sub-bass at -30 dBFS + a whisper of noise) straight into the
# speaker's BlueALSA A2DP PCM every INTERVAL_S seconds, only while nothing
# else is streaming to it (BlueALSA PCMs are exclusive: a burst during an
# answer would make the answer fail to open the speaker).
#
#   bt-keepalive.sh          run the loop (systemd: bt-keepalive.service)
#   bt-keepalive.sh test     play one pulse now to every usable speaker
#   bt-keepalive.sh status   show what it would do
#
# Knobs (systemd Environment= or shell): BT_KEEPALIVE_INTERVAL_S (240),
# BT_KEEPALIVE_TONE_HZ (20), BT_KEEPALIVE_DB (-30 dBFS peak), BT_KEEPALIVE_DUR_S (2),
# BT_KEEPALIVE_NOISE (0.002 linear, ~-54 dBFS; 0 disables the noise bed).
set -u
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"

SONY_MAC="50:1B:6A:8B:16:F2"       # Sony ULT FIELD 1
MARSHALL_MAC="04:21:44:84:1F:C1"   # Marshall EMBERTON
[ -f "$HOME/bin/audio-out.local" ] && . "$HOME/bin/audio-out.local"
SPEAKERS=("$SONY_MAC|sony" "$MARSHALL_MAC|marshall")

INTERVAL_S="${BT_KEEPALIVE_INTERVAL_S:-240}"
TONE_HZ="${BT_KEEPALIVE_TONE_HZ:-20}"
PEAK_DB="${BT_KEEPALIVE_DB:--30}"
DUR_S="${BT_KEEPALIVE_DUR_S:-2}"
NOISE="${BT_KEEPALIVE_NOISE:-0.002}"
POLL_S=20
BUSY_RETRY_S=15
SPEAKING_JSON=/dev/shm/cj_speaking.json
WAV_DIR=/dev/shm

connected() { bluetoothctl info "$1" 2>/dev/null | grep -q "Connected: yes"; }
has_pcm()   { bluealsa-aplay -L 2>/dev/null | grep -q "DEV=$1,PROFILE=a2dp"; }

# BlueALSA D-Bus path of the speaker's A2DP playback PCM, e.g.
# /org/bluealsa/hci0/dev_50_1B_6A_8B_16_F2/a2dpsrc/sink
pcm_path() {
    local dev="dev_${1//:/_}"
    bluealsa-cli list-pcms 2>/dev/null | grep "/$dev/" | grep -i a2dp | grep -i sink | head -1
}
# "Running: true" = someone (the robot) is streaming to it right now.
pcm_running() {
    local p; p="$(pcm_path "$1")"; [ -n "$p" ] || return 1
    bluealsa-cli info "$p" 2>/dev/null | grep -qi '^Running: *true'
}
# Rate/channels/format the codec negotiated - the bluealsa PCM plugin takes
# exactly that, so the pulse wav is generated to match (cached per format).
pcm_format() {
    local p info rate ch fmt
    p="$(pcm_path "$1")"
    info="$(bluealsa-cli info "$p" 2>/dev/null)"
    rate=$(echo "$info" | sed -n -E 's/^(Rate|Sampling): *([0-9]+).*/\2/p' | head -1)
    ch=$(echo "$info"   | sed -n -E 's/^Channels: *([0-9]+).*/\1/p' | head -1)
    fmt=$(echo "$info"  | sed -n -E 's/^Format: *([A-Z0-9_]+).*/\1/p' | head -1)
    echo "${rate:-44100} ${ch:-2} ${fmt:-S16_LE}"
}
robot_speaking() {   # streamed answer in flight (cj_voice_cloud publishes this)
    [ -f "$SPEAKING_JSON" ] || return 1
    python3 - "$SPEAKING_JSON" <<'PY' 2>/dev/null
import json, sys, time
d = json.load(open(sys.argv[1]))
fresh = time.time() - d.get("ts", 0) < 600
sys.exit(0 if (fresh and not d.get("done", True)) else 1)
PY
}
pulse_wav() {   # $1=rate $2=channels $3=format -> path
    local rate="$1" ch="$2" fmt="$3" sf="s16" codec="pcm_s16le"
    case "$fmt" in S32*) sf=s32; codec=pcm_s32le;; S24*) sf=s32; codec=pcm_s24le;; U8) sf=u8; codec=pcm_u8;; esac
    local amp; amp=$(python3 -c "print(10**($PEAK_DB/20))")
    local out="$WAV_DIR/bt_keepalive_${rate}_${ch}_${sf}_${TONE_HZ}hz_${PEAK_DB}db.wav"
    if [ ! -s "$out" ]; then
        if [ "$NOISE" != "0" ]; then
            ffmpeg -loglevel error -y \
              -f lavfi -i "aevalsrc=$amp*sin(2*PI*$TONE_HZ*t):s=$rate:d=$DUR_S" \
              -f lavfi -i "anoisesrc=color=white:sample_rate=$rate:duration=$DUR_S:amplitude=$NOISE" \
              -filter_complex "[0:a][1:a]amix=inputs=2:normalize=0,aformat=sample_fmts=$sf,pan=${ch}c|c0=c0$( [ "$ch" -ge 2 ] && printf '|c1=c0')" \
              -ar "$rate" -c:a "$codec" "$out" </dev/null
        else
            ffmpeg -loglevel error -y \
              -f lavfi -i "aevalsrc=$amp*sin(2*PI*$TONE_HZ*t):s=$rate:d=$DUR_S" \
              -af "aformat=sample_fmts=$sf,pan=${ch}c|c0=c0$( [ "$ch" -ge 2 ] && printf '|c1=c0')" \
              -ar "$rate" -c:a "$codec" "$out" </dev/null
        fi
    fi
    echo "$out"
}
send_pulse() {  # $1=mac $2=name -> 0 sent, 2 busy, 1 error
    local mac="$1" name="$2" fmt wav err
    read -r rate ch sfmt <<<"$(pcm_format "$mac")"
    wav="$(pulse_wav "$rate" "$ch" "$sfmt")"
    [ -s "$wav" ] || { echo "bt-keepalive: could not build pulse wav ($rate/$ch/$sfmt)"; return 1; }
    err="$(timeout 15 aplay -q -D "bluealsa:DEV=$mac,PROFILE=a2dp" "$wav" 2>&1)"
    case $? in
        0) return 0;;
        *) if echo "$err" | grep -qi 'busy'; then return 2; fi
           echo "bt-keepalive: pulse to $name failed: ${err:-exit $?}"; return 1;;
    esac
}

declare -A LAST_SENT
usable_now() {
    local entry mac name
    for entry in "${SPEAKERS[@]}"; do
        mac="${entry%%|*}"; name="${entry#*|}"
        connected "$mac" && has_pcm "$mac" && echo "$mac|$name"
    done
}

case "${1:-run}" in
  status)
    for u in $(usable_now); do
        mac="${u%%|*}"; name="${u#*|}"
        r="idle"; pcm_running "$mac" && r="STREAMING"
        echo "$name $mac: usable, pcm $r, format $(pcm_format "$mac"), pulse every ${INTERVAL_S}s"
    done
    [ -n "$(usable_now)" ] || echo "no usable Bluetooth speaker connected"
    robot_speaking && echo "robot is speaking" || echo "robot idle"
    exit 0;;
  test)
    n=0
    for u in $(usable_now); do
        mac="${u%%|*}"; name="${u#*|}"; n=$((n+1))
        send_pulse "$mac" "$name"; rc=$?
        case $rc in 0) echo "bt-keepalive: pulse sent to $name ($mac) OK";;
                    2) echo "bt-keepalive: $name busy (something is streaming to it)";; esac
    done
    [ $n = 0 ] && echo "bt-keepalive: no usable Bluetooth speaker connected"
    exit 0;;
  run) ;;
  *) echo "usage: $0 [run|test|status]"; exit 2;;
esac

echo "bt-keepalive: start (pulse ${TONE_HZ} Hz @ ${PEAK_DB} dBFS, ${DUR_S}s every ${INTERVAL_S}s; speakers: ${SPEAKERS[*]})"
while true; do
    now=$(date +%s)
    for u in $(usable_now); do
        mac="${u%%|*}"; name="${u#*|}"
        last="${LAST_SENT[$mac]:-0}"
        [ $((now - last)) -ge "$INTERVAL_S" ] || continue
        if robot_speaking || pcm_running "$mac"; then
            LAST_SENT[$mac]=$((now - INTERVAL_S + BUSY_RETRY_S))   # real audio counts; retry soon
            continue
        fi
        send_pulse "$mac" "$name"; rc=$?
        case $rc in
            0) LAST_SENT[$mac]=$now; [ "${BT_KEEPALIVE_LOG:-0}" = 1 ] && echo "bt-keepalive: pulse -> $name";;
            2) LAST_SENT[$mac]=$((now - INTERVAL_S + BUSY_RETRY_S));;
            *) LAST_SENT[$mac]=$((now - INTERVAL_S + 60));;
        esac
    done
    sleep "$POLL_S"
done
