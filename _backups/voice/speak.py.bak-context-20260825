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

_FALLBACK_DIR = Path(__file__).resolve().parent / "fallback"

# Canned situations worth pre-rendering (see fallback/README.md and
# fallback/generate_fallback_clips.py).
REASON_PHRASES: dict[str, str] = {
    "network": "I seem to have lost my connection. Give me a moment.",
    "quota": "My voice allowance is used up for now. Bear with me.",
    "error": "Something went wrong with my voice. Bear with me.",
}


class SynthError(Exception):
    """Internal: ElevenLabs synthesis failed. Carries a fallback reason.
    Never contains the API key."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Robot handle — accept an already-open ReachyMini rather than one per call
# ---------------------------------------------------------------------------
_mini: Any = None
_mini_lock = threading.Lock()


def init(mini: Any = None) -> None:
    """Hand this module an already-open ReachyMini instance. The SDK does not
    like concurrent connections, so share the one your control loop owns."""
    global _mini
    with _mini_lock:
        _mini = mini


def _get_mini() -> Any:
    """Return the shared handle, lazily opening one only if none was given."""
    global _mini
    with _mini_lock:
        if _mini is None and config.HARDWARE == "wireless":
            try:
                from reachy_mini import ReachyMini
                log.warning("no ReachyMini handle provided — opening one; "
                            "prefer voice.init(mini=...) from your control loop")
                _mini = ReachyMini()
            except ModuleNotFoundError:
                log.error("reachy_mini SDK is not installed in this Python "
                          "environment — robot playback unavailable, using "
                          "host audio (aplay routes to the robot speaker "
                          "when running on the robot itself)")
            except Exception as e:
                log.error("could not open ReachyMini handle: %s", type(e).__name__)
        return _mini


# ---------------------------------------------------------------------------
# Synthesis (ElevenLabs REST — raw PCM back, retries with backoff)
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
               align_out: Optional[dict] = None) -> np.ndarray:
    """Text → float32 mono PCM at audio.SYNTH_SAMPLE_RATE via ElevenLabs.
    Raises SynthError (never leaks the API key in messages).

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
            "voice_settings": effective_settings(speed)}
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
def _play_on_robot(pcm: np.ndarray, sr: int, blocking: bool) -> bool:
    """Push PCM through mini.media (16 kHz stereo float32 on current SDK)."""
    mini = _get_mini()
    if mini is None:
        return False
    try:
        media = mini.media
        out_sr = int(media.get_output_audio_samplerate())
        out_ch = int(media.get_output_channels())
        data = audio.resample(pcm, sr, out_sr)
        frames = np.repeat(data[:, None], out_ch, axis=1) if out_ch > 1 \
            else data[:, None]
        frames = np.ascontiguousarray(frames, dtype=np.float32)
        media.start_playing()
        chunk = int(out_sr * 0.1)  # 100 ms pushes
        for i in range(0, frames.shape[0], chunk):
            media.push_audio_sample(frames[i:i + chunk])
        if blocking:
            time.sleep(frames.shape[0] / out_sr + 0.15)
        return True
    except Exception as e:
        log.warning("robot playback failed (%s) — trying host audio",
                    type(e).__name__)
        return False


