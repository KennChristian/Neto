#!/bin/bash
# export-private.sh — pack everything the public repo deliberately EXCLUDES
# (API keys, certs, HeyGen key, the enrolled voice print, optionally the
# ElevenLabs clip cache) into ONE encrypted file you can carry to another
# Reachy Mini with scp or a USB stick.
#
#   export-private.sh                     -> ~/backups/private-<host>-<ts>.tar.gz.enc
#   export-private.sh --with-cache        -> also ~/.voice_cache (~400 MB: canned
#                                            answers play instantly, no credits)
#   export-private.sh [--with-cache] out.enc
#
# Encryption: openssl AES-256-CBC (PBKDF2). You are asked for a passphrase
# (or set PRIVATE_PASS=... for scripted use). Decrypt on the new robot with
# import-private.sh. Never commit the output.
set -euo pipefail
WITH_CACHE=0; OUT=""
for a in "$@"; do
  case "$a" in --with-cache) WITH_CACHE=1;; *) OUT="$a";; esac
done
[ -n "$OUT" ] || { mkdir -p "$HOME/backups"; OUT="$HOME/backups/private-$(hostname)-$(date +%Y%m%d-%H%M).tar.gz.enc"; }
M="Supervaise-Reachy-Mini-Project-main"
ITEMS=( "$M/app/.env" "$M/voice/config.py" "pi_dashboard/certs" "pi_dashboard/assets"
        "speaker_id/enrolled.npz" "speaker_id/enabled" ".asoundrc.route"
        ".config/supervaise" "bin/audio-out.local" )
[ "$WITH_CACHE" = 1 ] && ITEMS+=( ".voice_cache" )
cd "$HOME"
present=(); for i in "${ITEMS[@]}"; do [ -e "$i" ] && present+=("$i") || echo "  (skip, not present: $i)"; done
echo "packing: ${present[*]}"
PASSARG=(); [ -n "${PRIVATE_PASS:-}" ] && PASSARG=(-pass env:PRIVATE_PASS)
tar czf - "${present[@]}" | openssl enc -aes-256-cbc -pbkdf2 -salt "${PASSARG[@]}" -out "$OUT"
chmod 600 "$OUT"
echo "wrote $OUT ($(du -h "$OUT" | cut -f1))"
echo "copy it to the new robot, e.g.:  scp '$OUT' pollen@<new-robot>.local:~/"
echo "then there:                       import-private.sh ~/$(basename "$OUT") --restart"
