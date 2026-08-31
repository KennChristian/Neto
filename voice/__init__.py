"""voice — ElevenLabs cloned-voice synthesis for the CJ robot.

    from voice.speak import synthesize, effective_settings, SynthError

Config lives in voice/config.py (gitignored; copy config.example.py).
Playback/fallback helpers were removed 2026-08-29 (the app plays audio).
"""

from .speak import synthesize, effective_settings, SynthError  # noqa: F401
from .cache import prerender  # noqa: F401
from .audio import rms_envelope  # noqa: F401

__all__ = ["synthesize", "effective_settings", "SynthError", "prerender", "rms_envelope"]
