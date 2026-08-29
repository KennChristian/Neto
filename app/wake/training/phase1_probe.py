"""Probe the three real-voice raw WAVs — format, duration, noise floor.

Reports per-file:
  • sample rate, channels, bit depth
  • total duration
  • RMS dBFS of the QUIETEST 200 ms in the file (noise-floor estimate)
  • peak RMS dBFS over any 200 ms (signal envelope estimate)

The gap between noise floor and signal envelope tells us where to set
silence_thresh for split_on_silence. We want silence_thresh ~5-8 dB
above the noise floor so genuine silences register but speech doesn't
get clipped.
"""
from __future__ import annotations

import sys
import wave
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "real_raw"
FILES = [
    "heycj_male1_clean.wav",
    "heycj_male2_clean.wav",
    "heycj_female1_cafe.wav",
]


def db_rms(samples: np.ndarray) -> float:
    """RMS of int16 samples, expressed in dBFS (0 dB = full scale)."""
    if samples.size == 0:
        return -float("inf")
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    if rms <= 0:
        return -float("inf")
    # int16 full scale = 32768
    return 20.0 * np.log10(rms / 32768.0)


for fn in FILES:
    p = RAW_DIR / fn
    with wave.open(str(p), "rb") as f:
        sr = f.getframerate()
        ch = f.getnchannels()
        sw = f.getsampwidth()
        nf = f.getnframes()
        raw = f.readframes(nf)

    if sw != 2:
        print(f"{fn}: unexpected sample width {sw} — skipping")
        continue

    y = np.frombuffer(raw, dtype=np.int16)
    if ch > 1:
        y = y.reshape(-1, ch).mean(axis=1).astype(np.int16)

    dur_s = len(y) / sr
    # Roll a 200 ms window across the file; record min + max RMS.
    win = int(0.20 * sr)
    if win < 1:
        win = 1
    n_windows = max(1, len(y) // win)
    rms_db_list = []
    for i in range(n_windows):
        chunk = y[i * win:(i + 1) * win]
        rms_db_list.append(db_rms(chunk))
    rms_arr = np.array(rms_db_list)
    quietest = float(np.min(rms_arr))
    median = float(np.median(rms_arr))
    loudest = float(np.max(rms_arr))

    print(f"{fn}")
    print(f"  format:          {sr} Hz · {ch} ch · {sw * 8}-bit")
    print(f"  duration:        {dur_s:.1f} s")
    print(f"  RMS dBFS  min:   {quietest:.1f}  (≈ noise floor)")
    print(f"           median: {median:.1f}")
    print(f"           max:    {loudest:.1f}  (≈ peak speech RMS)")
    print(
        f"  suggested silence_thresh ≈ "
        f"{quietest + 6:.0f} dBFS  "
        f"(noise floor + 6 dB)"
    )
    print()
