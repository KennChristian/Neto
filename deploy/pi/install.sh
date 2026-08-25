#!/bin/bash
# install.sh — bring a FRESH Reachy Mini (Pi CM4, Debian 13, user "pollen")
# up to the same deployed state as the reference robot, from this repo alone.
#
#   git clone -b pi/deployment-snapshots https://github.com/Supervaise-Inc/CJAP.git \
#       ~/Supervaise-Reachy-Mini-Project-main
#   cd ~/Supervaise-Reachy-Mini-Project-main && bash deploy/pi/install.sh
#   nano app/.env            # paste the three API keys (see app/.env.example)
#   sudo systemctl restart supervaise
#
# Idempotent: safe to re-run after a `git pull` to pick up code + unit changes.
# What it does (in order):
#   1. apt packages the app shells out to (ffmpeg, aplay, portaudio, openssl)
#   2. app/.venv from deploy/pi/requirements-pi.txt (exact live pins)
#   3. openWakeWord shared feature models + faster-whisper tiny (STT fallback)
#   4. speaker-ID model (~26 MB from the sherpa-onnx release page)
#   5. audio clip pools -> ~/fillers, ~/fillers_ack, ~/fillers_bail, ~/demo_clips
#   6. dotfiles: ~/.asoundrc(.route), ~/bin/audio-out, ~/speaker-watchdog.sh,
#      ~/bin/{verify,export-private,import-private,snapshot-push}.sh
#   6b. PipeWire realtime + quantum tuning (the 2026-07-21 choppy-audio fix):
#      ~/.config/pipewire/*.conf.d, ~/.config/systemd/user/*.service.d/rt.conf,
#      /etc/systemd/system/user@.service.d/99-reachy-rtprio.conf
#   7. ~/pi_dashboard (web UI on :8080/:8443) + self-signed cert
#   8. systemd units (paths rewritten to this $HOME/$USER) + enable + linger
#   9. ReachySetup WiFi hotspot profile (fallback when no known WiFi)
#  10. app/.env + voice/config.py from templates if missing
#
# NOT done here (needs secrets / the reference robot's data):
#   - API keys: fill app/.env (ANTHROPIC, OPENAI, ELEVEN). Nothing speaks without them.
#   - Cached ElevenLabs clips (~/.voice_cache, 300 MB) — regenerate the canned
#     answers with `app/.venv/bin/python scripts/prerender_canned.py` once keys
#     are in; everything else caches itself on first use.
#   - Bluetooth speaker pairing (audio-out sony|marshall are MAC-specific).
#   - Speaker enrollment for voice lock (dashboard "Enroll" button).

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DP="$REPO/deploy/pi"
ME="$(id -un)"
UID_="$(id -u)"
PY=/usr/bin/python3

log() { printf '\n\033[1;36m== %s\033[0m\n' "$*"; }

if [ "$REPO" != "$HOME/Supervaise-Reachy-Mini-Project-main" ]; then
  echo "WARNING: repo is at $REPO; the units and PROJECT_NOTES assume"
  echo "         $HOME/Supervaise-Reachy-Mini-Project-main. Units are rewritten"
  echo "         to this path, but the dashboard's restart/log helpers expect the default."
fi

# ---------------------------------------------------------------- 1. apt
log "apt packages"
sudo apt-get update -qq || true
# build deps: pycairo/PyGObject in requirements-pi.txt have no aarch64 wheel
# and are compiled from sdist by pip (--no-deps)
sudo apt-get install -y --no-install-recommends \
  ffmpeg alsa-utils python3-venv python3-dev gcc pkg-config libcairo2-dev \
  libgirepository1.0-dev portaudio19-dev libportaudio2 libsndfile1 \
  openssl curl network-manager rpicam-apps-lite >/dev/null
# bluez-alsa-utils (BlueALSA) ships enabled on the Reachy Mini image; only
# needed for Bluetooth speakers.
sudo apt-get install -y --no-install-recommends bluez-alsa-utils >/dev/null || true

# ---------------------------------------------------------------- 2. venv
log "python venv -> $REPO/app/.venv"
if [ ! -x "$REPO/app/.venv/bin/python" ]; then
  $PY -m venv "$REPO/app/.venv"
