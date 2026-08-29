"""
PLAN-0008 Task 1 — Gate 2c (CJP-specific phrase test).

Operator confirmed at G2b that gpt-4o-mini-tts renders "Hey CJ" cleanly
across ash + ballad. CJP is the harder phrase — the trailing "P" is
exactly what TTS tends to swallow. This script generates 6 clips
(2 voices × 3 phrasings) for the CJP phrase only, with:

  * the same 2 voices we verified clean for CJ (ash + ballad),
  * the same 3 phrasings as G2b but for CJP:
        "Hey CJP."         (light: punctuation only)
        "Hey C J P"        (spaced letters)
        "Hey see jay pee"  (explicit phonetic)

Duration audit reports:
  * The new CJP duration per cell.
  * The delta vs the matching G2b CJ clip — if CJP duration ≤ CJ
    duration, the final "P" was almost certainly dropped (CJP should
    be slightly LONGER than CJ if rendered).
  * Quality buckets: <0.7s RUSHED, 0.7-1.5s GOOD, 1.5-2.5s LONG,
    >2.5s TOO_LONG. Operator flagged some G2b clips at 2-3s as too
    long for a natural wake word.

Cost: 64 chars × $0.06/1k = ~$0.004.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

_THIS = Path(__file__).resolve()
_APP_DIR = _THIS.parents[2]

try:
    from dotenv import load_dotenv
    load_dotenv(_APP_DIR / ".env", override=False)
except ImportError:
    pass

if not os.environ.get("OPENAI_API_KEY"):
    print("ERROR: OPENAI_API_KEY not in environment (expected in app/.env)",
          file=sys.stderr)
    sys.exit(1)

# Only the two voices the operator confirmed clean for CJ at G2b
VOICES = ("ash", "ballad")
MODEL = "gpt-4o-mini-tts"

PHRASES = [
    ("period",   "Hey CJP."),
    ("spaced",   "Hey C J P"),
    ("phonetic", "Hey see jay pee"),
]

OUT_DIR = _THIS.parent / "g2c_clips"
OUT_DIR.mkdir(exist_ok=True, parents=True)

# Reference: matching G2b CJ durations for delta comparison.
# Pulled from the G2b run output (g2b_clips/).
CJ_REFERENCE = {
    ("ash",    "period"):   1.650,
    ("ash",    "spaced"):   3.550,
    ("ash",    "phonetic"): 2.450,
    ("ballad", "period"):   2.350,
    ("ballad", "spaced"):   1.900,
    ("ballad", "phonetic"): 1.850,
}

# Cost guard
HARD_CAP_USD = 0.02
expected_chars = sum(len(p) for _, p in PHRASES) * len(VOICES)
worst_case = expected_chars / 1000 * 0.060
if worst_case > HARD_CAP_USD:
    print(f"ABORT: ${worst_case:.4f} > cap ${HARD_CAP_USD:.2f}",
          file=sys.stderr)
    sys.exit(1)

print(f"Voices:    {list(VOICES)}")
print(f"Model:     {MODEL}")
print(f"Phrases:   {[p for _, p in PHRASES]}")
print(f"Output:    {OUT_DIR.relative_to(_APP_DIR.parent)}")
print(f"Worst-case cost: ${worst_case:.4f}\n")

from openai import OpenAI
client = OpenAI()


def quality_label(dur: float) -> str:
    if dur < 0.7:
        return "RUSHED"
    if dur <= 1.5:
        return "GOOD"
    if dur <= 2.5:
        return "LONG"
    return "TOO_LONG"


total_chars = 0
total_cost = 0.0
n_ok = n_skip = 0
results = []
t_start = time.time()

for voice in VOICES:
    for phrase_label, phrase_text in PHRASES:
        out_path = OUT_DIR / f"{voice}_{phrase_label}.wav"
        try:
            with client.audio.speech.with_streaming_response.create(
                model=MODEL, voice=voice, input=phrase_text,
                speed=1.0, response_format="wav",
            ) as resp:
                resp.stream_to_file(str(out_path))
            cost = len(phrase_text) / 1000 * 0.060
            total_chars += len(phrase_text)
            total_cost += cost
            n_ok += 1
            size = out_path.stat().st_size
            dur_cjp = max(0, size - 44) / (24000 * 1 * 2)
            cj_ref = CJ_REFERENCE.get((voice, phrase_label), 0.0)
            delta = dur_cjp - cj_ref
            ql = quality_label(dur_cjp)
            # If the CJP clip is the same length or shorter than the
            # matching CJ clip, the trailing "P" was probably dropped.
            p_status = "P_DROPPED?" if delta < 0.10 else "P_LIKELY_OK"
            results.append((voice, phrase_label, dur_cjp, cj_ref, delta, ql, p_status))
            print(f"  [{voice:7s} / {phrase_label:8s}]  "
                  f"CJP={dur_cjp:5.3f}s  CJ_ref={cj_ref:5.3f}s  "
                  f"delta={delta:+5.3f}s  {ql:8s}  {p_status}")
        except Exception as e:
            n_skip += 1
            print(f"  [{voice:7s} / {phrase_label:8s}]  FAILED: {str(e)[:120]}")

print(f"\nWrote {n_ok}/{n_ok + n_skip} clips to {OUT_DIR}")
print(f"Cost this run:        ${total_cost:.5f}")
print(f"Elapsed:              {time.time() - t_start:.1f} s\n")

# Summary by phrase formulation
print(f"{'phrase':10s}  {'cells GOOD':12s}  {'P likely OK':14s}  {'mean dur':10s}")
print("-" * 60)
import statistics
for phrase_label, _ in PHRASES:
    sub = [r for r in results if r[1] == phrase_label]
    good   = sum(1 for r in sub if r[5] == "GOOD")
    p_ok   = sum(1 for r in sub if r[6] == "P_LIKELY_OK")
    mean_d = statistics.mean(r[2] for r in sub) if sub else 0.0
    print(f"{phrase_label:10s}  {good}/{len(sub):<11d}  {p_ok}/{len(sub):<13d}  {mean_d:5.3f}s")

print()
print("Listen to each .wav and confirm:")
print("  (1) the final 'P' is clearly pronounced (NOT a CJ-only sound),")
print("  (2) the clip isn't dragging — target ~1s, < 1.5s is natural.")
