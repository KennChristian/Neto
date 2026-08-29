"""Backfill word-timing sidecars for already-cached canned clips.

The 145 canned answers were rendered before the with-timestamps upgrade
(2026-08-22), so their cached wavs have no <key>.align.json and the /face
page falls back to estimated lip sync. This script runs each cached clip
through the ElevenLabs Forced Alignment API (audio + transcript in, word
timings out — NO re-synthesis, so no voice credits for TTS) and writes the
same sidecar tts_elevenlabs_wav would have written.

Run from the repo root:  app/.venv/bin/python scripts/backfill_alignments.py
Idempotent: clips that already have a sidecar are skipped.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("CJ_CANNED_ENABLED", "1")

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / "app" / ".env")
except Exception:
    pass

import requests  # noqa: E402
import answer_canned  # noqa: E402
import speech_engines  # noqa: E402
from voice import cache as v_cache  # noqa: E402
from voice.speak import effective_settings  # noqa: E402

try:
    from text_entities import process_tts_sentence
except Exception:
    process_tts_sentence = lambda t: t  # noqa: E731

API_KEY = os.environ.get("ELEVEN_API_KEY", "")
assert API_KEY, "ELEVEN_API_KEY missing (app/.env)"


def align(wav_path, transcript):
    """Forced alignment: wav + transcript -> [[word, start, end], ...]."""
    with open(wav_path, "rb") as f:
        r = requests.post(
            "https://api.elevenlabs.io/v1/forced-alignment",
            headers={"xi-api-key": API_KEY},
            files={"file": ("clip.wav", f, "audio/wav")},
            data={"text": transcript},
            timeout=120)
    r.raise_for_status()
    doc = r.json()
    return [[w["text"], round(w["start"], 3), round(w["end"], 3)]
            for w in doc.get("words", []) if w.get("text", "").strip()]


done = skipped = missing = failed = 0
for e in answer_canned._load():
    for i, answer in enumerate(e["answers"], 1):
        label = f"{e['id']}[{i}]"
        text = process_tts_sentence(answer)
        synth_text = text
        if os.environ.get("CJ_ELEVEN_RESPELL", "0") == "1":
            synth_text = speech_engines.apply_forced_respellings(text)
        norm = v_cache.normalize_text(synth_text)
        key = v_cache.cache_key(norm, effective_settings(None))
        wav = v_cache.cache_dir() / f"{key}.wav"
        side = v_cache.cache_dir() / f"{key}.align.json"
        if side.is_file():
            skipped += 1
            continue
        if not wav.is_file():
            print(f"  {label}: no cached clip (renders on first ask)")
            missing += 1
            continue
        try:
            # Align against the DISPLAY text (pre-respell) so the /face
            # caption words read correctly; forced alignment tolerates the
            # respelled pronunciation in the audio.
            words = align(wav, text)
            if not words:
                raise ValueError("empty alignment")
            side.write_text(json.dumps(words))
            done += 1
            print(f"  {label}: {len(words)} words, "
                  f"{words[-1][2]:.1f}s")
        except Exception as err:
            failed += 1
            print(f"  {label}: FAILED ({err})")
            time.sleep(5)
        time.sleep(0.6)   # be polite to the endpoint

print(f"aligned {done}, skipped(existing) {skipped}, "
      f"no-clip {missing}, failed {failed}")
