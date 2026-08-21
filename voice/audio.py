"""EQ + loudness + format helpers for the voice output module.

Everything operates in-process on float32 numpy arrays (mono, [-1, 1]) —
no ffmpeg subprocess round-trips. Chain applied by :func:`process`, in order:

    1. high-pass Butterworth at config.HIGHPASS_HZ   (protects the 5W/4Ω driver)
    2. peaking EQ +config.PRESENCE_BOOST_DB at config.PRESENCE_BOOST_HZ
    3. loudness normalization to config.TARGET_LUFS  (ITU-R BS.1770-4, gated)

Also exposes :func:`rms_envelope` (0–1 envelope, for antenna motion later)
and small PCM/resampling utilities used by speak.py and cache.py.
"""

from __future__ import annotations

import logging
import math

import numpy as np
from scipy import signal

from . import config

log = logging.getLogger("voice.audio")

SYNTH_SAMPLE_RATE = 24_000  # matches config.OUTPUT_FORMAT = "pcm_24000"


# ---------------------------------------------------------------------------
# PCM format helpers
# ---------------------------------------------------------------------------
def pcm16_bytes_to_float(raw: bytes) -> np.ndarray:
    """Raw little-endian signed 16-bit PCM → float32 in [-1, 1]."""
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16_bytes(pcm: np.ndarray) -> bytes:
    """Float32 [-1, 1] → raw little-endian signed 16-bit PCM bytes."""
    clipped = np.clip(pcm, -1.0, 1.0)
    return (clipped * 32767.0).astype("<i2").tobytes()


def resample(pcm: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """Polyphase resample (mono float32). No-op when rates match."""
    if sr_from == sr_to:
        return pcm
    g = math.gcd(sr_from, sr_to)
    out = signal.resample_poly(pcm.astype(np.float64), sr_to // g, sr_from // g)
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
def highpass(pcm: np.ndarray, sr: int, cutoff_hz: float) -> np.ndarray:
    sos = signal.butter(4, cutoff_hz, btype="highpass", fs=sr, output="sos")
    return signal.sosfilt(sos, pcm).astype(np.float32)


def peaking_eq(pcm: np.ndarray, sr: int, f0: float, gain_db: float,
               q: float = 1.0) -> np.ndarray:
    """RBJ audio-EQ-cookbook peaking biquad."""
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * f0 / sr
    alpha = math.sin(w0) / (2.0 * q)
    cos_w0 = math.cos(w0)
    b = np.array([1 + alpha * a, -2 * cos_w0, 1 - alpha * a])
    den = np.array([1 + alpha / a, -2 * cos_w0, 1 - alpha / a])
    return signal.lfilter(b / den[0], den / den[0], pcm).astype(np.float32)


# ---------------------------------------------------------------------------
# Loudness (ITU-R BS.1770-4, mono, gated) — coefficients derived for any fs
# ---------------------------------------------------------------------------
def _k_weighting_coeffs(sr: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """The two K-weighting biquads (pre-shelf + RLB high-pass), designed for
    an arbitrary sample rate from the analog prototypes (as pyloudnorm does)."""
    # Stage 1: high shelf
    db, f0, q = 3.999843853973347, 1681.974450955533, 0.7071752369554196
    k = math.tan(math.pi * f0 / sr)
    vh = 10.0 ** (db / 20.0)
    vb = vh ** 0.4996667741545416
    a0 = 1.0 + k / q + k * k
    shelf_b = np.array([(vh + vb * k / q + k * k) / a0,
                        2.0 * (k * k - vh) / a0,
                        (vh - vb * k / q + k * k) / a0])
    shelf_a = np.array([1.0, 2.0 * (k * k - 1.0) / a0,
                        (1.0 - k / q + k * k) / a0])
    # Stage 2: high-pass
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / sr)
    a0 = 1.0 + k / q + k * k
    hp_b = np.array([1.0, -2.0, 1.0])
    hp_a = np.array([1.0, 2.0 * (k * k - 1.0) / a0,
                     (1.0 - k / q + k * k) / a0])
    return [(shelf_b, shelf_a), (hp_b, hp_a)]


def measure_lufs(pcm: np.ndarray, sr: int) -> float:
    """Gated integrated loudness (LUFS) of a mono signal. Returns -inf for
    silence/too-short input."""
    if pcm.size < int(0.4 * sr):
        return float("-inf")
    x = pcm.astype(np.float64)
    for b, a in _k_weighting_coeffs(sr):
        x = signal.lfilter(b, a, x)
    block = int(0.4 * sr)
    hop = block // 4  # 75 % overlap
    n_blocks = 1 + (x.size - block) // hop
    starts = np.arange(n_blocks) * hop
    ms = np.array([np.mean(x[s:s + block] ** 2) for s in starts])
    with np.errstate(divide="ignore"):
        lk = -0.691 + 10.0 * np.log10(ms)
    above_abs = ms[lk > -70.0]
    if above_abs.size == 0:
        return float("-inf")
    rel_gate = -0.691 + 10.0 * np.log10(above_abs.mean()) - 10.0
    gated = ms[(lk > -70.0) & (lk > rel_gate)]
    if gated.size == 0:
        return float("-inf")
    return float(-0.691 + 10.0 * np.log10(gated.mean()))


def normalize_loudness(pcm: np.ndarray, sr: int, target_lufs: float) -> np.ndarray:
    """Gain the signal to target LUFS, with a peak guard against clipping."""
    measured = measure_lufs(pcm, sr)
    if not math.isfinite(measured):
        return pcm
    gain = 10.0 ** ((target_lufs - measured) / 20.0)
    out = pcm * gain
    peak = float(np.max(np.abs(out))) if out.size else 0.0
    if peak > 0.99:
        out *= 0.99 / peak
        log.debug("loudness gain %.2f dB limited by peak guard",
                  20.0 * math.log10(gain))
    return out.astype(np.float32)


# ---------------------------------------------------------------------------
# The chain
# ---------------------------------------------------------------------------
def process(pcm: np.ndarray, sr: int = SYNTH_SAMPLE_RATE) -> np.ndarray:
    """Full post-processing chain for the robot's 5W @ 4Ω driver."""
    out = highpass(pcm, sr, config.HIGHPASS_HZ)
    out = peaking_eq(out, sr, config.PRESENCE_BOOST_HZ, config.PRESENCE_BOOST_DB)
    out = normalize_loudness(out, sr, config.TARGET_LUFS)
    return out


# ---------------------------------------------------------------------------
# Envelope (for antenna motion — returned only, no motor wiring here)
# ---------------------------------------------------------------------------
def rms_envelope(pcm: np.ndarray, sr: int = SYNTH_SAMPLE_RATE,
                 hop_ms: int = 20) -> np.ndarray:
    """Normalized 0–1 RMS envelope, one value per hop_ms of audio."""
    hop = max(1, int(sr * hop_ms / 1000))
    n = max(1, pcm.size // hop)
    trimmed = pcm[:n * hop].reshape(n, hop).astype(np.float64)
    env = np.sqrt(np.mean(trimmed ** 2, axis=1))
    peak = env.max()
    if peak > 0.0:
        env = env / peak
    return env.astype(np.float32)
