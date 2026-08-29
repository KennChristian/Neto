"""Hands-free WAKE-WORD front door for the CJ Panganiban pipeline.

Per the Reachy seam design (design/w2_7_reachy_seam.md §f), wake capture sits
UPSTREAM of the pipeline: `WAKE detect -> record -> STT -> query_text`, and the
pipeline receives only the final `query_text` — it has no wake logic. The wake
phrase is a NAMED PARAMETER (config.WAKE_PHRASE, default "Cee-Jap" — the resolution
of the long-flagged "Seejop"/"CJ"), never hardcoded.

Why STT keyword-spotting (not openWakeWord)?
  A custom phrase like "Cee-Jap" needs a *trained* model for openWakeWord/Porcupine
  (the reverted PLAN-0008 shipped a hand-trained hey_cj.onnx). Keyword-spotting over
  the STT we already run (speech_engines.transcribe, faster-whisper local) needs NO trained
  model and is trivially re-parameterizable — change the phrase, done. openWakeWord
  stays a pluggable backend for the robot (WakeDetector protocol) when a model exists.

Layers (each independently testable / swappable):
  * WakePhraseMatcher — pure text logic: does a transcript contain the wake phrase?
    Tolerant of Cee-Jap mishears (see jap / cee jap / seejap / seejop); strict against
    near-misses (see the map / japan / cheese) AND the legacy CJ/see-jay family, retired
    per WW-5 (2026-07-27). Zero deps, offline.
  * WakeDetector (protocol) — SttKeywordDetector | OpenWakeWordDetector (trained
    hey_cee_jap.onnx, on-device; select via config.WAKE_BACKEND).
  * AudioSource (protocol) — MicAudioSource (sounddevice, lazy/optional) | inject frames.
  * wait_for_wake() / run_hands_free_loop() — arm, detect, capture the query, hand
    query_text to a pipeline callback. The pipeline stays decoupled (robot-portable).

$0 / offline: importing this module and the matcher never touch the network, a model,
or a mic. Live capture (sounddevice) and STT/pipeline are lazy and opt-in.
"""
from __future__ import annotations

import difflib
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
import config  # noqa: E402


# ---------------------------------------------------------------- config (named params)
def _cfg(name, default):
    return getattr(config, name, default)


# Leading filler/carrier words stripped before matching ("hey see-jap" -> "see jap").
_CARRIERS = {"hey", "ok", "okay", "hi", "hello", "yo", "um", "uh", "er", "so", "a", "the"}

# Default accepted spoken forms of the wake phrase (config.WAKE_PHRASE_VARIANTS overrides).
# Cee-Jap "-jap" mishears only — a custom phrase needs no model retrain (edit the list).
# Multi-word forms match ADJACENT tokens (per-token fuzzy); single-word forms match a
# whole TOKEN (never a substring — so a short token won't fire inside a longer word).
_DEFAULT_VARIANTS = [
    # Cee-Jap "-jap" mishears ONLY. The legacy "CJ"/"see jay"/"Jay" family is RETIRED
    # per the WW-5 decision (2026-07-27): spoken "CJ" ("see jay") must stay silent.
    # two-token (onset + coda)
    "see jap", "cee jap", "see jab", "cee jab", "sea jap", "see jip", "see jop", "c jap",
    # single-token (Whisper writes the OOV word glued together)
    "seejap", "ceejap", "cjap", "seajap", "seejop", "ceejop", "seejip",
]


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


# ---------------------------------------------------------------- audio source (pluggable)
