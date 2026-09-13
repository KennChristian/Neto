"""Name pin (2026-09-12): a sentence that speaks "Panganiban" is synthesized at
one fixed speed and delivery, neighbours slew from it, and it is exempt from
the tempo stretch."""
from __future__ import annotations

import os
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP)
os.environ.setdefault("ELEVEN_API_KEY", "test-key")      # voice/config.py refuses to import without them
os.environ.setdefault("ELEVEN_VOICE_ID", "test-voice")
import speech_engines as se  # noqa: E402


def test_pinned_name_matching(monkeypatch):
    monkeypatch.delenv("CJ_NAME_PIN_WORDS", raising=False)
    assert se.pinned_name_in("I am Artemio Panganiban.")
    assert se.pinned_name_in("PANGANIBAN'S court")
    assert se.pinned_name_in("panganiban’s")
    assert not se.pinned_name_in("Pangalangan spoke.")
    assert not se.pinned_name_in("")
    monkeypatch.setenv("CJ_NAME_PIN_WORDS", "Panganiban, Tañada")
    assert se.pinned_name_in("Senator Tanada") and se.pinned_name_in("Tañada")
    monkeypatch.setenv("CJ_NAME_PIN", "0")
    assert not se.pinned_name_in("Panganiban")


def test_pin_settings_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("CJ_NAME_PIN_SPEED", raising=False)
    monkeypatch.delenv("CJ_NAME_PIN_DELIVERY", raising=False)
    monkeypatch.delenv("CJ_SPEED_BASE", raising=False)
    from voice import config as vc
    speed, (stab, style) = se.name_pin_settings()
    assert speed == round(float(vc.VOICE_SETTINGS.get("speed", 1.0)), 3)
    monkeypatch.setenv("CJ_SPEED_BASE", "0.95")         # the resting pace wins over config (user: S2)
    assert se.name_pin_settings()[0] == 0.95
    vs = se.name_pin_voice_settings()
    assert vs["speed"] == 0.95 and vs["stability"] == stab and vs["style"] == style
    monkeypatch.delenv("CJ_NAME_PIN_SEED", raising=False)
    assert se.name_pin_seed() == 4242
    monkeypatch.setenv("CJ_NAME_PIN_SEED", "0")
    assert se.name_pin_seed() is None
    assert (stab, style) == (round(float(vc.VOICE_SETTINGS["stability"]), 3), round(float(vc.VOICE_SETTINGS["style"]), 3))
    monkeypatch.setenv("CJ_NAME_PIN_SPEED", "0.93")
    monkeypatch.setenv("CJ_NAME_PIN_DELIVERY", "0.65:0.1")
    assert se.name_pin_settings() == (0.93, (0.65, 0.1))
    monkeypatch.setenv("CJ_NAME_PIN_SPEED", "5")          # clamped to ElevenLabs' range
    assert se.name_pin_settings()[0] == 1.2


def test_streaming_sentence_is_pinned_and_neighbours_slew(monkeypatch):
    import speech_streaming as ss
    monkeypatch.setattr(se, "TTS_BACKEND", "elevenlabs", raising=False)
    monkeypatch.setenv("CJ_SPEED_BASE", "0.95")
    monkeypatch.setenv("CJ_SPEED_MIN", "0.92")
    monkeypatch.setenv("CJ_SPEED_MAX", "0.99")
    monkeypatch.setenv("CJ_SPEED_MAX_STEP", "0.02")
    monkeypatch.delenv("CJ_NAME_PIN_SPEED", raising=False)   # -> CJ_SPEED_BASE 0.95
    monkeypatch.setenv("CJ_NAME_PIN_DELIVERY", "0.5:0.0")
    monkeypatch.delenv("CJ_NAME_PIN_WORDS", raising=False)
    sp = ss.SentenceSpeaker(play_fn=lambda w: False)
    submitted = []

    class _F:
        def add_done_callback(self, cb):
            pass
    def fake_submit(sentence, prev, spd, idx, emo, vs):
        submitted.append((idx, sentence, spd, vs))
        sp._futures.append((sentence, None))
        return _F()
    monkeypatch.setattr(sp, "_submit_locked", fake_submit)
    sp.add("Good day to you all.")
    sp.add("I am Artemio Panganiban, retired Chief Justice.")
    sp.add("It is a pleasure to have your company.")
    sp.add("Ask me anything about the law.")
    (i0, _, s0, v0), (i1, _, s1, v1), (i2, _, s2, v2), (i3, _, s3, v3) = submitted
    assert s0 == 0.95                                   # opener at base
    assert s1 == 0.95 and v1["stability"] == 0.5 and v1["style"] == 0.0 and v1["speed"] == 0.95
    assert 1 in sp._pinned and 0 not in sp._pinned
    assert s2 == 0.95 and s3 == 0.95                   # the pin equals the base pace: nothing to slew
    sp._pool.shutdown(wait=False)


def test_syllable_shaping_shortens_span_and_shifts_times(monkeypatch):
    import numpy as np
    monkeypatch.delenv("CJ_NAME_PIN_WORDS", raising=False)
    monkeypatch.setenv("CJ_NAME_PIN_SYLLABLE", "ngah:0.80")
    assert se.name_pin_syllable() == ("ngah", 0.8)
    monkeypatch.setenv("CJ_NAME_PIN_SYLLABLE", "off")
    assert se.name_pin_syllable() is None
    monkeypatch.setenv("CJ_NAME_PIN_SYLLABLE", "ngah:0.80")
    # the lexicon must hold the "ngah" spelling for the shaping to find it
    monkeypatch.setattr(se, "apply_forced_respellings", lambda t: t.replace("Panganiban", "pahng-ngah-NEE-bahn"))
    sr = 24000
    text = "I am pahng-ngah-NEE-bahn today."
    # synthetic clip: 60 ms per character, a tone so WSOLA has something periodic
    per = 0.06
    chars = list(text)
    st = [round(i * per, 4) for i in range(len(chars))]
    en = [round((i + 1) * per, 4) for i in range(len(chars))]
    t = np.arange(int(len(chars) * per * sr)) / sr
    pcm = (0.3 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    align = {"characters": chars, "character_start_times_seconds": st, "character_end_times_seconds": en}
    out, al2, n = se.name_pin_shape(pcm, sr, align)
    assert n == 1
    i = text.find("ngah")
    span0 = en[i + 3] - st[i]
    span1 = al2["character_end_times_seconds"][i + 3] - al2["character_start_times_seconds"][i]
    assert 0.7 * span0 < span1 < 0.9 * span0                      # the syllable is ~20 % shorter
    removed = len(pcm) - len(out)
    assert abs(removed / sr - (span0 - span1)) < 0.01             # audio and timeline shrank alike
    # a character after the name moved earlier by the same amount; one before did not move
    assert abs(al2["character_start_times_seconds"][-1] - (st[-1] - (span0 - span1))) < 0.002
    assert al2["character_start_times_seconds"][0] == st[0]
    monkeypatch.setenv("CJ_NAME_PIN_SYLLABLE", "off")
    out2, _, n2 = se.name_pin_shape(pcm, sr, align)
    assert n2 == 0 and len(out2) == len(pcm)
