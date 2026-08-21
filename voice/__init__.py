"""Reachy Mini voice output — ElevenLabs cloned voice with offline fallback.

    import voice
    voice.init(mini=my_open_handle)   # optional but preferred
    voice.speak("Hello there")        # -> bool, never raises

Config lives in voice/config.py (gitignored; copy config.example.py).
"""

from .speak import init, speak  # noqa: F401
from .cache import prerender  # noqa: F401
from .audio import rms_envelope  # noqa: F401

__all__ = ["init", "speak", "prerender", "rms_envelope"]
