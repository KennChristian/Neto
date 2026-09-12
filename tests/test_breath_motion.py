"""Continuous head motion (2026-09-12).

Every gesture used to be a goto_target: a blocking interpolated move with dead
air after it, so between gestures the head was perfectly still — which reads as
switched off rather than listening. set_target is the SDK's non-blocking path
(38 Hz sustained on this robot), so a breath layer rides under the existing
choreography. It has to be subtle, never repeat visibly, and never jump.
"""
from __future__ import annotations

import os
import sys

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
import main_voice_robot as mvr  # noqa: E402


def _g(scale=1.0):
    g = mvr.Gestures.__new__(mvr.Gestures)
    g.breath_scale = scale
    return g


def test_motion_is_small_enough_not_to_be_named():
    g = _g()
    peak = max(max(abs(v) for v in g.breath_offset(t / 20)) for t in range(4000))
    assert 1.0 < peak < 18.0, f"peak {peak:.2f} deg — alive/visible incl. side-to-side sway (CJ_BREATH_GAIN + CJ_HEAD_SWAY_DEG)"


def test_it_never_jumps():
    """A step between consecutive frames would show as a twitch. At 30 Hz the
    move per frame must stay well under a tenth of a degree."""
    g = _g()
    dt = 1.0 / mvr.BREATH_HZ
    worst = 0.0
    prev = g.breath_offset(0.0)
    for i in range(1, 6000):
        cur = g.breath_offset(i * dt)
        worst = max(worst, max(abs(a - b) for a, b in zip(cur, prev)))
        prev = cur
    assert worst < 0.3, f"{worst:.3f} deg per frame is a visible step"   # slow sway raises it, still <6 deg/s


def test_the_pattern_does_not_visibly_repeat():
    g = _g()
    base = [g.breath_offset(t / 10) for t in range(100)]      # a 10 s window
    for shift in range(50, 3000, 37):                          # compare it against later windows
        other = [g.breath_offset((t + shift) / 10) for t in range(100)]
        diff = max(max(abs(a - b) for a, b in zip(p, q)) for p, q in zip(base, other))
        assert diff > 0.05, f"the cycle repeats after {shift / 10:.0f} s"


def test_scale_zero_holds_the_head_still():
    assert _g(0.0).breath_offset(7.0) == (0.0, 0.0, 0.0)
    half, full = _g(0.5).breath_offset(3.0), _g(1.0).breath_offset(3.0)
    assert all(abs(2 * a - b) < 1e-9 for a, b in zip(half, full))


def test_each_mode_has_an_amplitude_and_speaking_is_calmest():
    s = mvr.Gestures.BREATH_SCALE
    assert set(s) == {"listen", "think", "sleep", "talk"}
    assert s["talk"] < s["sleep"] < s["think"] <= s["listen"]   # the answer already moves plenty
    assert all(0 < v <= 1 for v in s.values())
