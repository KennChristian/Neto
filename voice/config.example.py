# Template — copy to voice/config.py (gitignored) and fill in the credentials.
#
#     cp voice/config.example.py voice/config.py
#
# NEVER commit voice/config.py: it holds your ElevenLabs API key.

# ─── FILL THESE IN ─────────────────────────────
ELEVEN_API_KEY = ""     # paste key here — https://elevenlabs.io → profile → API Keys
ELEVEN_VOICE_ID = ""    # paste voice ID here — https://elevenlabs.io → Voices → your clone → ID
# ───────────────────────────────────────────────

import os as _os  # noqa: E402 — credentials stay at the very top by design

# Environment wins over the file value, so the key can move to an
# EnvironmentFile-based systemd unit later without touching code.
ELEVEN_API_KEY = _os.environ.get("ELEVEN_API_KEY", "") or ELEVEN_API_KEY
ELEVEN_VOICE_ID = _os.environ.get("ELEVEN_VOICE_ID", "") or ELEVEN_VOICE_ID

if not ELEVEN_API_KEY:
    raise RuntimeError(
        "voice/config.py: ELEVEN_API_KEY is empty. Set the ELEVEN_API_KEY "
        "environment variable, or paste your key at the top of voice/config.py. "
        "Get one at https://elevenlabs.io → profile icon → 'API Keys' "
        "(the key needs the text_to_speech scope)."
    )
if not ELEVEN_VOICE_ID:
    raise RuntimeError(
        "voice/config.py: ELEVEN_VOICE_ID is empty. Paste the ID of your cloned "
        "voice at the top of voice/config.py. Find it at https://elevenlabs.io → "
        "'Voices' → your cloned voice → 'ID' (a ~20-character code)."
    )

HARDWARE = "wireless"   # "wireless" (Pi 5 onboard) or "lite" (tethered to host)

MODEL_ID = "eleven_flash_v2_5"
OUTPUT_FORMAT = "pcm_24000"

VOICE_SETTINGS = {
    "stability": 0.50,
    "similarity_boost": 0.75,
    "style": 0.0,
    "use_speaker_boost": True,
}

# Post-processing for the 5W @ 4Ω driver
HIGHPASS_HZ = 180
PRESENCE_BOOST_HZ = 3000
PRESENCE_BOOST_DB = 3.0
TARGET_LUFS = -16.0

CACHE_DIR = "~/.voice_cache"
CACHE_MAX_MB = 500
REQUEST_TIMEOUT_S = 10
MAX_RETRIES = 2
