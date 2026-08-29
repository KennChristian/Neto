"""Quick smoke check that the custom hey_cj.onnx loads in the
kiosk venv via openWakeWord and runs inference on a dummy frame.

If this passes, wake_test.py with "Custom — Hey CJ" selected should
also load — confirming Task 1's runtime integration before the
human-in-the-loop recall/FP testing in G6.

Run via the KIOSK venv (app/.venv/), not the training venv:
    .\\app\\.venv\\Scripts\\Activate.ps1
    python app\\wake\\training\\g6_smoke.py
"""

from __future__ import annotations
import sys
from pathlib import Path

# Force UTF-8 + ensure-models downloaded first
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

_THIS = Path(__file__).resolve()
_APP_DIR = _THIS.parents[2]
sys.path.insert(0, str(_APP_DIR))

ONNX_PATH = _APP_DIR / "wake" / "models" / "hey_cj.onnx"
if not ONNX_PATH.exists():
    print(f"FAIL: trained model not found at {ONNX_PATH}")
    sys.exit(1)

print(f"Custom model: {ONNX_PATH}")
print(f"  size: {ONNX_PATH.stat().st_size:,} bytes")

# Verify the shared feature models are on disk; skip download if so.
import openwakeword
_owww_resources = Path(openwakeword.__file__).parent / "resources" / "models"
_required = ["melspectrogram.onnx", "embedding_model.onnx"]
_missing = [f for f in _required if not (_owww_resources / f).exists()]
if _missing:
    print(f"  Need to fetch shared feature models: {_missing}")
    from openwakeword.utils import download_models
    download_models()
else:
    print(f"  Shared feature models already on disk at "
          f"{_owww_resources.name}/, skipping download.")

print("\nLoading openWakeWord Model …")
from openwakeword.model import Model
m = Model(
    wakeword_models=[str(ONNX_PATH)],
    inference_framework="onnx",
)
print(f"  Loaded. m.models keys: {list(m.models.keys())}")

# Run a silence and a noise frame through it.
import numpy as np
silence = np.zeros(1280, dtype=np.int16)
noise = (np.random.randn(1280) * 10000).astype(np.int16)

print("\nInference test:")
preds_silence = m.predict(silence)
preds_noise = m.predict(noise)
print(f"  silence  → {preds_silence}")
print(f"  noise    → {preds_noise}")

if not preds_silence:
    print("FAIL: predict() returned empty dict")
    sys.exit(1)

key = next(iter(preds_silence.keys()))
print(f"\nThe prediction key for our custom model is: {key!r}")
print(f"This is what engine.py needs to read — Task 0's engine "
      f"fallback (next(iter(preds.values()))) handles it correctly.")

# Test via our WakeWordEngine class to confirm path acceptance.
print("\nVerifying via wake.engine.WakeWordEngine …")
from wake.engine import WakeWordEngine
try:
    eng = WakeWordEngine(model_name=str(ONNX_PATH), threshold=0.5)
    print(f"  WakeWordEngine constructed with custom path. "
          f"model_name field: {eng.model_name!r}")
except Exception as e:
    print(f"  FAIL: {type(e).__name__}: {e}")
    sys.exit(1)

print("\n" + "=" * 60)
print("G6 SMOKE OK — model loads, predicts, engine accepts path.")
print("Next: run `streamlit run app/wake_test.py`, pick the")
print('"Custom — Hey CJ / Hey CJP / CJP" entry from the dropdown,')
print("press Start, then run the recall + FP test sets.")
print("=" * 60)