fi
VPY="$REPO/app/.venv/bin/python"
"$VPY" -m pip install -q --upgrade pip wheel
# Exact pins, no resolver: the freeze is a complete closure, and openwakeword's
# declared tflite-runtime dep has no cp313 wheel (we use its onnx path).
"$VPY" -m pip install -q --no-deps -r "$DP/requirements-pi.txt"

# ---------------------------------------------------------------- 3. models
log "openWakeWord feature models + faster-whisper tiny"
"$VPY" - <<'EOF'
import openwakeword.utils as u
u.download_models()          # melspectrogram.onnx + embedding_model.onnx (+ stock demos)
print("openwakeword resources ok")
EOF
"$VPY" - <<'EOF' || echo "faster-whisper tiny prefetch skipped (fallback STT only)"
from faster_whisper import WhisperModel
WhisperModel("tiny", device="cpu", compute_type="int8")
print("faster-whisper tiny cached")
EOF

# ---------------------------------------------------------------- 4. speaker-ID
log "speaker-ID model -> ~/speaker_id"
mkdir -p "$HOME/speaker_id"
SPK=3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx
if [ ! -s "$HOME/speaker_id/$SPK" ]; then
  curl -L --fail -o "$HOME/speaker_id/$SPK" \
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/$SPK"
fi

# ---------------------------------------------------------------- 5. audio
log "audio clip pools -> ~/"
for d in fillers fillers_ack fillers_bail demo_clips; do
  mkdir -p "$HOME/$d"
  cp -n "$DP/audio/$d/"* "$HOME/$d/"
done

# ---------------------------------------------------------------- 6. dotfiles
log "dotfiles"
mkdir -p "$HOME/bin"
sed "s#/home/pollen#$HOME#g" "$DP/dotfiles/.asoundrc" > "$HOME/.asoundrc"
[ -f "$HOME/.asoundrc.route" ] || cp "$DP/dotfiles/.asoundrc.route" "$HOME/.asoundrc.route"
sed "s#/home/pollen#$HOME#g" "$DP/dotfiles/bin/audio-out" > "$HOME/bin/audio-out"
# robot-specific speaker MACs: keep them in ~/bin/audio-out.local (sourced
# by audio-out if present) so a re-run never clobbers them
sed "s#/home/pollen#$HOME#g" "$DP/dotfiles/speaker-watchdog.sh" > "$HOME/speaker-watchdog.sh"
chmod +x "$HOME/bin/audio-out" "$HOME/speaker-watchdog.sh"
for t in verify.sh export-private.sh import-private.sh snapshot-push.sh; do
  [ -f "$DP/tools/$t" ] && install -m 755 "$DP/tools/$t" "$HOME/bin/$t"
done
sudo usermod -aG audio,plugdev,dialout,video "$ME" 2>/dev/null || true

# ---------------------------------------------------------------- 6b. PipeWire tuning
log "PipeWire realtime + quantum tuning (choppy-audio fix)"
mkdir -p "$HOME/.config/pipewire/pipewire.conf.d" "$HOME/.config/pipewire/pipewire-pulse.conf.d"
cp "$DP/dotfiles/config/pipewire/pipewire.conf.d/"*.conf "$HOME/.config/pipewire/pipewire.conf.d/"
cp "$DP/dotfiles/config/pipewire/pipewire-pulse.conf.d/"*.conf "$HOME/.config/pipewire/pipewire-pulse.conf.d/"
for u in pipewire pipewire-pulse wireplumber filter-chain; do
  mkdir -p "$HOME/.config/systemd/user/$u.service.d"
  cp "$DP/dotfiles/config/systemd/user/$u.service.d/rt.conf" "$HOME/.config/systemd/user/$u.service.d/rt.conf"
done
sudo mkdir -p /etc/systemd/system/user@.service.d
sudo install -m 644 "$DP/systemd/user@.service.d/99-reachy-rtprio.conf"   /etc/systemd/system/user@.service.d/99-reachy-rtprio.conf
# the user@ limits only apply to a NEW user session -> reboot at the end

