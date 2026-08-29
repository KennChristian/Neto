"""wake_word — openWakeWord detector for the "Hi Cee-Jap" wake phrase.

OpenWakeWordDetector wraps the ONNX model (CJ_WAKE_OWW_MODEL_PATH /
CJ_WAKE_OWW_THRESHOLD); main_voice_robot._wake_stream feeds it 80 ms frames
from the always-open mic tap, and the same resident model scores the stop
phrase during playback. make_detector() is the only entry point.

The STT-keyword detector, its mic window source and the hands-free loop were
removed 2026-08-29.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402


# ---------------------------------------------------------------- config (named params)
def _cfg(name, default):
    return getattr(config, name, default)


# Leading filler/carrier words stripped before matching ("hey see-jap" -> "see jap").

@dataclass
class MatchResult:
    fired: bool
    variant: Optional[str] = None
    score: float = 0.0
    heard: str = ""


class WakeDetector:
    """Protocol: given a short audio window (path or PCM), did the wake phrase occur?"""
    def detect(self, wav_path: str | Path) -> MatchResult:  # pragma: no cover - interface
        raise NotImplementedError


class OpenWakeWordDetector(WakeDetector):
    """Robot/production backend: trained openWakeWord model. Default model is
    wake/models/hey_cee_jap.onnx (trained per the wakeword_robot bundle, 2026-08;
    WW-5 rejection verified — 0 negatives fired in validation). Scores each audio
    window frame-by-frame (80 ms / 1280-sample frames at 16 kHz) and fires when
    the peak score clears config.WAKE_OWW_THRESHOLD. Fully on-device, no network.
    config.WAKE_OWW_MODEL_PATH overrides the model file; the .onnx.data external
    weights file must sit next to the .onnx."""

    _FRAME = 1280  # 80 ms at 16 kHz — openWakeWord's expected frame size

    def __init__(self, model_path: Optional[str] = None, threshold: Optional[float] = None):
        default_model = Path(__file__).resolve().parent / "wake" / "models" / "hey_cee_jap.onnx"
        self.model_path = str(model_path or _cfg("WAKE_OWW_MODEL_PATH", "") or default_model)
        self.threshold = float(threshold if threshold is not None
                               else _cfg("WAKE_OWW_THRESHOLD", 0.5))
        self._model = None

    def _load(self):
        if self._model is None:
            from openwakeword.model import Model  # lazy: keeps module import model-free
            self._model = Model(wakeword_models=[self.model_path],
                                inference_framework="onnx")
        return self._model

    def detect(self, wav_path: str | Path) -> MatchResult:
        import wave
        import numpy as np
        model = self._load()
        with wave.open(str(wav_path), "rb") as w:
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
            if w.getnchannels() > 1:
                pcm = pcm[::w.getnchannels()]
        model.reset()  # each window is an independent clip, not one continuous stream
        top, name = 0.0, None
        for i in range(0, len(pcm) - self._FRAME + 1, self._FRAME):
            for n, s in model.predict(pcm[i:i + self._FRAME]).items():
                if s > top:
                    top, name = float(s), n
        if top >= self.threshold:
            return MatchResult(True, name, round(top, 3), "<openwakeword>")
        return MatchResult(False, score=round(top, 3), heard="<openwakeword>")


def make_detector(backend: Optional[str] = None) -> WakeDetector:
    """openWakeWord is the only backend (the STT-keyword detector, its mic
    window source and the hands-free loop were removed 2026-08-29)."""
    backend = (backend or _cfg("WAKE_BACKEND", "openwakeword")).lower()
    if backend in ("openwakeword", "oww"):
        return OpenWakeWordDetector()
    raise ValueError(f"unsupported WAKE_BACKEND: {backend!r} (only 'openwakeword')")


