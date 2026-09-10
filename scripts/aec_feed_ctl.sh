#!/bin/bash
# aec_feed_ctl.sh — bring up the XVF3800 AEC reference feed reversibly.
#
# Why this exists: on a Bluetooth route the robot's playback never enters the
# XVF3800, so the chip's echo canceller has no far-end reference and the robot
# hears its own voice as ambient noise. _RefFeed (main_voice_robot.py:1240)
# fixes that by mirroring playback into the chip over USB — but it needs a
# calibrated CJ_AEC_REF_DELAY_MS, and it was left OFF on 2026-09-02 precisely
# because that delay was never measured.
#
# Every command that changes anything takes a snapshot first. `restore` puts
# the chip, the systemd drop-in, the feed flag and the volume back.
#
#   ./scripts/aec_feed_ctl.sh status
#   ./scripts/aec_feed_ctl.sh snapshot [tag]
#   ./scripts/aec_feed_ctl.sh reconcile
#   ./scripts/aec_feed_ctl.sh calibrate
#   ./scripts/aec_feed_ctl.sh enable <delay_ms>
#   ./scripts/aec_feed_ctl.sh disable
#   ./scripts/aec_feed_ctl.sh verify [seconds]
#   ./scripts/aec_feed_ctl.sh list
#   ./scripts/aec_feed_ctl.sh restore <snapshot-dir>
set -uo pipefail
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/1000}"

REPO="/home/pollen/Supervaise-Reachy-Mini-Project-main"
XVF="$HOME/bin/xvf-ctl"
VOL="$HOME/bin/audio-volume"
OUT="$HOME/bin/audio-out"
CALIB="$HOME/tools/aec_ref_calib.py"
SNAP="$REPO/scripts/xvf_snapshot.py"
DROPIN="/etc/systemd/system/supervaise.service.d/wakeword.conf"
ROUTE="$HOME/.asoundrc.route"
FEED_FLAG="$HOME/.cj_ref_feed_on"
SNAPDIR="$REPO/docs/audio/snapshots"
SVC="supervaise.service"

die()  { echo "error: $*" >&2; exit 1; }
note() { echo "  $*"; }
hdr()  { echo; echo "== $*"; }

sink_name() { pactl list sinks short 2>/dev/null | awk '/Reachy_Mini_Audio/ {print $2; exit}'; }
sink_mute() { pactl get-sink-mute "$(sink_name)" 2>/dev/null | awk '{print $2}'; }

# The reference feed writes into the XMOS PipeWire sink. A MUTED sink swallows
# it silently: the chip gets no reference, the AEC never converges, and
# aec_ref_calib.py measures no lag_ref either ("not enough clean
# measurements"). Nothing in audio-volume, audio-out or the app ever unmutes
# this sink, so it stays muted across reboots until something clears it —
# which is the most likely reason the 2026-09-01 attempt was parked.
require_unmuted() {
    [ "$(sink_mute)" = "no" ] && return 0
    note "XMOS sink is MUTED — unmuting (the feed writes into it)"
    pactl set-sink-mute "$(sink_name)" 0 2>/dev/null || die "could not unmute the XMOS sink"
    [ "$(sink_mute)" = "no" ] || die "XMOS sink still muted after unmute"
    note "XMOS sink unmuted"
}

# ── snapshot ────────────────────────────────────────────────────────────────
do_snapshot() {
    local tag="${1:-manual}" dir
    dir="$SNAPDIR/$(date +%Y%m%d-%H%M%S)-$tag"
    mkdir -p "$dir" || die "cannot create $dir"

    "$SNAP" save "$dir/chip.json" >/dev/null || echo "  ! chip snapshot failed" >&2
    cp "$DROPIN" "$dir/wakeword.conf" 2>/dev/null || echo "  ! drop-in copy failed" >&2
    cp "$ROUTE"  "$dir/asoundrc.route" 2>/dev/null || true

    local flag=absent; [ -f "$FEED_FLAG" ] && flag=present
    cat > "$dir/state.json" <<EOF
{
  "taken":      "$(date -Is)",
  "tag":        "$tag",
  "feed_flag":  "$flag",
  "cj_volume":  "$(cat "$HOME/.cj_volume" 2>/dev/null || echo unset)",
  "sink_mute":  "$(sink_mute)",
  "alsa_pcm":   "$(amixer -c Audio sget PCM 2>/dev/null | grep -m1 'Front Left:' | tr -s ' ')",
  "service":    "$(systemctl is-active $SVC 2>/dev/null)"
}
EOF
    echo "$dir"
}

