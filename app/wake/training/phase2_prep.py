"""Phase 2 prep — fold real-voice positives into the openWakeWord training set.

Inputs:
  app/wake/data/real_split/heycj_male1_clean/*.wav   (28 clips, 16 kHz mono 16-bit)
  app/wake/data/real_split/heycj_male2_clean/*.wav   (29 clips)

Strategy (matches operator brief):
  • Hold out 4 clips per speaker as a real-voice VAL set
      → 8 clips total, copied verbatim to positive_test/ with
        a "real_<speaker>_<idx>.wav" filename so phase2_eval can
        find them later.
  • Augment the remaining 24 + 25 = 49 clips with the SAME
    audiomentations stack as g4_generate.py:
      PitchShift   ±2 st           (p=0.7)
      TimeStretch  0.90 – 1.10×    (p=0.5)
      AddGaussianSNR  15 – 40 dB   (p=0.5)
    7 augmented passes per raw clip → 49 raw + 343 aug = 392 new train clips.
  • Speed-aug note: the TTS stack already centres at 1.0×; the brief asked
    we don't drift slow. 0.90 is the lower edge — kept as-is for parity
    with the TTS positives so the only changed variable between v1 and v2
    is the real voices being added.

Speed-safety pad: each raw real clip is 0.58–0.93 s; after TimeStretch the
slowest case (× 0.90) lands at < 1.04 s, still well below the 2.5 s
total_length cap that train.py enforces.

After the WAVs are written, the cached positive_features_*.npy files are
deleted so the trainer re-encodes the union of TTS + real positives.

NOT done here: training. NOT done here: deletion of any existing TTS clip.
This pass changes EXACTLY ONE variable — added real voices.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
import librosa
import soundfile as sf
from audiomentations import (
    AddGaussianSNR, Compose, PitchShift, TimeStretch,
)


_THIS = Path(__file__).resolve()
REAL_SPLIT = _THIS.parents[1] / "data" / "real_split"
OWW_OUT = _THIS.parent / "oww_output" / "hey_cj"
TRAIN_DIR = OWW_OUT / "positive_train"
VAL_DIR   = OWW_OUT / "positive_test"

SPEAKERS = ("heycj_male1_clean", "heycj_male2_clean")
HOLDOUT_IDX = (3, 10, 17, 24)   # 4 evenly-spaced indices per speaker
N_AUG_PER_RAW = 7
TARGET_SR = 16_000

# Augmentation matrix — identical to g4_generate.py so the only
# v1 → v2 variable change is the source of the positives.
AUGMENT = Compose([
    PitchShift(min_semitones=-2, max_semitones=2, p=0.7),
    TimeStretch(min_rate=0.90, max_rate=1.10, p=0.5),
    AddGaussianSNR(min_snr_in_db=15.0, max_snr_in_db=40.0, p=0.5),
])

# Files whose presence in positive_train/ implies stale cache; deleted
# at the end so train.py recomputes positive_features_*.npy.
CACHE_FILES = [
    OWW_OUT / "positive_features_train.npy",
    OWW_OUT / "positive_features_test.npy",
]


def load_16k_mono(p: Path) -> np.ndarray:
    """Load WAV → float32 mono at 16 kHz. The splitter already wrote
    16 kHz mono PCM_16, so this is essentially a fast no-op resample,
    but we go through librosa to normalise dtype to float32 in [-1, 1]."""
    y, _ = librosa.load(str(p), sr=TARGET_SR, mono=True)
    return y


def write_wav(p: Path, y: np.ndarray) -> None:
    sf.write(str(p), y, TARGET_SR, subtype="PCM_16")


def main() -> int:
    if not REAL_SPLIT.exists():
        print(f"FAIL: {REAL_SPLIT} not found — run phase1_split.py first.")
        return 1
    if not TRAIN_DIR.exists() or not VAL_DIR.exists():
        print(f"FAIL: expected {TRAIN_DIR} and {VAL_DIR} — run g4_generate.py first.")
        return 1

    print("=" * 70)
    print("Phase 2 prep — fold real-voice positives into training set")
    print("=" * 70)

    # Snapshot prior counts so the report at the end is clean.
    n_train_before = len(list(TRAIN_DIR.glob("*.wav")))
    n_val_before   = len(list(VAL_DIR.glob("*.wav")))
    print(f"  positive_train (before): {n_train_before}")
    print(f"  positive_test  (before): {n_val_before}")
    print(f"  holdout indices per speaker: {HOLDOUT_IDX}")
    print(f"  N_AUG_PER_RAW: {N_AUG_PER_RAW}")
    print(f"  augmentation stack:")
    print(f"    PitchShift   ±2 st        (p=0.7)")
    print(f"    TimeStretch  0.90 – 1.10× (p=0.5)")
    print(f"    AddGaussianSNR 15 – 40 dB (p=0.5)")

    total_val_added = 0
    total_train_raw_added = 0
    total_train_aug_added = 0
    per_speaker = {}

    for speaker in SPEAKERS:
        src_dir = REAL_SPLIT / speaker
        if not src_dir.exists():
            print(f"\n  WARN: {src_dir} missing — skipping speaker.")
            continue

        all_clips = sorted(src_dir.glob("*.wav"))
        n_total = len(all_clips)
        print(f"\n── speaker: {speaker} (raw clips: {n_total}) ──")

        # Build held-out set from HOLDOUT_IDX (clipped to actual length).
        holdout_idx = [i for i in HOLDOUT_IDX if i < n_total]
        train_idx = [i for i in range(n_total) if i not in holdout_idx]

        per_speaker[speaker] = {
            "n_total":   n_total,
            "n_holdout": len(holdout_idx),
            "n_train":   len(train_idx),
            "holdout_idx": holdout_idx,
        }

        # ── VAL: 4 held-out clips, no augmentation ──
        for i in holdout_idx:
            src = all_clips[i]
            dst = VAL_DIR / f"real_{speaker}_{i:02d}.wav"
            if dst.exists():
                print(f"    (val skip exists) {dst.name}")
                continue
            y = load_16k_mono(src)
            write_wav(dst, y)
            total_val_added += 1
        print(f"  held out → positive_test/ : {len(holdout_idx)} clips "
              f"(indices {holdout_idx})")

        # ── TRAIN: remaining clips + 7× augmentations each ──
        n_raw_added_this_speaker = 0
        n_aug_added_this_speaker = 0
        for i in train_idx:
            src = all_clips[i]
            base = f"real_{speaker}_{i:02d}"
            y = load_16k_mono(src)

            # 1. raw real clip
            raw_dst = TRAIN_DIR / f"{base}.wav"
            if not raw_dst.exists():
                write_wav(raw_dst, y)
                n_raw_added_this_speaker += 1

            # 2. 7 augmented variants
            for aug_i in range(N_AUG_PER_RAW):
                aug_dst = TRAIN_DIR / f"{base}_aug{aug_i:03d}.wav"
                if aug_dst.exists():
                    continue
                try:
                    y_aug = AUGMENT(samples=y, sample_rate=TARGET_SR)
                except Exception as e:
                    print(f"    AUG FAIL {base} #{aug_i}: "
                          f"{type(e).__name__}: {str(e)[:100]}")
                    continue
                write_wav(aug_dst, y_aug)
                n_aug_added_this_speaker += 1

        print(f"  added → positive_train/ : "
              f"{n_raw_added_this_speaker} raw + "
              f"{n_aug_added_this_speaker} aug "
              f"= {n_raw_added_this_speaker + n_aug_added_this_speaker} new clips")
        total_train_raw_added += n_raw_added_this_speaker
        total_train_aug_added += n_aug_added_this_speaker

    # ── Invalidate the feature caches so train.py re-encodes ──
    print()
    print("── Invalidating stale positive feature caches ──")
    for p in CACHE_FILES:
        if p.exists():
            sz = p.stat().st_size
            p.unlink()
            print(f"  deleted: {p.relative_to(_THIS.parents[2].parent)} "
                  f"({sz / 1024:.1f} kB)")
        else:
            print(f"  not present: {p.name}")

    # ── Final counts ──
    n_train_after = len(list(TRAIN_DIR.glob("*.wav")))
    n_val_after   = len(list(VAL_DIR.glob("*.wav")))

    print()
    print("=" * 70)
    print("Phase 2 prep summary")
    print("=" * 70)
    for speaker, st in per_speaker.items():
        print(f"  {speaker}: total={st['n_total']}, "
              f"holdout={st['n_holdout']}, train_raw={st['n_train']}")
    print()
    print(f"  positive_train: {n_train_before} → {n_train_after}  "
          f"(+{n_train_after - n_train_before}: "
          f"{total_train_raw_added} raw + {total_train_aug_added} aug)")
    print(f"  positive_test:  {n_val_before} → {n_val_after}  "
          f"(+{n_val_after - n_val_before})")
    print()
    print(f"  Real-voice positives added (train): "
          f"{total_train_raw_added} raw + {total_train_aug_added} aug")
    print(f"  Real-voice positives added (val, held out): "
          f"{total_val_added}")
    print()
    print("Next: run g5_train.py to retrain. Cached positive_features_*.npy")
    print("were deleted so train.py will re-encode the union of TTS + real.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
