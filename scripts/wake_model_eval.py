#!/usr/bin/env python3
"""Score openWakeWord candidate models against real recordings, side by side.

    app/.venv/bin/python scripts/wake_model_eval.py \
        app/wake/models/hi_see_jap.onnx ~/Sep_7_model/whatever.onnx \
        [--clips ~/wake_real_20260901] [--thresholds 0.003,0.01,0.05,0.2]

For every model and every wav in the clips directory it streams the audio
in 80 ms frames exactly as the robot does (app/wake_word.py) and prints the
peak score. Files whose name contains "neg" count as negatives; a long
"full_session*" file is treated as a stream and reports how many distinct
fires each threshold would have produced. Use it BEFORE pointing
CJ_WAKE_OWW_MODEL_PATH at a new model: a new model's scores live on a
different scale, so the console's wake threshold must be re-picked from
this table, not carried over.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys
import wave

import numpy as np

FRAME = 1280   # 80 ms at 16 kHz


def load_wav_16k(path):
    with wave.open(path, "rb") as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        pcm = np.frombuffer(w.readframes(n), dtype=np.int16)
    if ch > 1:
        pcm = pcm.reshape(-1, ch)[:, 0]
    if sr != 16000:
        from scipy.signal import resample_poly
        from math import gcd
        g = gcd(sr, 16000)
        pcm = resample_poly(pcm.astype(np.float32), 16000 // g, sr // g).astype(np.int16)
    return pcm


WARM_S = 2.0   # openWakeWord needs ~1-2 s of audio after reset() before scores mean anything


def stream_scores(model, pcm, warm=True):
    """Scores per 80 ms frame. A short clip is scored after WARM_S of
    silence (the robot's model has been running for minutes when a visitor
    speaks — scoring a 1 s clip straight from reset() under-reads it)."""
    model.reset()
    if warm:
        pcm = np.concatenate([np.zeros(int(16000 * WARM_S), dtype=np.int16), pcm])
    out = []
    for i in range(0, len(pcm) - FRAME + 1, FRAME):
        out.append(max(model.predict(pcm[i:i + FRAME]).values()))
    return np.array(out, dtype=np.float32)


def fires(scores, thr, cooldown_frames=25):
    """Distinct fires with a 2 s cooldown, like the robot's re-arm."""
    n, i = 0, 0
    while i < len(scores):
        if scores[i] >= thr:
            n += 1
            i += cooldown_frames
        else:
            i += 1
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+", help=".onnx files (first = reference)")
    ap.add_argument("--clips", default=os.path.expanduser("~/wake_real_20260901"))
    ap.add_argument("--thresholds", default="0.003,0.01,0.03,0.1,0.3")
    a = ap.parse_args()
    from openwakeword.model import Model
    thrs = [float(t) for t in a.thresholds.split(",")]
    clips = sorted(glob.glob(os.path.join(a.clips, "*.wav")))
    if not clips:
        sys.exit(f"no wavs in {a.clips}")
    models = {}
    for p in a.models:
        try:
            models[os.path.basename(p)] = Model(wakeword_models=[p], inference_framework="onnx")
        except Exception as e:
            sys.exit(f"cannot load {p}: {type(e).__name__}: {e}")
    names = list(models)
    print("peak score per clip (positives should be HIGH, *neg* files LOW)")
    print(f"{'clip':34s}" + "".join(f"{n[:22]:>24s}" for n in names))
    streams = [c for c in clips if "full_session" in os.path.basename(c)]
    for c in clips:
        if c in streams:
            continue
        pcm = load_wav_16k(c)
        row = f"{(os.path.basename(c)[:26] + ' ' + f'{len(pcm) / 16000:.1f}s'):34s}"
        for n in names:
            row += f"{float(stream_scores(models[n], pcm).max()):>24.4f}"
        print(row)
    for c in streams:
        pcm = load_wav_16k(c)
        print(f"\n{os.path.basename(c)}: {len(pcm) / 16000:.0f} s stream — distinct fires per threshold")
        print(f"{'threshold':12s}" + "".join(f"{n[:22]:>24s}" for n in names))
        sc = {n: stream_scores(models[n], pcm) for n in names}
        for t in thrs:
            print(f"{t:<12g}" + "".join(f"{fires(sc[n], t):>24d}" for n in names))
        print(f"{'peak':12s}" + "".join(f"{float(sc[n].max()):>24.4f}" for n in names))
        print(f"{'p99 frame':12s}" + "".join(f"{float(np.percentile(sc[n], 99)):>24.4f}" for n in names))
    print("\nPick the threshold where every positive clears it and the stream's fire count "
          "matches the real wakes in that session (2026-09-01: 8 positives, 2 negatives).")


if __name__ == "__main__":
    main()
