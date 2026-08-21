"""Synthesize text in the CJ voice (app's tts-1/echo pipeline) to a wav.

Usage: .../app/.venv/bin/python say_text_helper.py "text" /path/out.wav
Run by the dashboard's /api/say-text endpoint; needs internet.
"""
import os
import subprocess
import sys
import tempfile

APP = os.path.expanduser("~/Supervaise-Reachy-Mini-Project-main/app")
sys.path.insert(0, APP)
for line in open(os.path.join(APP, ".env")):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

import shutil  # noqa: E402

import voice_io  # noqa: E402
from voice_io import tts_concatenate_parallel  # noqa: E402

text, out = sys.argv[1], sys.argv[2]
if getattr(voice_io, "TTS_BACKEND", "openai") == "elevenlabs":
    try:
        shutil.move(voice_io.tts_elevenlabs_wav(text), out)
        sys.exit(0)
    except Exception as e:
        print(f"[say-text] elevenlabs failed ({type(e).__name__}) — openai fallback")
mp3 = tts_concatenate_parallel(text)
with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
    f.write(mp3)
    p = f.name
try:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", p, out], check=True)
finally:
    os.unlink(p)
