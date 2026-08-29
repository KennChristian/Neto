"""
PLAN-0008 Task 1 — Gate 5: train the Hey-CJ classifier.

Wraps openwakeword.train (the upstream training script) with our
Rung-1 config:

  • Skip Piper generation entirely — positives are already in
    `oww_output/hey_cj/{positive_train,positive_test}/` from G4.
  • feature_data_files points at the G3 1.5 GB negatives slice.
  • false_positive_validation_data_path points at the G3 176 MB
    validation file.
  • total_length=2.5 s — matches G4's max-clip cap so longer
    positives get centre-cropped rather than truncated by the trim.
  • rir_paths and background_paths empty — augment_clips() degrades
    to a passthrough that only enforces total_length padding.
  • steps=10000 (vs upstream default 50000) — Rung 1 quick model.
  • target_false_positives_per_hour=0.5 (vs upstream 0.2) — relaxed
    because we trained on a 9.3 % negative slice (Rung 1 trade).

End-to-end: --augment_clips → --train_model → ONNX export.
The exported file goes into:
  app/wake/training/oww_output/hey_cj/hey_cj.onnx

After training we copy it into:
  app/wake/models/hey_cj.onnx
which is the path the WakeWordEngine constructor takes as a
custom-model file (already designed for at Task 0).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import yaml

_THIS = Path(__file__).resolve()
_APP_DIR = _THIS.parents[2]
_REPO_ROOT = _APP_DIR.parent

# All paths in the YAML are ABSOLUTE so the train.py invocation
# resolves them regardless of cwd.
OWW_OUTPUT_DIR = _THIS.parent / "oww_output"
OWW_DATA_DIR   = _THIS.parent / "oww_data"
MODEL_NAME = "hey_cj"
NEG_SLICE = OWW_DATA_DIR / "openwakeword_features_ACAV100M_1p5GB_sliced.npy"
VAL_FILE  = OWW_DATA_DIR / "validation_set_features.npy"
TRAINING_CONFIG_PATH = _THIS.parent / "training_config.yml"

# Final output destination — the committed model file.
FINAL_MODEL_DIR = _APP_DIR / "wake" / "models"
FINAL_MODEL_PATH = FINAL_MODEL_DIR / "hey_cj.onnx"
FINAL_MODEL_DIR.mkdir(parents=True, exist_ok=True)


def write_config() -> Path:
    """Write the training_config.yml with absolute paths."""
    cfg = {
        "model_name": MODEL_NAME,
        # target_phrase is consulted by train.py only for the
        # skip-Piper count check (n_current_samples vs n_samples).
        # The strings here aren't actually rendered — the positives
        # are pre-populated.
        "target_phrase": ["Hey CJ", "Hey CJP", "CJP"],
        "custom_negative_phrases": [],

        # Pre-population: we have 480 train positives + 455 train
        # negatives (455 = 91 unique adversarial texts × 5 voices);
        # 60 val positives + 50 val negatives. Skip check is
        # 0.95 × n_samples; setting n_samples=450 means threshold
        # = 427.5, both positives (480) and negatives (455) clear it.
        "n_samples":     450,
        "n_samples_val":  50,

        # tts batch sizes are unused (no Piper call). Keep harmless.
        "tts_batch_size": 50,
        "augmentation_batch_size": 16,

        # Piper path is unused but train.py reads it.
        "piper_sample_generator_path": "",

        # Output / data paths — all absolute.
        "output_dir":  str(OWW_OUTPUT_DIR),
        "rir_paths":   [],
        "background_paths": [],
        "background_paths_duplication_rate": [],

        "false_positive_validation_data_path": str(VAL_FILE),
        "augmentation_rounds": 1,

        "feature_data_files": {
            "ACAV100M_sample": str(NEG_SLICE),
        },

        "batch_n_per_class": {
            "ACAV100M_sample": 1024,
            "adversarial_negative": 50,
            "positive": 50,
        },

        # Rung-1 minimal: small DNN, fewer steps, relaxed FP target
        "model_type": "dnn",
        "layer_size": 32,
        "steps": 10000,
        "max_negative_weight": 1500,
        "target_false_positives_per_hour": 0.5,

        # Total-length budget matches our G4 cap.
        "total_length": 2.5,
    }
    TRAINING_CONFIG_PATH.write_text(
        yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8"
    )
    print(f"Wrote training config: {TRAINING_CONFIG_PATH}")
    return TRAINING_CONFIG_PATH


def sanity_check_prereqs() -> bool:
    train_dir = OWW_OUTPUT_DIR / MODEL_NAME / "positive_train"
    val_dir   = OWW_OUTPUT_DIR / MODEL_NAME / "positive_test"
    n_train = len(list(train_dir.glob("*.wav"))) if train_dir.exists() else 0
    n_val   = len(list(val_dir.glob("*.wav")))   if val_dir.exists()   else 0
    ok_train = n_train >= int(0.95 * 500)
    ok_val   = n_val   >= int(0.95 * 50)
    ok_neg = NEG_SLICE.exists() and NEG_SLICE.stat().st_size > 100_000_000
    ok_val_npy = VAL_FILE.exists() and VAL_FILE.stat().st_size > 100_000_000

    print("Sanity check:")
    print(f"  Train clips ({train_dir.name}): {n_train}  "
          f"[need >= 475]  {'OK' if ok_train else 'FAIL'}")
    print(f"  Val clips   ({val_dir.name}):   {n_val}    "
          f"[need >= 47]   {'OK' if ok_val else 'FAIL'}")
    print(f"  Negatives slice: {NEG_SLICE.exists()} "
          f"({NEG_SLICE.stat().st_size / 1024**2:.1f} MB) "
          f"{'OK' if ok_neg else 'FAIL'}")
    print(f"  Validation set: {VAL_FILE.exists()} "
          f"({VAL_FILE.stat().st_size / 1024**2:.1f} MB) "
          f"{'OK' if ok_val_npy else 'FAIL'}")
    return all([ok_train, ok_val, ok_neg, ok_val_npy])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--steps", type=int, default=None,
        help="Override steps in config (default = config's value)",
    )
    parser.add_argument(
        "--write-config-only", action="store_true",
        help="Generate the config YAML and exit; don't train.",
    )
    args = parser.parse_args()

    print("=" * 70)
    print("G5 — Hey-CJ classifier training")
    print("=" * 70)
    print(f"  Python:   {sys.executable}")
    print(f"  Config:   {TRAINING_CONFIG_PATH.relative_to(_REPO_ROOT)}")
    print(f"  Output:   {OWW_OUTPUT_DIR.relative_to(_REPO_ROOT)}/{MODEL_NAME}")
    print(f"  Final model destination: {FINAL_MODEL_PATH.relative_to(_REPO_ROOT)}")
    print()

    if not sanity_check_prereqs():
        print("\nFAIL: prereqs not in place. Re-run G3 / G4 if needed.")
        return 1

    # openwakeword pip package ships zero ONNX models — the training
    # pipeline needs melspectrogram.onnx + embedding_model.onnx to
    # compute features from our pre-populated WAV positives. Idempotent:
    # download_models() skips files already present.
    print("Ensuring openwakeword feature/VAD models are on disk …")
    try:
        from openwakeword.utils import download_models
        download_models()
    except Exception as e:
        print(f"  WARNING: download_models raised {type(e).__name__}: {e}")
        print("  Continuing — training will fail loud if files are missing.")

    write_config()
    if args.write_config_only:
        print("Wrote config only; exiting.")
        return 0

    # Invoke openwakeword.train via -m so its own argparse + main run.
    # We pass both --augment_clips and --train_model so it does the
    # full pipeline in one shot.
    import subprocess
    cmd = [
        sys.executable, "-m", "openwakeword.train",
        "--training_config", str(TRAINING_CONFIG_PATH),
        "--augment_clips",
        "--train_model",
    ]
    print("Invoking:", " ".join(cmd))
    print("-" * 70)
    t0 = time.time()
    # Stream subprocess output line-by-line so progress shows in the
    # background-task log file as it happens.
    # Force UTF-8 + replace-on-error so the subprocess's emoji-laced
    # output (e.g. torch.onnx's ✅) doesn't crash this parent while
    # the subprocess is still running.
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, encoding="utf-8", errors="replace",
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
    rc = proc.wait()
    print("-" * 70)
    print(f"openwakeword.train returned exit code {rc}")
    print(f"Total elapsed: {(time.time() - t0) / 60:.1f} min")

    if rc != 0:
        print("FAIL: training step exited with non-zero code.")
        return rc

    # Locate the produced ONNX. The upstream notebook saves to
    # `<output_dir>/<model_name>.onnx`. Defensively search a few places.
    candidates = [
        OWW_OUTPUT_DIR / f"{MODEL_NAME}.onnx",
        OWW_OUTPUT_DIR / MODEL_NAME / f"{MODEL_NAME}.onnx",
        OWW_OUTPUT_DIR / MODEL_NAME / "model.onnx",
    ]
    onnx_path = next((p for p in candidates if p.exists()), None)
    if onnx_path is None:
        print("\nWARNING: trained ONNX not found at expected paths.")
        print("Searching output_dir for any .onnx file …")
        found = list(OWW_OUTPUT_DIR.rglob("*.onnx"))
        if found:
            print(f"  Found: {[str(p.relative_to(_REPO_ROOT)) for p in found]}")
            onnx_path = max(found, key=lambda p: p.stat().st_mtime)
            print(f"  Using newest: {onnx_path.relative_to(_REPO_ROOT)}")
        else:
            print("  No .onnx file produced. Training likely failed.")
            return 2

    # Copy the trained model into app/wake/models/.
    print()
    print(f"Copying {onnx_path.name} → {FINAL_MODEL_PATH.relative_to(_REPO_ROOT)}")
    shutil.copy2(onnx_path, FINAL_MODEL_PATH)
    print(f"Final model size: {FINAL_MODEL_PATH.stat().st_size / 1024:.1f} kB")

    # Quick sanity-load: open the ONNX with onnxruntime and report
    # input/output names — that's all the engine needs to use it.
    try:
        import onnxruntime as ort
        sess = ort.InferenceSession(
            str(FINAL_MODEL_PATH),
            providers=["CPUExecutionProvider"],
        )
        ins = [(i.name, i.shape) for i in sess.get_inputs()]
        outs = [(o.name, o.shape) for o in sess.get_outputs()]
        print(f"  ONNX inputs:  {ins}")
        print(f"  ONNX outputs: {outs}")
    except Exception as e:
        print(f"  WARNING: ONNX runtime load check failed: {e}")

    print()
    print("=" * 70)
    print("G5 COMPLETE — proceed to G6 (verification via wake_test.py)")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
