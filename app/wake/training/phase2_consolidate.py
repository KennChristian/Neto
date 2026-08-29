"""Consolidate the split ONNX (hey_cj.onnx + hey_cj.onnx.data) into one file.

openwakeword.train writes the trained classifier as a split ONNX with
external-data weights:
    oww_output/hey_cj.onnx        ← small graph stub (~15 kB)
    oww_output/hey_cj.onnx.data   ← external weights (~200 kB)

The kiosk runtime loads the ONNX by absolute path and the engine
package wants ONE self-contained file. We reload it with onnx.load and
re-save with save_as_external_data=False so all weights inline into a
single ~215 kB file, then copy it to app/wake/models/hey_cj.onnx.

This was done by hand during v1; lifting it into the pipeline so v2
(and any later retrain) needs only a single command after training.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import onnx
import onnxruntime as ort


_THIS = Path(__file__).resolve()
SRC = _THIS.parent / "oww_output" / "hey_cj.onnx"
DST = _THIS.parents[1] / "models" / "hey_cj.onnx"


def main() -> int:
    if not SRC.exists():
        print(f"FAIL: source ONNX not found at {SRC}")
        return 1

    src_size = SRC.stat().st_size
    data_blob = SRC.with_suffix(".onnx.data")
    data_size = data_blob.stat().st_size if data_blob.exists() else 0
    print(f"Source:   {SRC.relative_to(_THIS.parents[2].parent)} "
          f"({src_size / 1024:.1f} kB)")
    if data_blob.exists():
        print(f"+weights: {data_blob.relative_to(_THIS.parents[2].parent)} "
              f"({data_size / 1024:.1f} kB)")

    print("Loading + consolidating …")
    # onnx.load with external data resolves the .onnx.data blob from
    # the same directory automatically — that's why we pass the full
    # path, so resolution works.
    model = onnx.load(str(SRC))

    DST.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(DST), save_as_external_data=False)
    dst_size = DST.stat().st_size
    print(f"Wrote:    {DST.relative_to(_THIS.parents[2].parent)} "
          f"({dst_size / 1024:.1f} kB)")

    # Validate by opening with onnxruntime and reporting I/O shape.
    print("Validating self-contained ONNX with onnxruntime …")
    sess = ort.InferenceSession(
        str(DST), providers=["CPUExecutionProvider"],
    )
    for inp in sess.get_inputs():
        print(f"  input:  name={inp.name!r}  shape={inp.shape}  type={inp.type}")
    for out in sess.get_outputs():
        print(f"  output: name={out.name!r}  shape={out.shape}  type={out.type}")

    print()
    print("OK — consolidated ONNX is ready for the kiosk runtime.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
