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

try:  # credentials live in app/.env on the robot (loaded by answer_pipeline in-service)
    from dotenv import load_dotenv
    load_dotenv(ROOT / "app" / ".env")
except Exception:
    pass

import answer_canned  # noqa: E402
import speech_engines  # noqa: E402

try:
    from text_entities import process_tts_sentence
except Exception:
    process_tts_sentence = lambda t: t  # noqa: E731

total, failed = 0, []
for e in answer_canned._load():
    for i, answer in enumerate(e["answers"], 1):
        text = process_tts_sentence(answer)
        label = f"{e['id']}[{i}]"
        for attempt in (1, 2):
            t0 = time.time()
            try:
                wav = speech_engines.tts_elevenlabs_wav(text)
            except Exception as err:
                # ElevenLabs intermittently 401s rapid-fire batch renders even
                # on a valid key — pause and retry once, then move on (a
                # missed clip just renders on its first live ask).
                print(f"  {label}: FAILED ({err}); "
                      f"{'retrying after pause' if attempt == 1 else 'skipping'}")
                if attempt == 1:
                    time.sleep(20)
                    continue
                failed.append(label)
                break
            os.unlink(wav)
            dt = time.time() - t0
            total += 1
            print(f"  {label}: {dt:.1f}s "
                  f"{'(cache hit)' if dt < 0.5 else '(rendered)'}")
            if dt >= 0.5:
                time.sleep(1.5)   # be polite: don't hammer the TTS endpoint
            break
print(f"{total} answers in the clip cache." +
      (f"  FAILED: {', '.join(failed)}" if failed else ""))