# ---------------------------------------------------------------- 7. dashboard
log "pi_dashboard"
mkdir -p "$HOME/pi_dashboard/certs" "$HOME/pi_dashboard/assets"
cp "$DP/dashboard/dashboard.py" "$DP/dashboard/supervaise_ui.py" \
   "$DP/dashboard/say_text_helper.py" "$DP/dashboard/wifi_fallback.sh" \
   "$HOME/pi_dashboard/"
chmod +x "$HOME/pi_dashboard/wifi_fallback.sh"
if [ ! -s "$HOME/pi_dashboard/certs/key.pem" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -subj "/CN=reachy-mini.local" \
    -keyout "$HOME/pi_dashboard/certs/key.pem" \
    -out "$HOME/pi_dashboard/certs/cert.pem" 2>/dev/null
  chmod 600 "$HOME/pi_dashboard/certs/key.pem"
fi

# ---------------------------------------------------------------- 8. systemd
log "systemd units"
tmp="$(mktemp -d)"
for u in supervaise.service pi-dashboard.service wifi-fallback.service speaker-watchdog.service; do
  sed -e "s#/home/pollen#$HOME#g" -e "s#^User=pollen#User=$ME#" \
      -e "s#^Group=pollen#Group=$ME#" -e "s#/run/user/1000#/run/user/$UID_#g" \
      "$DP/systemd/$u" > "$tmp/$u"
  sudo install -m 644 "$tmp/$u" "/etc/systemd/system/$u"
done
sudo mkdir -p /etc/systemd/system/supervaise.service.d
sudo install -m 644 "$DP/systemd/supervaise.service.d/wakeword.conf" \
  /etc/systemd/system/supervaise.service.d/wakeword.conf
rm -rf "$tmp"
sudo loginctl enable-linger "$ME"          # PipeWire user session up at boot
sudo systemctl daemon-reload
sudo systemctl enable supervaise pi-dashboard wifi-fallback >/dev/null
# speaker-watchdog is tied to one Sony speaker's MAC — install but leave it
# to the operator:  sudo systemctl enable --now speaker-watchdog
sudo systemctl disable speaker-watchdog >/dev/null 2>&1 || true

# ---------------------------------------------------------------- 9. hotspot profile
log "ReachySetup hotspot profile (autoconnect off; wifi_fallback.sh raises it)"
if ! nmcli -t -f NAME con show | grep -qx ReachySetup; then
  sudo nmcli con add type wifi ifname wlan0 con-name ReachySetup autoconnect no \
    ssid ReachyMini-Setup 802-11-wireless.mode ap 802-11-wireless.band bg \
    ipv4.method shared wifi-sec.key-mgmt wpa-psk wifi-sec.psk reachymini >/dev/null
fi

# ---------------------------------------------------------------- 10. secrets templates
log "config templates"
[ -f "$REPO/app/.env" ]        || cp "$REPO/app/.env.example" "$REPO/app/.env"
[ -f "$REPO/voice/config.py" ] || cp "$REPO/voice/config.example.py" "$REPO/voice/config.py"

echo
echo "================================================================"
echo " Install complete."
if grep -qE '^(ANTHROPIC|OPENAI|ELEVEN)_API_KEY=(sk-ant-\.\.\.|sk-\.\.\.|)$' "$REPO/app/.env"; then
  echo " >> Fill in the API keys in $REPO/app/.env, then:"
else
  echo " >> Keys look set. Start the robot with:"
fi
echo "      sudo reboot        # once, so the PipeWire realtime limits apply"
echo "      # then http://$(hostname).local:8080  (maintain page: /maintain?key=cjap)"
echo " >> Moving from another robot? restore its secrets bundle first:"
echo "      ~/bin/import-private.sh ~/private-<host>-<ts>.tar.gz.enc --restart   (see deploy/pi/TRANSFER.md)"
echo " >> Check everything:  ~/bin/verify.sh   (~/bin joins PATH at next login)"
echo " >> Robot-specific tuning goes in /etc/systemd/system/supervaise.service.d/local.conf"
echo "    (e.g. Environment=CJ_DOA_FLIP=1) — install.sh only ever rewrites wakeword.conf"
echo " >> Pre-warm the canned answers (ElevenLabs credits, ~150 clips):"
echo "      cd $REPO && app/.venv/bin/python scripts/prerender_canned.py"
echo "================================================================"