# ── status ──────────────────────────────────────────────────────────────────
cmd_status() {
    hdr "route (authoritative for new playback streams)"
    "$OUT" status 2>/dev/null | sed -n '2,3p'
    note "route file target: $(grep -m1 '^# Route:' "$ROUTE" 2>/dev/null || echo unknown)"

    hdr "connected A2DP sinks"
    # More than one speaker can be connected at once (speaker-watchdog keeps the
    # Sony up while the route may point elsewhere). Only the route target above
    # actually receives audio — and the AEC delay is per-speaker, so calibrating
    # against the wrong one produces a mistimed reference.
    local target; target=$(grep -m1 '^# Primary:' "$ROUTE" 2>/dev/null | awk '{print $3}')
    bluealsa-cli list-pcms 2>/dev/null | grep -o 'dev_[0-9A-F_]*' | sort -u | while read -r d; do
        mac=$(echo "${d#dev_}" | tr '_' ':')
        name=$(bluetoothctl info "$mac" 2>/dev/null | awk -F': ' '/Name:/{print $2; exit}')
        if [ "$mac" = "$target" ]; then note "$mac  ${name:-?}   <- ROUTE TARGET"
        else                          note "$mac  ${name:-?}   (connected, idle)"; fi
    done

    hdr "chip AEC state"
    "$XVF" read AEC_AECCONVERGED AEC_RT60 AUDIO_MGR_REF_GAIN AEC_FAR_EXTGAIN \
                AUDIO_MGR_SYS_DELAY AUDIO_MGR_OP_R 2>/dev/null | tail -1

    hdr "drop-in env"
    grep -E '^Environment=CJ_AEC' "$DROPIN" 2>/dev/null | sed 's/^/  /' || note "(none)"

    hdr "feed flag / speaker attenuation"
    if [ -f "$FEED_FLAG" ]; then note "$FEED_FLAG PRESENT ($(date -r "$FEED_FLAG" -Is))"; else note "$FEED_FLAG absent"; fi
    note "XMOS sink: $(amixer -c Audio sget PCM 2>/dev/null | grep -m1 'Front Left:' | tr -s ' ')"
    if [ "$(sink_mute)" = "yes" ]; then
        echo "  ⚠ XMOS sink is MUTED — the reference feed and the calibration"
        echo "    both write into this sink; muted means neither can work."
    else
        note "XMOS sink unmuted (the feed can reach the chip)"
    fi

    hdr "consistency"
    local want_on=0 flag_on=0
    grep -qE '^Environment=CJ_AEC_REF_FEED=(1|true|yes|on)' "$DROPIN" 2>/dev/null && want_on=1
    [ -f "$FEED_FLAG" ] && flag_on=1
    # _RefFeed.sync() runs only from the playback paths (main_voice_robot.py
    # 1573 / 2161 / 2227), so with feed=1 the chip is NOT configured until CJ
    # speaks for the first time after a restart. That is by design — the feed
    # follows the route lazily — so "wants on, not yet engaged" is a normal
    # state, not a mismatch. Only the reverse (attenuated for a feed that will
    # never run) is the stale condition reconcile exists to fix.
    if [ "$want_on" = 1 ] && [ "$flag_on" = 0 ]; then
        echo "  ⏳ feed ENABLED but not yet engaged — _RefFeed.sync() fires on the"
        echo "     first playback after a restart. Ask CJ something, then: $0 verify"
    elif [ "$want_on" = 0 ] && [ "$flag_on" = 1 ]; then
        echo "  ⚠ STALE: drop-in feed=0 but the feed flag is present."
        echo "    the speaker is attenuated for a feed that never runs."
        echo "    fix with: $0 reconcile"
    else
        note "drop-in and feed flag agree (feed=$want_on)"
    fi
}

