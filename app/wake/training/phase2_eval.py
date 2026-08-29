"""Score the held-out real-voice positives against the v1 and v2 ONNX models.

Why: g5_train.py's val number is computed over the FULL positive_test set
(TTS + real). The operator wants to know how the real-voice clips score
specifically, since recall on real voice is the gate this retrain exists
to move.

What this does:
  • Iterate every WAV named  positive_test/real_*.wav   (the 8 clips
    held out by phase2_prep.py).
  • For each clip, run the openWakeWord feature pipeline:
        raw 16 kHz int16  →  mel-spec  →  embedding  →  classifier
    using the published `openwakeword.model.Model` so the inference
    path is byte-identical to what the kiosk does at runtime.
  • Report per-clip MAX score across the sliding window.
  • Aggregate: count fires at threshold 0.5 and 0.35 (the operator's
    G6 finding).
  • Compare v1 (app/wake/models/hey_cj.v1.onnx) vs v2
    (app/wake/models/hey_cj.onnx) head-to-head.

NB: this is an offline file-fed evaluation; it predicts the score a
clean, full-volume utterance would produce. Live-mic conditions add
their own attenuation and noise, so live scores should be modestly
lower. The relevant signal is the v1 → v2 delta.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
import soundfile as sf


_THIS = Path(__file__).resolve()
VAL_DIR = _THIS.parent / "oww_output" / "hey_cj" / "positive_test"
MODEL_V1 = _THIS.parents[1] / "models" / "hey_cj.v1.onnx"
MODEL_V2 = _THIS.parents[1] / "models" / "hey_cj.onnx"

# Operator-relevant thresholds from G6 testing.
THRESHOLDS = (0.50, 0.35)


def load_pcm16(p: Path) -> np.ndarray:
    """Load WAV → int16 mono at 16 kHz (the format Model.predict expects)."""
    y, sr = sf.read(str(p), dtype="int16", always_2d=False)
    if sr != 16_000:
        raise RuntimeError(f"{p.name}: expected 16 kHz, got {sr}")
    if y.ndim > 1:
        y = y.mean(axis=1).astype(np.int16)
    return y


def score_clip_with_model(model, samples: np.ndarray) -> float:
    """Slide an 80 ms (1280-sample) window across the clip, calling
    model.predict each frame, and return the max score seen.

    openWakeWord buffers prior frames internally, so the sliding-window
    classifier sees the full 1.5 s context once enough frames have
    been fed. We feed the entire clip (padded if shorter than 1280)
    and take the peak score across all frames — that's the operative
    'did the clip wake?' signal.
    """
    FRAME = 1280
    # Pad to a multiple of FRAME with leading silence so the first
    # frame doesn't truncate the utterance.
    if len(samples) < FRAME:
        samples = np.concatenate([np.zeros(FRAME - len(samples), dtype=np.int16),
                                  samples])
    # Pad an extra ~1 s of silence at the END too so the classifier's
    # internal context window has time to see the full utterance even
    # when the wake word sits very close to the right edge of the clip.
    samples = np.concatenate([samples, np.zeros(16_000, dtype=np.int16)])
    n_full = (len(samples) // FRAME) * FRAME
    samples = samples[:n_full]

    peak = 0.0
    for start in range(0, n_full, FRAME):
        frame = samples[start:start + FRAME]
        preds = model.predict(frame)
        score = float(next(iter(preds.values()))) if preds else 0.0
        if score > peak:
            peak = score
    return peak


def run_eval(model_path: Path, label: str, clips: list[Path]) -> dict:
    from openwakeword.model import Model
    print(f"\n── {label} : {model_path.name} ──")
    print(f"  loading model …")
    # Reset model state between clips by re-instantiating once per
    # model, but model.reset() clears the embedding buffer between
    # clips so cross-clip context doesn't pollute.
    model = Model(
        wakeword_models=[str(model_path)],
        inference_framework="onnx",
    )

    rows = []
    for clip in clips:
        samples = load_pcm16(clip)
        # Hard reset internal buffers so each clip starts cold.
        try:
            model.reset()
        except Exception:
            pass
        peak = score_clip_with_model(model, samples)
        rows.append((clip.name, peak))

    n = len(rows)
    scores = np.array([s for _, s in rows])
    n_fire_05  = int((scores >= THRESHOLDS[0]).sum())
    n_fire_035 = int((scores >= THRESHOLDS[1]).sum())

    print(f"  per-clip peak scores:")
    for name, s in rows:
        bucket = "🟢" if s >= 0.50 else ("🟡" if s >= 0.35 else "⚫")
        print(f"    {bucket}  {s:.3f}   {name}")
    print(f"  summary:")
    print(f"    n = {n}")
    print(f"    mean peak = {scores.mean():.3f}   "
          f"median = {np.median(scores):.3f}   "
          f"min = {scores.min():.3f}   max = {scores.max():.3f}")
    print(f"    fires @ 0.50: {n_fire_05}/{n}  "
          f"({100 * n_fire_05 / max(n, 1):.0f}%)")
    print(f"    fires @ 0.35: {n_fire_035}/{n}  "
          f"({100 * n_fire_035 / max(n, 1):.0f}%)")

    return {
        "label": label,
        "model": str(model_path.name),
        "n": n,
        "mean": float(scores.mean()),
        "median": float(np.median(scores)),
        "min": float(scores.min()),
        "max": float(scores.max()),
        "fires_050": n_fire_05,
        "fires_035": n_fire_035,
        "rows": rows,
    }


def main() -> int:
    real_clips = sorted(VAL_DIR.glob("real_*.wav"))
    if not real_clips:
        print(f"FAIL: no real_*.wav in {VAL_DIR}")
        return 1
    print("=" * 70)
    print(f"Phase 2 eval — held-out real-voice clips ({len(real_clips)})")
    print("=" * 70)
    for p in real_clips:
        print(f"  {p.name}")

    have_v1 = MODEL_V1.exists()
    have_v2 = MODEL_V2.exists()
    print(f"\nv1 available: {have_v1}  ({MODEL_V1})")
    print(f"v2 available: {have_v2}  ({MODEL_V2})")

    results = []
    if have_v1:
        results.append(run_eval(MODEL_V1, "v1 (TTS-only training)", real_clips))
    if have_v2:
        results.append(run_eval(MODEL_V2, "v2 (TTS + real voices)", real_clips))

    if len(results) == 2:
        v1, v2 = results
        print()
        print("=" * 70)
        print("v1 → v2 head-to-head on held-out real-voice clips")
        print("=" * 70)
        print(f"  mean peak   v1={v1['mean']:.3f}  v2={v2['mean']:.3f}  "
              f"Δ={v2['mean'] - v1['mean']:+.3f}")
        print(f"  median peak v1={v1['median']:.3f}  v2={v2['median']:.3f}  "
              f"Δ={v2['median'] - v1['median']:+.3f}")
        print(f"  fires @ 0.50  v1={v1['fires_050']}/{v1['n']}  "
              f"v2={v2['fires_050']}/{v2['n']}")
        print(f"  fires @ 0.35  v1={v1['fires_035']}/{v1['n']}  "
              f"v2={v2['fires_035']}/{v2['n']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
