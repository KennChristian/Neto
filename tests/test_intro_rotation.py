"""Rotating pre-rendered intro variants (2026-09-13).

Before this there was ONE intro line, synthesised live over the network on
every arrival, so every visitor heard the identical sentence and a network
stall delayed the one moment the installation gets to explain itself.
config/modes/direct.json had claimed "variants rotate" since it was written.

The instruction at the end of the line differs by mode — the wake phrase in
direct-kiosk, the handheld microphone in direct-event — so each variant is
rendered once per mode and selection is mode-aware.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import wave

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
import main_voice_robot as mvr  # noqa: E402


def _mkwav(path):
    with wave.open(str(path), "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(struct.pack("<1600h", *([0] * 1600)))


def _stage(tmp_path, variants=("i1", "i2", "i3"), modes=("kiosk", "event")):
    clips = []
    for v in variants:
        for m in modes:
            name = f"{v}_{m}.wav"
            _mkwav(tmp_path / name)
            clips.append({"id": f"{v}_{m}", "variant": v, "mode": m,
                          "wav": name, "text": f"{v} in {m}"})
    (tmp_path / "manifest.json").write_text(json.dumps({"version": 1, "clips": clips}))
    mvr.INTRO_DIR = str(tmp_path)
    return clips


def test_variants_rotate_and_never_repeat_back_to_back(tmp_path, monkeypatch):
    _stage(tmp_path)
    monkeypatch.setenv("CJ_WAKE_LISTEN", "1")
    spoken = [mvr._intro_clip(s)[1] for s in range(7)]
    assert len(set(spoken)) == 3, "all three variants must be used"
    assert not any(a == b for a, b in zip(spoken, spoken[1:])), \
        "consecutive visitors must never hear the same intro"


def test_selection_follows_the_mode(tmp_path, monkeypatch):
    _stage(tmp_path)
    monkeypatch.setenv("CJ_WAKE_LISTEN", "1")
    assert mvr._intro_clip(0)[1].endswith("kiosk")
    monkeypatch.setenv("CJ_WAKE_LISTEN", "0")
    assert mvr._intro_clip(0)[1].endswith("event"), \
        "with the wake word off the visitor must be told about the handheld, not the phrase"


def test_falls_back_to_live_tts_when_nothing_is_rendered(tmp_path):
    mvr.INTRO_DIR = str(tmp_path / "does-not-exist")
    assert mvr._intro_clip(0) is None


def test_a_missing_wav_does_not_strand_the_intro(tmp_path):
    clips = _stage(tmp_path)
    os.unlink(tmp_path / clips[0]["wav"])        # manifest lists it, file is gone
    os.environ["CJ_WAKE_LISTEN"] = "1"
    assert mvr._intro_clip(0) is None            # -> live TTS, never silence


def test_one_mode_missing_falls_back_rather_than_speaking_the_wrong_one(tmp_path, monkeypatch):
    _stage(tmp_path, modes=("kiosk",))           # event never rendered
    monkeypatch.setenv("CJ_WAKE_LISTEN", "0")    # ...but we are in event
    assert mvr._intro_clip(0) is None, \
        "better to synthesise the right words than play the wrong instruction"