# ── reconcile ───────────────────────────────────────────────────────────────
cmd_reconcile() {
    do_snapshot reconcile >/dev/null
    if grep -qE '^Environment=CJ_AEC_REF_FEED=(1|true|yes|on)' "$DROPIN" 2>/dev/null; then
        note "drop-in wants the feed ON -> audio-volume feed-on"
        "$VOL" feed-on
    else
        note "drop-in wants the feed OFF -> audio-volume feed-off (restores speaker level)"
        "$VOL" feed-off
        "$XVF" write AUDIO_MGR_REF_GAIN 8 >/dev/null && note "AUDIO_MGR_REF_GAIN -> 8 (feed-off value)"
    fi
    cmd_status
}

# ── calibrate ───────────────────────────────────────────────────────────────
cmd_calibrate() {
    [ -x "$CALIB" ] || die "$CALIB not found or not executable"
    grep -q "type bluealsa" "$ROUTE" 2>/dev/null || \
        die "route is not Bluetooth — the feed is only needed on a BT route"

    echo "Calibration plays audible chirps through the speaker in use."
    echo "Route target: $(grep -m1 '^# Route:' "$ROUTE" | sed 's/^# Route: //')"
    echo "It needs the mic exclusively, so $SVC will be STOPPED and restarted."
    echo "Make sure the /maintain mic meter is closed."
    read -r -p "Proceed? [y/N] " ok
    [ "$ok" = "y" ] || { echo "aborted"; return 1; }

    local was; was=$(systemctl is-active "$SVC")
    do_snapshot calibrate >/dev/null
    require_unmuted
    [ "$was" = "active" ] && { note "stopping $SVC"; sudo systemctl stop "$SVC"; sleep 2; }

    "$CALIB" --repeats 3 --margin-ms 80
    local rc=$?

    if [ "$was" = "active" ]; then note "restarting $SVC"; sudo systemctl start "$SVC"; fi
    [ $rc -eq 0 ] || die "calibration failed (rc=$rc) — is the speaker on and playing?"
    echo
    echo "Take the CJ_AEC_REF_DELAY_MS printed above and run:"
    echo "    $0 enable <delay_ms>"
}

# ── enable / disable ────────────────────────────────────────────────────────
set_env() {   # $1 = feed value, $2 = delay (only used when enabling)
    local feed="$1" delay="${2:-}" bak
    bak="$DROPIN.bak-aecfeed-$(date +%Y%m%d-%H%M%S)"
    sudo cp "$DROPIN" "$bak" || die "drop-in backup failed"
    note "drop-in backed up -> $bak"
    sudo sed -i "s/^Environment=CJ_AEC_REF_FEED=.*/Environment=CJ_AEC_REF_FEED=$feed/" "$DROPIN"
    [ -n "$delay" ] && sudo sed -i "s/^Environment=CJ_AEC_REF_DELAY_MS=.*/Environment=CJ_AEC_REF_DELAY_MS=$delay/" "$DROPIN"
    grep -E '^Environment=CJ_AEC' "$DROPIN" | sed 's/^/  /'
    sudo systemctl daemon-reload
    sudo systemctl restart "$SVC"
    note "$SVC restarted"
}

cmd_enable() {
    local delay="${1:-}"
    [ -n "$delay" ] || die "usage: $0 enable <delay_ms>   (run 'calibrate' first)"
    [[ "$delay" =~ ^[0-9]+$ ]] || die "delay must be an integer number of milliseconds"
    grep -q "type bluealsa" "$ROUTE" 2>/dev/null || \
        die "route is not Bluetooth — _RefFeed.wanted() would stay false anyway"
    do_snapshot enable >/dev/null
    require_unmuted
    set_env 1 "$delay"
    echo
    echo "Now play an answer and run:  $0 verify"
}

cmd_disable() {
    do_snapshot disable >/dev/null
    set_env 0
    "$VOL" feed-off >/dev/null 2>&1 && note "speaker level restored"
    "$XVF" write AUDIO_MGR_REF_GAIN 8 >/dev/null 2>&1 && note "AUDIO_MGR_REF_GAIN -> 8"
}

