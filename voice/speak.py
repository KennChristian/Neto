"""Voice output for Reachy Mini — ElevenLabs cloned voice with robust fallback.

Public API:

    import voice
    voice.init(mini=already_open_handle)   # optional, but preferred
    voice.speak("Magandang umaga!")        # -> bool

speak() never raises into the caller's control loop. On any TTS failure it
plays a pre-rendered clip from voice/fallback/ (or espeak-ng as a last
resort) so the robot never goes silent, and returns False.

NOTE on the SDK: reachy_mini 1.9.0 has no ``mini.speaker.play_audio()``.
The real playback surface is ``mini.media`` (MediaManager):
``start_playing()`` + ``push_audio_sample(float32 (frames, channels))`` at
``get_output_audio_samplerate()``. This module adapts to that API.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

import numpy as np
import requests

from . import audio, cache, config

log = logging.getLogger("voice")

class SynthError(Exception):
    """Internal: ElevenLabs synthesis failed. Carries a fallback reason.
    Never contains the API key."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Robot handle — accept an already-open ReachyMini rather than one per call
# ---------------------------------------------------------------------------
def effective_settings(speed: Optional[float] = None) -> dict:
    """config.VOICE_SETTINGS with an optional per-call speed override,
    clamped to ElevenLabs' valid 0.7–1.2 range. Use the SAME dict for the
    cache key so each speed variant caches separately."""
    s = dict(config.VOICE_SETTINGS)
    if speed is not None:
        s["speed"] = round(min(1.2, max(0.7, float(speed))), 3)
    return s


# Keep-alive session: sentence-streamed answers synth one request per sentence,
# and a fresh TLS handshake to api.elevenlabs.io costs ~0.3-0.7s each on the
# CM4. requests.Session reuses the connection across sentences (thread-safe
# for this use: worker pool is size 1-2 and requests serializes per-connection).
_session = requests.Session()


# The /with-timestamps endpoint returns the same audio plus per-character
# timing (drives the /face page's lip sync; same credit cost). If it ever
# rejects the request (model/tier), we fall back to the plain endpoint for
# the rest of the process. CJ_ELEVEN_TIMESTAMPS=0 disables it outright.
_ts_enabled = True


def _want_timestamps() -> bool:
    return _ts_enabled and os.environ.get(
        "CJ_ELEVEN_TIMESTAMPS", "1").strip().lower() not in {
        "0", "false", "no", "off"}


