#!/bin/bash
# snapshot-push.sh — capture the live Pi system into git and push it
# to github.com/KennChristian/Neto with a timestamped branch.
#
#   snapshot-push.sh   → commit on pi/deployment-snapshots
#                        + branch snapshot/YYYY-MM-DD-HHMM
#                        + push both to remote "neto"
#
# Every snapshot branch is a permanent restore point: to see what the
# system looked like at a given time, `git checkout snapshot/<ts>`
# (or browse the branch on GitHub). The mainline branch
# pi/deployment-snapshots always points at the newest snapshot.
#
# NEVER synced (secrets / large data): app/.env, voice/config.py, certs/,
# pi_dashboard/assets (HeyGen key), ~/.voice_cache, speaker embeddings.
# Clip pools (~/fillers*, ~/demo_clips) ARE synced to deploy/pi/audio/.

set -euo pipefail
W="$HOME/gitwork/pi-main"
M="$HOME/Supervaise-Reachy-Mini-Project-main"
D="$HOME/pi_dashboard"

cd "$W"

# 1. refresh every already-tracked repo file from the live checkout
git ls-files | grep -E '^(app|corpus|data|scripts|tests|voice)/|^config\.py$' \
  | while read -r f; do
      [ -f "$M/$f" ] && cp "$M/$f" "$f"
    done || true

# 2. pick up NEW live files in the code/data dirs (never .env/keys/wavs)
for pat in "app/*.py" "app/*.md" "data/entities/*.json" \
           "corpus/voice/*" "scripts/*.py" "tests/*.py" "voice/*.py" \
           "voice/*.md"; do
  for src in $M/$pat; do
    [ -f "$src" ] || continue
    rel="${src#$M/}"
    case "$rel" in voice/config.py) continue;; esac
    mkdir -p "$(dirname "$rel")"
    cp "$src" "$rel"
  done
done

# 3. dashboard, systemd units, dotfiles, notes, home-dir tools
cp "$D"/ui_server.py "$D"/ui_common.py "$D"/ui_routes.py "$D"/ui_page_*.py "$D"/say_text_helper.py \
   "$D"/wifi_fallback.sh "$D"/wifi-fallback.service \
   "$D"/pi-dashboard.service deploy/pi/dashboard/
cp /etc/systemd/system/supervaise.service deploy/pi/systemd/ 2>/dev/null || true
mkdir -p deploy/pi/systemd/supervaise.service.d
cp /etc/systemd/system/supervaise.service.d/wakeword.conf \
   deploy/pi/systemd/supervaise.service.d/
cp "$HOME/.asoundrc" deploy/pi/dotfiles/.asoundrc
cp "$HOME/.asoundrc.route" deploy/pi/dotfiles/.asoundrc.route
cp "$HOME/bin/audio-out" deploy/pi/dotfiles/bin/audio-out
cp "$HOME/speaker-watchdog.sh" deploy/pi/dotfiles/speaker-watchdog.sh
cp "$HOME/PROJECT_NOTES.txt" deploy/pi/PROJECT_NOTES.txt 2>/dev/null || true
mkdir -p deploy/pi/tools
for t in gen_voice_wavs_eleven.py gen_voice_wavs_accent.py \
         snapshot-push.sh verify.sh export-private.sh import-private.sh; do
  src="$HOME/$t"; [ -f "$HOME/bin/$t" ] && src="$HOME/bin/$t"
  [ -f "$src" ] && cp "$src" "deploy/pi/tools/$t" || true
done

# 3a. PipeWire realtime/quantum tuning (choppy-audio fix 2026-07-21) — user
#     configs + the system user@ drop-in; install.sh step 6b replays them.
mkdir -p deploy/pi/dotfiles/config/pipewire/pipewire.conf.d \
         deploy/pi/dotfiles/config/pipewire/pipewire-pulse.conf.d \
         deploy/pi/systemd/user@.service.d
cp "$HOME"/.config/pipewire/pipewire.conf.d/*.conf deploy/pi/dotfiles/config/pipewire/pipewire.conf.d/ 2>/dev/null || true
cp "$HOME"/.config/pipewire/pipewire-pulse.conf.d/*.conf deploy/pi/dotfiles/config/pipewire/pipewire-pulse.conf.d/ 2>/dev/null || true
for u in pipewire pipewire-pulse wireplumber filter-chain; do
  mkdir -p "deploy/pi/dotfiles/config/systemd/user/$u.service.d"
  cp "$HOME/.config/systemd/user/$u.service.d/rt.conf" "deploy/pi/dotfiles/config/systemd/user/$u.service.d/" 2>/dev/null || true
done
cp /etc/systemd/system/user@.service.d/99-reachy-rtprio.conf deploy/pi/systemd/user@.service.d/ 2>/dev/null || true

# 3b. fresh-robot bundle (deploy/pi/README.md + install.sh consume these):
#     audio clip pools (~13 MB, no secrets) + exact venv pins.
for d in fillers fillers_ack fillers_bail demo_clips; do
  mkdir -p "deploy/pi/audio/$d"
  cp "$HOME/$d"/*.wav "deploy/pi/audio/$d/" 2>/dev/null || true
done
{ echo "# Frozen from the live Reachy Mini venv (app/.venv, Python 3.13.5, aarch64) on $(date +%F)."
  echo "# Install with --no-deps (see deploy/pi/install.sh): openwakeword 0.6.0 declares"
  echo "# tflite-runtime, which has no Python 3.13 wheel — we run its onnx path only."
  echo "# pyarrow must stay >= 24 on the Pi 4/CM4 (21.0.0 wheels SIGILL on Cortex-A72)."
  "$M/app/.venv/bin/pip" freeze; } > deploy/pi/requirements-pi.txt

# 4. commit + timestamped branch + push
git add -A
if git diff --cached --quiet; then
  echo "snapshot: no changes since last push — nothing to do"
  exit 0
fi
ts=$(date +%Y-%m-%d-%H%M)
git -c user.name=dev0 -c user.email=dev0@supervaise.io \
    commit -m "pi snapshot $ts"
git branch "snapshot/$ts"
git push neto pi/deployment-snapshots "snapshot/$ts"
echo "snapshot: pushed snapshot/$ts + pi/deployment-snapshots"
