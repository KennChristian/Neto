"""
PLAN-0008 Task 1 — G4b: adversarial negative WAV generation.

openwakeword's train.py requires negative clips in:
  oww_output/<model_name>/negative_train/
  oww_output/<model_name>/negative_test/

These are normally produced by Piper via `generate_samples(...)` using
adversarial texts from `generate_adversarial_texts(...)`. We don't have
Piper on Windows (per Task 1 §1), so we mirror the same workflow with
OpenAI gpt-4o-mini-tts — same model + voice set + trim pipeline as G4.

Matrix:
  • adversarial texts produced by openwakeword.data.generate_adversarial_texts
    against each of our 3 target phrases (Hey CJ, Hey CJP, CJP)
  • 5 gpt-4o-mini-tts voices (ash, ballad, coral, sage, verse)
  • speed = 1.0 (single speed; the model is learning rejection patterns,
    not voice cadence variation)

Train target: 500 negative clips
Val target:    50 negative clips
Cost estimate: ~$0.33 (well under PLAN-0008 Task 1 budget of $0.50)

Idempotent — re-runs skip files already on disk.
"""

from __future__ import annotations

import os
import random
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
    print("ERROR: OPENAI_API_KEY missing (expected in app/.env)",
          file=sys.stderr)
    sys.exit(1)

import numpy as np
import librosa
import soundfile as sf

# Same trim pipeline as G4 (locked at G3)
TRIM_TOP_DB    = 40
SAFETY_PAD_MS  = 50
TARGET_SR      = 16_000
MAX_DURATION_S = 2.5

# Same model + voice set as G4
MODEL  = "gpt-4o-mini-tts"
VOICES = ("ash", "ballad", "coral", "sage", "verse")
SPEED  = 1.0

# Targets — matching openwakeword train.py's n_samples / n_samples_val
TARGET_TRAIN = 500
TARGET_VAL   = 50

# Same target phrases as in g5_train.py's training_config.yml
TARGET_PHRASES = ["Hey CJ", "Hey CJP", "CJP"]

OUT_BASE      = _THIS.parent / "oww_output" / "hey_cj"
NEG_TRAIN_DIR = OUT_BASE / "negative_train"
NEG_TEST_DIR  = OUT_BASE / "negative_test"
NEG_TRAIN_DIR.mkdir(parents=True, exist_ok=True)
NEG_TEST_DIR.mkdir(parents=True, exist_ok=True)

# Cost guard
HARD_CAP_USD = 0.50
expected_calls = TARGET_TRAIN + TARGET_VAL          # one call per WAV
avg_chars      = 15                                 # phrases run ~10-25 chars
worst_case     = expected_calls * avg_chars / 1000 * 0.060
if worst_case > HARD_CAP_USD:
    print(f"ABORT: worst-case ${worst_case:.4f} > cap ${HARD_CAP_USD:.2f}",
          file=sys.stderr)
    sys.exit(1)

print(f"Target counts: train={TARGET_TRAIN}, val={TARGET_VAL}")
print(f"Voices:        {list(VOICES)}")
print(f"Output:        {OUT_BASE.relative_to(_APP_DIR.parent)}")
print(f"Worst-case cost: ${worst_case:.4f}\n")

# ── Generate adversarial texts ──────────────────────────────────────
print("Generating adversarial texts via openwakeword …")
from openwakeword.data import generate_adversarial_texts

# Need TARGET_TRAIN / len(VOICES) unique texts so 5-voice expansion
# produces the target count.
n_train_unique = (TARGET_TRAIN + len(VOICES) - 1) // len(VOICES)   # = 100
n_val_unique   = (TARGET_VAL   + len(VOICES) - 1) // len(VOICES)   # = 10

# Distribute across target phrases.
n_train_per_phrase = (n_train_unique + len(TARGET_PHRASES) - 1) // len(TARGET_PHRASES)
n_val_per_phrase   = (n_val_unique   + len(TARGET_PHRASES) - 1) // len(TARGET_PHRASES)

train_texts = []
val_texts   = []
for phrase in TARGET_PHRASES:
    train_texts.extend(generate_adversarial_texts(
        input_text=phrase, N=n_train_per_phrase,
        include_partial_phrase=1.0, include_input_words=0.2,
    ))
    val_texts.extend(generate_adversarial_texts(
        input_text=phrase, N=n_val_per_phrase,
        include_partial_phrase=1.0, include_input_words=0.2,
    ))

