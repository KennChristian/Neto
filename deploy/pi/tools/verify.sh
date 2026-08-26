#!/bin/bash
# verify.sh — end-to-end health check for a (newly set up) Reachy Mini running
# the CJAP stack. Prints PASS/FAIL per item; exit code = number of failures.
M="$HOME/Supervaise-Reachy-Mini-Project-main"; VPY="$M/app/.venv/bin/python"
fail=0
ok()   { printf '  \033[32mPASS\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$*"; fail=$((fail+1)); }
chk()  { local name="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$name"; else bad "$name"; fi; }
echo "== services  (verify.sh: 25 checks)"
for s in reachy-mini-daemon supervaise pi-dashboard; do chk "$s active" systemctl is-active --quiet $s; done
chk "supervaise enabled at boot" systemctl is-enabled --quiet supervaise
chk "user session lingers (PipeWire at boot)" test -f "/var/lib/systemd/linger/$(id -un)"
echo "== files"
chk "app/.env has all 3 API keys" bash -c "grep -qE '^ANTHROPIC_API_KEY=.{20,}' '$M/app/.env' && grep -qE '^OPENAI_API_KEY=.{20,}' '$M/app/.env' && grep -qE '^ELEVEN_API_KEY=.{20,}' '$M/app/.env'"
chk "wake model hi_see_jap.onnx" test -s "$M/app/wake/models/hi_see_jap.onnx"
chk "speaker-ID model" test -s "$HOME/speaker_id/3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx"
chk "filler clips (40)" bash -c "[ \$(ls $HOME/fillers/*.wav 2>/dev/null | wc -l) -ge 40 ]"
chk "offline notice clip" test -s "$HOME/fillers_bail/not_connected.wav"
chk "dashboard TLS cert" test -s "$HOME/pi_dashboard/certs/key.pem"
chk "PipeWire quantum fix installed" test -s "$HOME/.config/pipewire/pipewire.conf.d/90-reachy-quantum.conf"
chk "user@ realtime drop-in installed" test -s /etc/systemd/system/user@.service.d/99-reachy-rtprio.conf
echo "== audio hardware"
chk "XMOS mic array present (USB audio card)" bash -c "arecord -l | grep -qiE 'reachy|respeaker|xmos|usb'"
chk "ALSA route reachymini_audio_src_plug defined" bash -c "arecord -L | grep -q reachymini_audio_src_plug"
# 2026-08-26: reachy-mini-daemon rewrites ~/.asoundrc with a raw-hw config when the USB
# card index it detects is not literally listed in the file -> "Channels count non
# available" on every answer + barge-in mic unavailable. Our file addresses the card
# by name and lists "card 0..4" in a comment so the daemon check passes at any index.
chk ".asoundrc is ours (card by name, not daemon-clobbered)" bash -c "grep -q 'hw:CARD=Audio' '$HOME/.asoundrc' && grep -q 'audio_out_route' '$HOME/.asoundrc' && grep -q 'card 0 card 1 card 2' '$HOME/.asoundrc'"
chk "XMOS firmware >= 2.1.0 (DoA)" bash -c "timeout 20 /venvs/mini_daemon/bin/python /venvs/mini_daemon/lib/python3.12/site-packages/reachy_mini/media/audio_control_utils.py VERSION | $VPY -c 'import sys,re; m=re.search(r\"VERSION: \\[(\\d+), (\\d+), (\\d+), (\\d+)\\]\", sys.stdin.read()); v=[int(x) for x in m.groups()] if m else None; sys.exit(0 if v and v[1:3] >= [2,1] else 1)'"
chk "direction-of-arrival readable" bash -c "timeout 30 $VPY -c 'from reachy_mini.media.audio_doa import AudioDoA; d=AudioDoA(); r=d.get_DoA(); d.close(); assert r is not None' 2>/dev/null"
echo "== python env"
chk "venv imports (app modules)" bash -c "cd $M/app && timeout 120 $VPY -c 'import voice_io, lang_gate, usage_meter, canned_answers, stream_speak'"
echo "== network / providers"
chk "dashboard answers on :8080" bash -c "curl -sf -o /dev/null http://127.0.0.1:8080/"
P=$(curl -sf -m 40 http://127.0.0.1:8080/api/providers 2>/dev/null)
for p in claude elevenlabs openai; do
  if echo "$P" | "$VPY" -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('$p',{}).get('ok') else 1)" 2>/dev/null; then ok "$p API reachable with this key"; else bad "$p API (key or network)"; fi
done
echo "== robot"
chk "journal: wake model resident this boot" bash -c "journalctl -u supervaise -b --no-pager | grep -q 'openWakeWord model resident'"
chk "journal: motors connected this boot" bash -c "journalctl -u supervaise -b --no-pager | grep -q 'motors on'"
echo
if [ $fail = 0 ]; then echo "ALL CHECKS PASSED — say \"Hi Cee-Jap\" to the robot."; else echo "$fail check(s) failed"; fi
exit $fail
