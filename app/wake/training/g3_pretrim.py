"""
PLAN-0008 Task 1 — Pre-G4 trim verification.

Operator concern: the librosa silence-trim might chop the final "pee"
syllable (a low-energy voiceless plosive). This script generates 3
clips (one per phrase variant on the same voice) at the speed we'll
actually use, runs them through the full G4 audio pipeline (resample
→ trim → safety-pad → 16 kHz PCM), and saves BOTH raw and trimmed
versions side-by-side so the operator can listen and verify the P
survives.

Output:
    app/wake/training/g3_pretrim_clips/
        ballad_hey_cj_raw.wav            ← 24 kHz, untrimmed (reference)
        ballad_hey_cj_trimmed.wav        ← 16 kHz, trimmed + padded
        ballad_hey_see_jay_pee_raw.wav   ← CJP at full length
        ballad_hey_see_jay_pee_trimmed.wav
        ballad_see_jay_pee_raw.wav       ← bare CJP-bare phrase
        ballad_see_jay_pee_trimmed.wav

Plus the durations table so we can see exactly how much was trimmed.

Cost: 3 calls × ~14 chars × $0.060/1k ≈ $0.003.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from dataclasses import dataclass

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

import numpy as np
import librosa
import soundfile as sf

OUT_DIR = _THIS.parent / "g3_pretrim_clips"
OUT_DIR.mkdir(exist_ok=True, parents=True)

# Voice: ballad — most consistently clean across G2 and G2c.
# Speed: 1.0 — baseline; the speed variants come at G4.
VOICE = "ballad"
MODEL = "gpt-4o-mini-tts"
SPEED = 1.0

# ── Trim parameters — tuned conservatively to PROTECT the final P ──
# librosa.effects.trim measures energy in dB below the peak. Default
# top_db=60 trims aggressively (cuts anything quieter than 60 dB below
# peak). For wake-word training we want to preserve the trailing
# unvoiced "p" plosive — a brief, low-energy burst that can easily
# fall below 60 dB. We use top_db=40 (less aggressive — keeps
# anything within 40 dB of peak) plus an explicit 50 ms safety pad of
# silence at start AND end after trim, so even if librosa chops too
# close to the plosive, the pad keeps it audible inside the saved clip.
TRIM_TOP_DB = 40
SAFETY_PAD_MS = 50
TARGET_SR = 16_000
MAX_DURATION_S = 2.5   # hard cap to keep training clips reasonable

# Cost guard
HARD_CAP_USD = 0.02


@dataclass
class PhraseSpec:
    name: str          # human-readable label used in filenames
    text: str          # the actual TTS input
    expect_trailing_p: bool  # are we testing P retention on this one?


PHRASES = [
    PhraseSpec("hey_cj",          "Hey CJ.",         False),
    PhraseSpec("hey_see_jay_pee", "Hey see jay pee", True),
    PhraseSpec("see_jay_pee",     "see jay pee",     True),
]

expected_chars = sum(len(p.text) for p in PHRASES)
worst_case = expected_chars / 1000 * 0.060
if worst_case > HARD_CAP_USD:
    print(f"ABORT: ${worst_case:.4f} > cap ${HARD_CAP_USD:.2f}",
          file=sys.stderr)
    sys.exit(1)

print(f"Voice:       {VOICE}  (model={MODEL}, speed={SPEED})")
print(f"Trim:        top_db={TRIM_TOP_DB}, safety_pad={SAFETY_PAD_MS}ms, "
      f"max_dur={MAX_DURATION_S}s")
print(f"Target SR:   {TARGET_SR} Hz")
print(f"Output:      {OUT_DIR.relative_to(_APP_DIR.parent)}")
print(f"Worst-case cost: ${worst_case:.4f}\n")

from openai import OpenAI
client = OpenAI()


def trim_and_resample(raw_path: Path, trimmed_path: Path) -> dict:
    """Apply the G4 audio pipeline to a raw tts WAV.

    Returns a dict of {duration_raw, duration_trimmed, trim_left_ms,
    trim_right_ms, capped} so the caller can show the operator
    exactly how much was chopped from each end.
    """
    # Load + resample to 16 kHz mono float32 in one librosa call.
    y, _ = librosa.load(str(raw_path), sr=TARGET_SR, mono=True)
    duration_raw = len(y) / TARGET_SR

    # Trim silence below TRIM_TOP_DB.
    y_trimmed, idx = librosa.effects.trim(y, top_db=TRIM_TOP_DB)
    trim_left_samples  = idx[0]
    trim_right_samples = len(y) - idx[1]

    # Safety pad: prepend / append SAFETY_PAD_MS of zeros so even if
    # librosa cut too tight to the plosive, the saved WAV still has
    # a clean tail. This is the operator's stated concern.
    pad_samples = int(TARGET_SR * SAFETY_PAD_MS / 1000)
    pad = np.zeros(pad_samples, dtype=y_trimmed.dtype)
    y_final = np.concatenate([pad, y_trimmed, pad])

    # Hard cap: if total length > MAX_DURATION_S, truncate the END.
    # Trimming was already centered on speech, so the END is mostly
    # the safety pad (unlikely to lose speech). Still, log when capped.
    max_samples = int(MAX_DURATION_S * TARGET_SR)
    capped = False
    if len(y_final) > max_samples:
        y_final = y_final[:max_samples]
        capped = True

    duration_trimmed = len(y_final) / TARGET_SR

    # Save as 16 kHz mono 16-bit PCM WAV — openWakeWord's expected format.
    sf.write(str(trimmed_path), y_final, TARGET_SR, subtype="PCM_16")

    return {
        "duration_raw":     duration_raw,
        "duration_trimmed": duration_trimmed,
        "trim_left_ms":     1000 * trim_left_samples / TARGET_SR,
        "trim_right_ms":    1000 * trim_right_samples / TARGET_SR,
        "capped":           capped,
    }


total_chars = 0
total_cost = 0.0
results = []
t_start = time.time()

for spec in PHRASES:
    raw_path     = OUT_DIR / f"{VOICE}_{spec.name}_raw.wav"
    trimmed_path = OUT_DIR / f"{VOICE}_{spec.name}_trimmed.wav"

    # Generate raw WAV from OpenAI API.
    try:
        with client.audio.speech.with_streaming_response.create(
            model=MODEL, voice=VOICE, input=spec.text,
            speed=SPEED, response_format="wav",
        ) as resp:
            resp.stream_to_file(str(raw_path))
    except Exception as e:
        print(f"  [{spec.name}]  GENERATE FAILED: {str(e)[:140]}")
        continue

    cost = len(spec.text) / 1000 * 0.060
    total_chars += len(spec.text)
    total_cost += cost

    # Trim + resample.
    try:
        m = trim_and_resample(raw_path, trimmed_path)
    except Exception as e:
        print(f"  [{spec.name}]  TRIM FAILED: {str(e)[:140]}")
        continue

    p_flag = "  (test P retention)" if spec.expect_trailing_p else ""
    cap_flag = "  ⚠ CAPPED to max" if m["capped"] else ""
    print(f"  [{spec.name:18s}]  "
          f"raw={m['duration_raw']:5.3f}s  "
          f"trimmed={m['duration_trimmed']:5.3f}s  "
          f"L-trim={m['trim_left_ms']:5.1f}ms  "
          f"R-trim={m['trim_right_ms']:5.1f}ms"
          f"{cap_flag}{p_flag}")

    results.append({"name": spec.name, "text": spec.text, **m})

print(f"\nGenerated {len(results)} clip pairs in {OUT_DIR}")
print(f"Cost this run:      ${total_cost:.5f}")
print(f"Elapsed:            {time.time() - t_start:.1f} s\n")

print("─" * 70)
print("Trim parameters used (locked for G4 if approved):")
print(f"  top_db          = {TRIM_TOP_DB}   (lower = more conservative — keeps quieter sounds)")
print(f"  safety_pad      = {SAFETY_PAD_MS}ms  (zero-padding at both ends)")
print(f"  target_sr       = {TARGET_SR} Hz")
print(f"  max_duration    = {MAX_DURATION_S}s  (hard cap, truncates END)")
print()
print("Listening protocol — compare each pair:")
print("  • <voice>_<phrase>_raw.wav      — 24 kHz untrimmed reference")
print("  • <voice>_<phrase>_trimmed.wav  — final G4 pipeline output")
print()
print("Confirm for the two CJP clips:")
print("  - The final 'p' plosive is STILL CLEARLY AUDIBLE in the trimmed version.")
print("  - The clip isn't dragging past ~2s.")
print()
print("If P is intact: reply 'go G4' — I run the full 60-train + 60-val matrix.")
print("If P is clipped: reply 'tighter pad' (more safety) or 'lower top_db' (gentler trim).")