# Dedup + trim to required count, then shuffle for voice assignment.
random.seed(42)
def _trim_unique(texts, n):
    seen, out = set(), []
    for t in texts:
        if t not in seen:
            seen.add(t); out.append(t)
        if len(out) >= n: break
    return out

train_texts = _trim_unique(train_texts, n_train_unique)
val_texts   = _trim_unique(val_texts,   n_val_unique)
random.shuffle(train_texts); random.shuffle(val_texts)
print(f"Unique adversarial texts: {len(train_texts)} train, {len(val_texts)} val")
print(f"Sample: {train_texts[:5]}\n")

# ── TTS + trim pipeline (identical to g4_generate.py) ──────────────
from openai import OpenAI
client = OpenAI()


def trim_to_16k(raw_path: Path, out_path: Path) -> bool:
    try:
        y, _ = librosa.load(str(raw_path), sr=TARGET_SR, mono=True)
    except Exception as e:
        print(f"  LOAD FAILED [{raw_path.name}]: {str(e)[:120]}")
        return False
    y_t, _ = librosa.effects.trim(y, top_db=TRIM_TOP_DB)
    pad = np.zeros(int(TARGET_SR * SAFETY_PAD_MS / 1000), dtype=y_t.dtype)
    y_f = np.concatenate([pad, y_t, pad])
    max_samples = int(MAX_DURATION_S * TARGET_SR)
    if len(y_f) > max_samples:
        y_f = y_f[:max_samples]
    sf.write(str(out_path), y_f, TARGET_SR, subtype="PCM_16")
    return True


def safe_name(s: str) -> str:
    """Make a filesystem-safe stem from an arbitrary string."""
    return "".join(c if c.isalnum() else "_" for c in s).strip("_")[:60]


RAW_STAGE = OUT_BASE / "_raw_24k_neg"
RAW_STAGE.mkdir(parents=True, exist_ok=True)


def run_phase(label: str, target_dir: Path, texts: list, target_count: int) -> dict:
    print(f"\n── {label}: target {target_count} clips from "
          f"{len(texts)} unique texts × {len(VOICES)} voices ──")
    t0 = time.time()
    n_made = n_skip = 0
    chars = 0
    cost = 0.0
    file_index = 0
    # Fill until we reach target_count by cycling through (text, voice).
    for text in texts:
        for voice in VOICES:
            if file_index >= target_count:
                break
            stem  = f"adv_{file_index:04d}_{voice}_{safe_name(text)}"
            raw_p = RAW_STAGE  / f"{stem}_24k.wav"
            out_p = target_dir / f"{stem}.wav"
            file_index += 1
            if out_p.exists() and raw_p.exists():
                n_skip += 1
                continue
            try:
                if not raw_p.exists():
                    with client.audio.speech.with_streaming_response.create(
                        model=MODEL, voice=voice, input=text,
                        speed=SPEED, response_format="wav",
                    ) as resp:
                        resp.stream_to_file(str(raw_p))
                    chars += len(text)
                    cost  += len(text) / 1000 * 0.060
                trim_to_16k(raw_p, out_p)
                n_made += 1
            except Exception as e:
                print(f"  FAIL [{stem}]: {str(e)[:120]}")
        if file_index >= target_count:
            break

    total_in_dir = sum(1 for _ in target_dir.glob("*.wav"))
    print(f"  New clips written: {n_made}")
    print(f"  Skipped (cached):  {n_skip}")
    print(f"  Total in {target_dir.name}: {total_in_dir}")
    print(f"  Cost this phase:   ${cost:.5f}")
    print(f"  Elapsed:           {(time.time() - t0) / 60:.1f} min")
    return {"made": n_made, "chars": chars, "cost": cost,
            "files": total_in_dir}


train_stats = run_phase("TRAIN", NEG_TRAIN_DIR, train_texts, TARGET_TRAIN)
val_stats   = run_phase("VAL",   NEG_TEST_DIR,  val_texts,   TARGET_VAL)

total_cost = train_stats["cost"] + val_stats["cost"]
print(f"\n{'='*60}")
print(f"G4b COMPLETE")
print(f"{'='*60}")
print(f"  Negative TRAIN clips: {train_stats['files']}")
print(f"  Negative VAL clips:   {val_stats['files']}")
print(f"  Cost this run:        ${total_cost:.5f}")
