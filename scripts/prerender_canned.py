"""Pre-render every canned answer into the ElevenLabs clip cache so the FIRST
ask of each common question plays instantly. Mirrors the classic speak() path
exactly (entity TTS pass, then base-speed synth) so the cache key matches.

Run from the repo root:  app/.venv/bin/python scripts/prerender_canned.py
Re-run after editing data/entities/canned_answers.json (only new/changed
answers cost credits — unchanged ones are cache hits).
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
os.environ.setdefault("CJ_CANNED_ENABLED", "1")

try:  # credentials live in app/.env on the robot (loaded by cj_chat in-service)
    from dotenv import load_dotenv
    load_dotenv(ROOT / "app" / ".env")
except Exception:
    pass

import canned_answers  # noqa: E402
import voice_io  # noqa: E402

try:
    from postprocess import process_tts_sentence
except Exception:
    process_tts_sentence = lambda t: t  # noqa: E731

total = 0
for e in canned_answers._load():
    for answer in e["answers"]:
        text = process_tts_sentence(answer)
        t0 = time.time()
        wav = voice_io.tts_elevenlabs_wav(text)
        os.unlink(wav)
        dt = time.time() - t0
        total += 1
        print(f"  {e['id']}: {dt:.1f}s {'(cache hit)' if dt < 0.5 else '(rendered)'}")
print(f"{total} answers in the clip cache.")