# ── verify ──────────────────────────────────────────────────────────────────
cmd_verify() {
    local secs="${1:-120}"
    # Convergence took ~90 s of CUMULATIVE far-end audio on 2026-09-02 — it did
    # not assert during the first or second answer. A short window reports a
    # false negative, so the default is 120 s and the hint says to keep talking.
    echo "Sampling the chip for ${secs}s. AEC_AECCONVERGED only rises while"
    echo "far-end audio plays, and needed ~90s of cumulative playback to lock."
    echo "Keep CJ talking for the whole window — one short answer is not enough."
    echo
    printf "%-9s %-11s %-10s %-10s\n" "t" "CONVERGED" "RT60" "REF_GAIN"
    local i=0
    while [ $i -lt "$secs" ]; do
        local j c r g
        j=$("$XVF" read AEC_AECCONVERGED AEC_RT60 AUDIO_MGR_REF_GAIN 2>/dev/null | tail -1)
        # parse with python, not grep: the values are inside "NAME": [v] and an
        # anchored regex fails against the trailing ']' (that bug printed "?" for
        # every CONVERGED sample on the first verify run).
        read -r c r g <<<"$(printf '%s' "$j" | python3 -c '
import json,sys
d=json.load(sys.stdin)
f=lambda k: (d.get(k) or ["?"])[0]
print(f("AEC_AECCONVERGED"), f("AEC_RT60"), f("AUDIO_MGR_REF_GAIN"))' 2>/dev/null)"
        printf "%-9s %-11s %-10s %-10s\n" "${i}s" "${c:-?}" "${r:-?}" "${g:-?}"
        [ "$c" = "1" ] && { echo; echo "  ✅ AEC CONVERGED — the chip has a usable reference."; return 0; }
        i=$((i + 1))
    done
    echo
    echo "  ❌ never converged in ${secs}s."
    echo "     Check: was audio actually playing? is REF_GAIN 1000 (not 8)?"
    echo "     is the delay calibrated for THIS speaker? ($0 calibrate)"
    return 1
}

# ── list / restore ──────────────────────────────────────────────────────────
cmd_list() {
    [ -d "$SNAPDIR" ] || { echo "no snapshots yet"; return 0; }
    for d in "$SNAPDIR"/*/; do
        [ -d "$d" ] || continue
        echo "$(basename "$d")  $(grep -o '"feed_flag": *"[a-z]*"' "$d/state.json" 2>/dev/null)"
    done
}

cmd_restore() {
    local dir="${1:-}"
    [ -n "$dir" ] || die "usage: $0 restore <snapshot-dir>   (see: $0 list)"
    [ -d "$dir" ] || dir="$SNAPDIR/$dir"
    [ -d "$dir" ] || die "no such snapshot: $1"

    hdr "restoring from $dir"

    if [ -f "$dir/chip.json" ]; then
        "$SNAP" restore "$dir/chip.json"
    else
        note "! no chip.json in snapshot"
    fi

    if [ -f "$dir/wakeword.conf" ]; then
        sudo cp "$DROPIN" "$DROPIN.bak-prerestore-$(date +%Y%m%d-%H%M%S)"
        sudo cp "$dir/wakeword.conf" "$DROPIN"
        sudo systemctl daemon-reload
        sudo systemctl restart "$SVC"
        note "drop-in restored, $SVC restarted"
    fi

    local mute; mute=$(grep -o '"sink_mute": *"[a-z]*"' "$dir/state.json" 2>/dev/null | grep -o '[a-z]*"$' | tr -d '"')
    if [ -n "$mute" ] && [ "$mute" != "$(sink_mute)" ]; then
        pactl set-sink-mute "$(sink_name)" "$([ "$mute" = yes ] && echo 1 || echo 0)" 2>/dev/null
        note "XMOS sink mute restored: $mute"
    fi

    local flag; flag=$(grep -o '"feed_flag": *"[a-z]*"' "$dir/state.json" 2>/dev/null | grep -o '[a-z]*"$' | tr -d '"')
    if [ "$flag" = "present" ]; then "$VOL" feed-on >/dev/null; note "feed flag restored: present"
    else "$VOL" feed-off >/dev/null; note "feed flag restored: absent"; fi

    cmd_status
}

case "${1:-}" in
    status)    cmd_status ;;
    snapshot)  do_snapshot "${2:-manual}" ;;
    reconcile) cmd_reconcile ;;
    calibrate) cmd_calibrate ;;
    enable)    cmd_enable "${2:-}" ;;
    disable)   cmd_disable ;;
    verify)    cmd_verify "${2:-120}" ;;
    list)      cmd_list ;;
    restore)   cmd_restore "${2:-}" ;;
    *) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