def synthesize(text: str, speed: Optional[float] = None,
               align_out: Optional[dict] = None,
               previous_text: Optional[str] = None,
               settings: Optional[dict] = None,
               previous_request_ids: Optional[list] = None) -> np.ndarray:
    """Text → float32 mono PCM at audio.SYNTH_SAMPLE_RATE via ElevenLabs.

    previous_request_ids (2026-08-29): ElevenLabs request stitching — ids of
    the sentences generated just before this one (max 3). Conditions prosody
    on the actual previous AUDIO, not just previous_text. The response's
    request id is returned in align_out["_request_id"]. If the API rejects
    the ids (stale), the request is retried once without them.
    Raises SynthError (never leaks the API key in messages).

    previous_text: the sentence spoken just before this one (request
    stitching). Answers are synthesized one sentence per request; without
    this context each request is delivered independently and the voice
    drifts between sentences (2026-08-25, user: "his voice changes a bit").
    Not part of the clip-cache key.

    settings: full voice_settings dict to send instead of
    effective_settings(speed) — used for expressive deliveries (farewells,
    2026-08-25). Callers must key the clip cache with the SAME dict.

    align_out: pass a dict to receive the ElevenLabs character alignment
    (characters / character_start_times_seconds / character_end_times_seconds)
    when the timestamps endpoint is available; left empty otherwise."""
    global _ts_enabled
    base_url = (f"https://api.elevenlabs.io/v1/text-to-speech/"
                f"{config.ELEVEN_VOICE_ID}")
    use_ts = _want_timestamps()
    url = base_url + ("/with-timestamps" if use_ts else "")
    headers = {"xi-api-key": config.ELEVEN_API_KEY,
               "accept": "application/json" if use_ts
               else "application/octet-stream"}
    body = {"text": text, "model_id": config.MODEL_ID,
            "voice_settings": settings or effective_settings(speed)}
    if previous_text:
        body["previous_text"] = previous_text[-400:]
    if previous_request_ids:
        body["previous_request_ids"] = [r for r in previous_request_ids if r][-3:]
    params = {"output_format": config.OUTPUT_FORMAT}

    last_detail = "unknown"
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            resp = _session.post(url, headers=headers, json=body, params=params,
                                 timeout=config.REQUEST_TIMEOUT_S)
        except (requests.ConnectionError, requests.Timeout) as e:
            last_detail = type(e).__name__
            log.warning("TTS request failed (%s), attempt %d/%d",
                        last_detail, attempt + 1, config.MAX_RETRIES + 1)
            if attempt < config.MAX_RETRIES:
                time.sleep(1.5 * (2 ** attempt))
                continue
            raise SynthError("network", last_detail)

        if resp.status_code == 200:
            if align_out is not None:
                align_out["_request_id"] = resp.headers.get("request-id")
            if use_ts:
                try:
                    doc = resp.json()
                    raw = base64.b64decode(doc["audio_base64"])
                    if align_out is not None and doc.get("alignment"):
                        align_out.update(doc["alignment"])
                except (ValueError, KeyError, TypeError) as e:
                    raise SynthError(
                        "error", f"bad timestamps payload ({type(e).__name__})")
            else:
                raw = resp.content
            pcm = audio.pcm16_bytes_to_float(raw)
            if pcm.size == 0:
                raise SynthError("error", "empty audio response")
            return pcm

        if body.get("previous_request_ids") and resp.status_code in (400, 422):
            # stale/unknown stitching ids: drop them and try again once
            log.warning("previous_request_ids rejected (HTTP %d) — retrying without",
                        resp.status_code)
            body.pop("previous_request_ids", None)
            continue
        if use_ts and resp.status_code in (400, 404, 405, 422):
            # with-timestamps not available for this model/tier — drop to the
            # plain endpoint for the rest of the process (lip sync degrades
            # to estimated timing; audio unaffected).
            log.warning("with-timestamps rejected (HTTP %d) — plain TTS "
                        "fallback for this process", resp.status_code)
            _ts_enabled = False
            use_ts = False
            url = base_url
            headers["accept"] = "application/octet-stream"
            continue

        if resp.status_code == 401:
            # Do NOT retry. 401 covers BOTH a bad key AND a per-key credit
            # cap being exhausted (code "quota_exceeded" — hit live
            # 2026-08-21: the key had a 10k cap while the account still had
            # credits). Surface the API's own code so the two are never
            # confused; the body carries no secrets.
            try:
                code = resp.json().get("detail", {}).get("code", "")
            except Exception:
                code = ""
            if code == "quota_exceeded":
                log.error("ElevenLabs 401 quota_exceeded: this API KEY's "
                          "credit cap is used up (the account may still have "
                          "credits). Raise the key's limit in the ElevenLabs "
                          "dashboard under API Keys.")
                raise SynthError("quota", "key credit cap exhausted (401)")
            log.error("ElevenLabs returned 401 (%s): the API key is invalid "
                      "or lacks the text_to_speech scope. Fix ELEVEN_API_KEY "
                      "in voice/config.py or the environment.",
                      code or "no detail code")
            raise SynthError("error", "unauthorized (401)")

        if resp.status_code == 429:
            # Do NOT retry. Surface remaining credits if the API tells us.
            remaining = {k: v for k, v in resp.headers.items()
                         if "remaining" in k.lower() or "limit" in k.lower()}
            log.error("ElevenLabs returned 429 (quota/rate limit exceeded). "
                      "Quota info: %s", remaining or "not provided")
            raise SynthError("quota", "quota exceeded (429)")

        if 500 <= resp.status_code < 600:
            last_detail = f"server error {resp.status_code}"
            log.warning("TTS %s, attempt %d/%d", last_detail,
                        attempt + 1, config.MAX_RETRIES + 1)
            if attempt < config.MAX_RETRIES:
                time.sleep(1.5 * (2 ** attempt))
                continue
            raise SynthError("network", last_detail)

        # Other 4xx — not retryable, log a safe summary (never the body verbatim
        # beyond the API's machine-readable status field).
        detail = ""
        try:
            detail = str(resp.json().get("detail", {}).get("status", ""))
        except Exception:
            pass
        log.error("TTS request rejected: HTTP %d %s", resp.status_code, detail)
        raise SynthError("error", f"http {resp.status_code}")

    raise SynthError("error", last_detail)  # unreachable, defensive


# ---------------------------------------------------------------------------
# Playback
# ---------------------------------------------------------------------------
