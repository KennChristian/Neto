"""
PLAN-0008 Task 1 — Gate 4: full positive-class generation.

Generates the complete training + validation positive corpus for the
custom "Hey CJ / Hey CJP / CJP" wake-word classifier, using
OpenAI gpt-4o-mini-tts (verified at G2 / G2b / G2c as the only
working TTS combination for these phrases) and the silence-trim
pipeline verified at G3.

Output structure follows openWakeWord's expected layout so G5's
train.py invocation plugs straight in:

  app/wake/training/hey_cj/
      positive_train/   ← 60 raw + ~420 augmented = ~480 WAVs
      positive_test/    ← 60 raw (no augmentation — clean val signal)

Per-clip pipeline (locked from G3):
  1. OpenAI gpt-4o-mini-tts → 24 kHz WAV
  2. librosa.load(sr=16_000)  → resample to 16 kHz mono float32
  3. librosa.effects.trim(top_db=40)  → strip silence (conservative)
  4. prepend + append 50 ms safety pad (protect final P plosive)
  5. truncate to ≤ 2.5 s (hard cap on trailing silence)
  6. soundfile.write(subtype="PCM_16")  → openWakeWord-ready

Augmentation matrix (audiomentations, applied to train only — val
stays raw for a clean generalization signal):
  • PitchShift   ±2 semitones        (p=0.7)
  • TimeStretch  0.90–1.10×           (p=0.5)
  • AddGaussianSNR  15–40 dB SNR      (p=0.5)
  7 randomised passes per raw clip   → ≈ 420 augmented + 60 raw

Idempotent — files that already exist are skipped, so re-running
costs nothing in API spend.

Expected cost:
  120 calls × ~12 chars avg × $0.060/1k = ~$0.087
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
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

import numpy as np
import librosa
import soundfile as sf
from audiomentations import (
    AddGaussianSNR, Compose, PitchShift, TimeStretch,
)

# ── Locked configuration ─────────────────────────────────────────────
MODEL = "gpt-4o-mini-tts"
VOICES = ("ash", "ballad", "coral", "sage", "verse")
SPEEDS_TRAIN = (0.85, 1.0, 1.15)
SPEEDS_VAL   = (0.90, 1.0, 1.10)   # slightly offset to avoid identical tts outputs

# Locked at G2c + G3 listening
@dataclass(frozen=True)
class Phrase:
    label: str
    text: str

PHRASES = (
    Phrase("hey_cj",          "Hey CJ."),
    Phrase("hey_see_jay",     "Hey see jay"),
    Phrase("hey_see_jay_pee", "Hey see jay pee"),
    Phrase("see_jay_pee",     "see jay pee"),       # bare CJP trigger
)

# Audio pipeline (locked at G3)
TRIM_TOP_DB    = 40
SAFETY_PAD_MS  = 50
TARGET_SR      = 16_000
MAX_DURATION_S = 2.5

# Augmentation (train only)
N_AUG_PER_RAW = 7
AUGMENT = Compose([
    PitchShift(min_semitones=-2, max_semitones=2, p=0.7),
    TimeStretch(min_rate=0.90, max_rate=1.10, p=0.5),
    AddGaussianSNR(min_snr_in_db=15.0, max_snr_in_db=40.0, p=0.5),
])

# Output directory — matches openWakeWord's expected layout.
# train.py constructs positive_train_output_dir as:
#   <config.output_dir>/<config.model_name>/positive_train
# We pick output_dir = app/wake/training/oww_output/ and
# model_name = hey_cj so the path resolves to
# app/wake/training/oww_output/hey_cj/positive_train/.
MODEL_NAME = "hey_cj"
OWW_OUTPUT_DIR = _THIS.parent / "oww_output"
TRAIN_DIR = OWW_OUTPUT_DIR / MODEL_NAME / "positive_train"
VAL_DIR   = OWW_OUTPUT_DIR / MODEL_NAME / "positive_test"
TRAIN_DIR.mkdir(parents=True, exist_ok=True)
VAL_DIR.mkdir(parents=True, exist_ok=True)

# Cost guard
HARD_CAP_USD = 0.30   # 3× the expected $0.087 — generous safety
n_calls_planned = len(VOICES) * (len(SPEEDS_TRAIN) + len(SPEEDS_VAL)) * len(PHRASES)
avg_chars = sum(len(p.text) for p in PHRASES) / len(PHRASES)
worst_case = n_calls_planned * avg_chars / 1000 * 0.060

if worst_case > HARD_CAP_USD:
    print(f"ABORT: worst-case ${worst_case:.4f} > cap ${HARD_CAP_USD:.2f}",
          file=sys.stderr)
    sys.exit(1)

print(f"Voices:           {list(VOICES)}")
print(f"Phrases:          {[p.label for p in PHRASES]}")
print(f"Speeds (train):   {SPEEDS_TRAIN}")
print(f"Speeds (val):     {SPEEDS_VAL}")
print(f"Per-raw augmentations (train): {N_AUG_PER_RAW}")
print(f"Output:           {OWW_OUTPUT_DIR.relative_to(_APP_DIR.parent)}")
print(f"Planned API calls: {n_calls_planned}  (60 train + 60 val)")
print(f"Worst-case cost:  ${worst_case:.4f}\n")

from openai import OpenAI
client = OpenAI()


def safe_speed_label(speed: float) -> str:
    """0.85 → '0p85' (filesystem-safe)."""
    return f"{speed:.2f}".replace(".", "p")


def generate_raw(
    voice: str, speed: float, text: str, out_path: Path,
) -> bool:
    """API call → 24 kHz raw WAV at out_path. Returns True on success."""
    if out_path.exists():
        return True
    try:
        with client.audio.speech.with_streaming_response.create(
            model=MODEL, voice=voice, input=text,
            speed=speed, response_format="wav",
        ) as resp:
            resp.stream_to_file(str(out_path))
        return True
    except Exception as e:
        print(f"  GENERATE FAILED [{voice} {speed} '{text}']: "
              f"{str(e)[:120]}")
        return False


def trim_and_save(raw_path: Path, out_path: Path) -> bool:
    """Apply the locked G3 pipeline. Overwrites out_path."""
    try:
        y, _ = librosa.load(str(raw_path), sr=TARGET_SR, mono=True)
    except Exception as e:
        print(f"  LOAD FAILED [{raw_path.name}]: {str(e)[:120]}")
        return False
    y_trimmed, _ = librosa.effects.trim(y, top_db=TRIM_TOP_DB)
    pad = np.zeros(int(TARGET_SR * SAFETY_PAD_MS / 1000), dtype=y_trimmed.dtype)
    y_final = np.concatenate([pad, y_trimmed, pad])
    max_samples = int(MAX_DURATION_S * TARGET_SR)
    if len(y_final) > max_samples:
        y_final = y_final[:max_samples]
    sf.write(str(out_path), y_final, TARGET_SR, subtype="PCM_16")
    return True


def augment_and_save(
    src_path: Path, out_dir: Path, base_name: str, n_aug: int,
) -> int:
    """For each raw WAV, write n_aug augmented copies. Returns count
    actually written (skips files that already exist for idempotency)."""
    written = 0
    try:
        y, _ = librosa.load(str(src_path), sr=TARGET_SR, mono=True)
    except Exception as e:
        print(f"  AUG LOAD FAILED [{src_path.name}]: {str(e)[:120]}")
        return 0
    for i in range(n_aug):
        out_path = out_dir / f"{base_name}_aug{i:03d}.wav"
        if out_path.exists():
            written += 1
            continue
        try:
            y_aug = AUGMENT(samples=y, sample_rate=TARGET_SR)
        except Exception as e:
            print(f"  AUG FAILED [{src_path.name} #{i}]: {str(e)[:120]}")
            continue
        sf.write(str(out_path), y_aug, TARGET_SR, subtype="PCM_16")
        written += 1
    return written


# ── Run: train set ───────────────────────────────────────────────────
# We stage the raw 24 kHz files in a subdirectory so we keep the
# originals around for debugging and so re-runs can skip the API.
RAW_STAGE = OWW_OUTPUT_DIR / "_raw_24k"
RAW_STAGE.mkdir(parents=True, exist_ok=True)


def run_phase(label: str, target_dir: Path, speeds: tuple,
              do_augment: bool) -> dict:
    print(f"\n── {label} phase: {len(VOICES)} voices × {len(speeds)} speeds "
          f"× {len(PHRASES)} phrases "
          f"= {len(VOICES) * len(speeds) * len(PHRASES)} raw clips ──")
    t0 = time.time()
    n_api_made = 0
    n_api_skipped = 0
    n_trimmed = 0
    n_augmented = 0
    chars = 0
    cost = 0.0

    for voice in VOICES:
        for speed in speeds:
            for phrase in PHRASES:
                base = (
                    f"{voice}_{safe_speed_label(speed)}_{phrase.label}"
                )
                raw_path = RAW_STAGE / f"{base}_24k.wav"
                # Step 1: API → raw 24 kHz WAV
                if not raw_path.exists():
                    ok = generate_raw(voice, speed, phrase.text, raw_path)
                    if not ok:
                        continue
                    n_api_made += 1
                    chars += len(phrase.text)
                    cost += len(phrase.text) / 1000 * 0.060
                else:
                    n_api_skipped += 1
                # Step 2: trim → 16 kHz final
                final_path = target_dir / f"{base}.wav"
                if not final_path.exists():
                    if trim_and_save(raw_path, final_path):
                        n_trimmed += 1
                else:
                    n_trimmed += 1     # already done in a prior run
                # Step 3: augmentation (train only)
                if do_augment and final_path.exists():
                    n_augmented += augment_and_save(
                        final_path, target_dir, base, N_AUG_PER_RAW,
                    )

    total_files = sum(1 for _ in target_dir.glob("*.wav"))
    print(f"\n  API calls made:        {n_api_made}")
    print(f"  API calls skipped:     {n_api_skipped} (already cached)")
    print(f"  16 kHz trimmed clips:  {n_trimmed}")
    if do_augment:
        print(f"  Augmented variants:    {n_augmented}")
    print(f"  Total files in {target_dir.name}: {total_files}")
    print(f"  Chars billed:          {chars}")
    print(f"  Cost this phase:       ${cost:.5f}")
    print(f"  Elapsed:               {time.time() - t0:.1f} s")
    return {"calls": n_api_made, "chars": chars, "cost": cost,
            "files": total_files}


train_stats = run_phase("TRAIN", TRAIN_DIR, SPEEDS_TRAIN, do_augment=True)
val_stats   = run_phase("VAL",   VAL_DIR,   SPEEDS_VAL,   do_augment=False)

# ── Summary ──────────────────────────────────────────────────────────
total_chars = train_stats["chars"] + val_stats["chars"]
total_cost = train_stats["cost"] + val_stats["cost"]
print(f"\n{'='*60}")
print(f"G4 COMPLETE")
print(f"{'='*60}")
print(f"  TRAIN clips: {train_stats['files']}  "
      f"(in {TRAIN_DIR.relative_to(_APP_DIR.parent)})")
print(f"  VAL clips:   {val_stats['files']}    "
      f"(in {VAL_DIR.relative_to(_APP_DIR.parent)})")
print(f"  Total chars billed (this run): {total_chars}")
print(f"  Cost this run:                 ${total_cost:.5f}")
print()
print("Next: G5 will write the openWakeWord training config pointing at")
print(f"  output_dir = {OWW_OUTPUT_DIR.relative_to(_APP_DIR.parent)}")
print(f"  model_name = {MODEL_NAME}")
print(f"  n_samples  = 500   (≥0.95 × 500 = 475 — train has more than that)")
print(f"  n_samples_val = 50 (val has more than that)")
print()
print("Optional: spot-listen to 2-3 random files in each directory before")
print("kicking off G5 (training takes 30-90 min on CPU).")