def _play_on_host(pcm: np.ndarray, sr: int, blocking: bool) -> bool:
    """Host audio: sounddevice, then aplay as a last resort."""
    try:
        import sounddevice as sd
        # many ALSA routes only negotiate 44.1/48 kHz — resample up front
        play_sr = 48_000
        sd.play(audio.resample(pcm, sr, play_sr), play_sr)
        if blocking:
            sd.wait()
        return True
    except Exception as e:
        log.warning("sounddevice playback failed (%s) — trying aplay",
                    type(e).__name__)
    try:
        import soundfile as sf
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = Path(f.name)
        sf.write(tmp, pcm, sr, subtype="PCM_16")
        proc = subprocess.Popen(["aplay", "-q", str(tmp)],
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        if blocking:
            rc = proc.wait(timeout=max(10.0, pcm.size / sr + 5.0))
            if rc != 0:
                log.error("aplay exited %d — no audio was played", rc)
                return False
        return True
    except Exception as e:
        log.error("all playback paths failed (%s)", type(e).__name__)
        return False


def _play(pcm: np.ndarray, sr: int, blocking: bool) -> bool:
    if config.HARDWARE == "wireless":
        return _play_on_robot(pcm, sr, blocking) or _play_on_host(pcm, sr, blocking)
    return _play_on_host(pcm, sr, blocking)


# ---------------------------------------------------------------------------
# Fallback — the robot must never go silent
# ---------------------------------------------------------------------------
def _fallback_clip(normalized: str) -> Optional[tuple[np.ndarray, int]]:
    """Look up a pre-rendered clip for this exact phrase in voice/fallback/."""
    index = _FALLBACK_DIR / "index.json"
    if not index.is_file():
        return None
    try:
        import soundfile as sf
        mapping: dict[str, str] = json.loads(index.read_text(encoding="utf-8"))
        name = mapping.get(normalized)
        if not name:
            return None
        pcm, sr = sf.read(_FALLBACK_DIR / name, dtype="float32",
                          always_2d=False)
        return pcm, int(sr)
    except Exception as e:
        log.warning("fallback clip lookup failed: %s", type(e).__name__)
        return None


def _espeak(text: str) -> Optional[tuple[np.ndarray, int]]:
    """Last-resort synthesis with espeak-ng so *something* comes out."""
    try:
        import soundfile as sf
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = Path(f.name)
        subprocess.run(["espeak-ng", "-w", str(tmp), text], check=True,
                       timeout=15, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        pcm, sr = sf.read(tmp, dtype="float32", always_2d=False)
        if pcm.ndim > 1:
            pcm = pcm.mean(axis=1).astype(np.float32)
        return pcm, int(sr)
    except FileNotFoundError:
        log.error("espeak-ng is not installed (apt install espeak-ng) — "
                  "no last-resort voice available")
        return None
    except Exception as e:
        log.error("espeak-ng fallback failed: %s", type(e).__name__)
        return None


def _speak_fallback(normalized: str, reason: str, blocking: bool) -> None:
    """Fallback ladder: exact clip → reason clip → espeak-ng → silence."""
    clip = _fallback_clip(normalized)
    if clip is None and reason in REASON_PHRASES:
        clip = _fallback_clip(cache.normalize_text(REASON_PHRASES[reason]))
    if clip is None:
        clip = _espeak(normalized)
    if clip is not None:
        _play(clip[0], clip[1], blocking)
    else:
        log.error("fallback exhausted — staying silent for this line")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def speak(text: str, blocking: bool = True) -> bool:
    """Speak text in the cloned voice. Returns True on success, False if it
    fell back or failed. NEVER raises into the caller's control loop."""
    try:
        normalized = cache.normalize_text(text)
        if not normalized:
            return False
        key = cache.cache_key(normalized)

        hit = cache.get(key)
        if hit is not None:
            pcm, sr = hit
        else:
            try:
                raw = synthesize(normalized)
            except SynthError as e:
                log.warning("TTS unavailable (%s) — falling back", e.reason)
                _speak_fallback(normalized, e.reason, blocking)
                return False
            pcm = audio.process(raw, audio.SYNTH_SAMPLE_RATE)
            sr = audio.SYNTH_SAMPLE_RATE
            cache.put(key, pcm, sr)

        if blocking:
            return _play(pcm, sr, blocking=True)
        threading.Thread(target=_play, args=(pcm, sr, True),
                         daemon=True, name="voice-speak").start()
        return True
    except Exception as e:
        # Absolute backstop: a TTS problem must never crash the control loop.
        log.error("speak() suppressed unexpected %s: %s", type(e).__name__, e)
        try:
            _speak_fallback(cache.normalize_text(text), "error", blocking)
        except Exception:
            pass
        return False
