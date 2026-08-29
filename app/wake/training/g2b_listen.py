"""
PLAN-0008 Task 1 — Gate 2b (phrase-formulation experiment).

After Gate 2 revealed 9/11 voices rendered the bare phrase "Hey CJ" as
~0.46s fragments (truncated to "Hey" + tail), this script tests three
phrasing fixes against three representative voices to find a clean
formulation before committing to G4.

Voice probe set (3):
  * echo    (tts-1 — broken in G2 at 0.463 s)
  * ash     (gpt-4o-mini-tts — broken in G2 at 0.388 s)
  * ballad  (gpt-4o-mini-tts — clean in G2 at 1.350 s; control)

Phrase probe set (3):
  * "Hey CJ."         — punctuation only (lightest intervention)
  * "Hey C J"         — spaced letters (forces letter-by-letter read)
  * "Hey see jay"     — explicit phonetic spelling

3 × 3 = 9 clips. Cost ceiling at gpt-4o-mini-tts rate
(~$0.06 / 1k chars × ~110 chars) ≈ $0.007.

After this script writes the WAVs, the operator listens. The
combination (or combinations) producing clean two-syllable "Hey see-jay"
across all 3 voices is what we use for G4's full matrix.
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

# Per-voice model assignments. tts-1 voices use the tts-1 model; the
# newer voices use gpt-4o-mini-tts.
VOICE_MODEL = {
    "echo":   "tts-1",
    "ash":    "gpt-4o-mini-tts",
    "ballad": "gpt-4o-mini-tts",
}

PHRASES = [
    ("period",        "Hey CJ."),       # lightest intervention
    ("spaced",        "Hey C J"),       # spaced letters
    ("phonetic",      "Hey see jay"),   # explicit phonetic
]

OUT_DIR = _THIS.parent / "g2b_clips"
OUT_DIR.mkdir(exist_ok=True, parents=True)

# Cost guard
PRICE_PER_KCHAR = {"tts-1": 0.015, "gpt-4o-mini-tts": 0.060}
HARD_CAP_USD = 0.05
expected_chars = sum(len(p) for _, p in PHRASES) * len(VOICE_MODEL)
worst_case = expected_chars / 1000 * PRICE_PER_KCHAR["gpt-4o-mini-tts"]
if worst_case > HARD_CAP_USD:
    print(f"ABORT: worst-case ${worst_case:.4f} > cap ${HARD_CAP_USD:.2f}",
          file=sys.stderr)
    sys.exit(1)

print(f"Voices:    {list(VOICE_MODEL)}")
print(f"Phrases:   {[p for _, p in PHRASES]}")
print(f"Output:    {OUT_DIR.relative_to(_APP_DIR.parent)}")
print(f"Worst-case cost: ${worst_case:.4f}\n")

from openai import OpenAI
client = OpenAI()

total_chars = 0
total_cost = 0.0
n_ok = n_skip = 0
t_start = time.time()
results = []

for voice, model in VOICE_MODEL.items():
    for phrase_label, phrase_text in PHRASES:
        out_path = OUT_DIR / f"{voice}_{phrase_label}.wav"
        try:
            with client.audio.speech.with_streaming_response.create(
                model=model,
                voice=voice,
                input=phrase_text,
                speed=1.0,
                response_format="wav",
            ) as resp:
                resp.stream_to_file(str(out_path))
            cost = len(phrase_text) / 1000 * PRICE_PER_KCHAR[model]
            total_chars += len(phrase_text)
            total_cost += cost
            n_ok += 1
            # Compute actual duration from file size
            size = out_path.stat().st_size
            dur = max(0, size - 44) / (24000 * 1 * 2)
            quality = "RUSHED" if dur < 0.7 else ("CLEAN" if dur > 1.0 else "BORDER")
            results.append((voice, model, phrase_label, phrase_text, dur, quality, size))
            print(f"  [{voice:7s} / {phrase_label:8s} / {model:16s}]  "
                  f"dur={dur:5.3f}s  {quality:6s}  "
                  f"cost=${cost:.5f}  -> {out_path.name}")
        except Exception as e:
            n_skip += 1
            print(f"  [{voice:7s} / {phrase_label:8s} / {model:16s}]  "
                  f"FAILED: {str(e)[:120]}")

print(f"\nWrote {n_ok}/{n_ok + n_skip} clips to {OUT_DIR}")
print(f"Cost this run:  ${total_cost:.5f}")
print(f"Elapsed:        {time.time() - t_start:.1f} s\n")

# Summary by phrase formulation
print(f"{'phrase':10s}  {'voices clean':14s}  {'mean dur':10s}")
print("-" * 50)
import statistics
for phrase_label, _ in PHRASES:
    sub = [r for r in results if r[2] == phrase_label]
    clean = sum(1 for r in sub if r[5] == "CLEAN")
    mean_dur = statistics.mean(r[4] for r in sub) if sub else 0.0
    print(f"{phrase_label:10s}  {clean}/{len(sub):<13d}  {mean_dur:5.3f}s")

print()
print("Listen to each .wav and report which formulation produced the")
print("cleanest two-syllable 'Hey see-jay' rendering across all 3 voices.")
