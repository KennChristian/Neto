# NO SECRETS IN THIS FILE. On the robot the two credentials are provided as
# environment variables (via app/.env, loaded at app startup); the literals
# below are intentionally empty placeholders. Environment always wins.

# ─── FILL THESE IN (or set them in app/.env) ───
ELEVEN_API_KEY = ""     # or set ELEVEN_API_KEY in the environment / app/.env
ELEVEN_VOICE_ID = ""    # or set ELEVEN_VOICE_ID in the environment / app/.env
# ───────────────────────────────────────────────

import os as _os  # noqa: E402 — credentials stay at the very top by design

ELEVEN_API_KEY = _os.environ.get("ELEVEN_API_KEY", "") or ELEVEN_API_KEY
ELEVEN_VOICE_ID = _os.environ.get("ELEVEN_VOICE_ID", "") or ELEVEN_VOICE_ID

if not ELEVEN_API_KEY:
    raise RuntimeError(
        "voice/config.py: ELEVEN_API_KEY is empty. Set ELEVEN_API_KEY in "
        "app/.env (preferred on the robot) or paste it at the top of "
        "voice/config.py. Get one at https://elevenlabs.io → profile icon → "
        "'API Keys' (needs the text_to_speech scope)."
    )
if not ELEVEN_VOICE_ID:
    raise RuntimeError(
        "voice/config.py: ELEVEN_VOICE_ID is empty. Set ELEVEN_VOICE_ID in "
        "app/.env or paste it at the top of voice/config.py. Find it at "
        "https://elevenlabs.io → 'Voices' → your cloned voice → 'ID'."
    )

HARDWARE = "wireless"   # "wireless" (Pi onboard) or "lite" (tethered to host)

MODEL_ID = "eleven_flash_v2_5"
OUTPUT_FORMAT = "pcm_24000"

VOICE_SETTINGS = {
    "stability": 0.50,
    "similarity_boost": 0.75,
    "style": 0.0,
    "use_speaker_boost": True,
    # Delivery pace: 1.0 = the clone's natural speed; valid 0.7-1.2.
    # 0.9 set 2026-08-19 ("a bit slower"); back to 1.0 per user request
    # 2026-08-22 ("speed up a bit"). ⚠ changing this changes every cache
    # key — re-run scripts/prerender_canned.py + backfill_alignments.py.
    "speed": 1.0,
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
