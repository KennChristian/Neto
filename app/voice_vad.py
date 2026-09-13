"""voice_vad — Silero VAD (via sherpa-onnx, no torch) for the voice-isolation
gates (Phase 1, 2026-08-30). LOG-ONLY: analyze() measures how much real speech
a captured utterance contains; nothing is rejected on its result yet. The
numbers land on the per-turn `[gate]` journal line so the thresholds can be
chosen from real turns before any gate is armed.

analyze(path_or_samples, sr) -> {"speech_s", "total_s", "fraction", "segments"}
Fails open (returns None) if the model is missing or anything errors.
Model: app/wake/models/silero_vad.onnx (CJ_VAD_MODEL_PATH overrides).
"""
from __future__ import annotations

import os
import threading

_MODEL = os.environ.get("CJ_VAD_MODEL_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "wake", "models", "silero_vad.onnx")
_lock = threading.Lock()
_vad_cfg = None
_vad = None            # the one cached detector (see _detector)
_vad_buffer_s = 0      # seconds of buffer it was built with


def _config():
    global _vad_cfg
    if _vad_cfg is None:
        import sherpa_onnx
        _vad_cfg = sherpa_onnx.VadModelConfig(
            silero_vad=sherpa_onnx.SileroVadModelConfig(
                model=_MODEL, threshold=float(os.environ.get("CJ_VAD_THRESHOLD", "0.5")),
                min_silence_duration=0.25, min_speech_duration=0.2),
            sample_rate=16000)
    return _vad_cfg


def _detector(total: float):
    """The ONE VoiceActivityDetector, reused across calls. Caller holds _lock.

    Until 2026-09-13 analyze() built a fresh detector — a fresh Silero ONNX
    session — for every utterance. The recorder caps a capture at 30 s
    (main_voice_robot.record_with_meter max_s=30), so one 35 s buffer covers
    every real call; anything longer rebuilds once, bigger, and that becomes
    the cached detector.
    """
    global _vad, _vad_buffer_s
    import sherpa_onnx
    want = max(35, int(total) + 5)
    if _vad is None or want > _vad_buffer_s:
        _vad = sherpa_onnx.VoiceActivityDetector(_config(), buffer_size_in_seconds=want)
        _vad_buffer_s = want
    return _vad


def analyze(src, sr: int = 16000):
    """src: wav path or a float32/int16 mono numpy array at `sr`."""
    try:
        import numpy as np
        import sherpa_onnx
        if isinstance(src, str):
            import soundfile as sf
            x, sr = sf.read(src, dtype="float32")
        else:
            x = np.asarray(src)
            if x.dtype != np.float32:
                x = x.astype(np.float32) / (32768.0 if x.dtype.kind == "i" else 1.0)
        if x.ndim > 1:
            x = x[:, 0]
        if sr != 16000:
            n = int(len(x) * 16000 / sr)
            x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
            sr = 16000
        total = len(x) / sr
        if total < 0.1:
            return {"speech_s": 0.0, "total_s": round(total, 2), "fraction": 0.0, "segments": 0}
        with _lock:   # sherpa detector objects are not thread-safe; one at a time
            vad = _detector(total)
            vad.reset()             # drop the previous utterance's buffered audio
            while not vad.empty():  # ...and any segment reset() may have left queued
                vad.pop()
            for i in range(0, len(x), 512):
                vad.accept_waveform(x[i:i + 512])
            vad.flush()
            speech, segs = 0.0, 0
            while not vad.empty():
                speech += len(vad.front.samples) / sr
                segs += 1
                vad.pop()
        return {"speech_s": round(speech, 2), "total_s": round(total, 2),
                "fraction": round(speech / total, 2), "segments": segs}
    except Exception as e:
        print(f"[vad] skipped ({type(e).__name__}: {e})")
        return None
