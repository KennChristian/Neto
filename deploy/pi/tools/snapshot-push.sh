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
# NEVER synced (secrets / large audio): app/.env, voice/config.py,
# certs/, *.wav pools, ~/.voice_cache, speaker embeddings.

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
cp "$D"/dashboard.py "$D"/supervaise_ui.py "$D"/say_text_helper.py \
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
         snapshot-push.sh; do
  src="$HOME/$t"; [ -f "$HOME/bin/$t" ] && src="$HOME/bin/$t"
  [ -f "$src" ] && cp "$src" "deploy/pi/tools/$t" || true
done

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
