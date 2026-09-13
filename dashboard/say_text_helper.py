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

# Optional 3rd arg: an ElevenLabs voice id to synthesize WITH, instead of the
# default cloned voice — used by the Guest voice test box (2026-09-12), which
# speaks in ELEVEN_HOST_VOICE_ID so you can hear the Host without a duet.
text, out = sys.argv[1], sys.argv[2]
_voice_override = sys.argv[3] if len(sys.argv) > 3 else ""
if _voice_override:
    os.environ["ELEVEN_VOICE_ID"] = _voice_override   # voice/config reads this at import

import shutil  # noqa: E402

import speech_engines  # noqa: E402
from speech_engines import tts_concatenate_parallel  # noqa: E402
if getattr(speech_engines, "TTS_BACKEND", "openai") == "elevenlabs":
    try:
        kw = {}
        if not _voice_override and speech_engines.pinned_name_in(text):   # name pin is CJAP-only
            kw = {"voice_settings": speech_engines.name_pin_voice_settings(), "seed": speech_engines.name_pin_seed()}
        src = speech_engines.tts_elevenlabs_wav(text, **kw)
        shutil.move(src, out)
        try:   # alignment sidecar rides along (deleted with the wav)
            shutil.move(src + ".align.json", out + ".align.json")
        except OSError:
            pass
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
