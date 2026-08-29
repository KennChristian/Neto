"""
PLAN-0008 Task 1 — Gate 3 download.

Downloads:
  1. A 1.5 GB byte-range slice of the openWakeWord negatives features
     file from HuggingFace LFS, then rewrites the NumPy header so the
     result is a valid standalone .npy of the slice.
  2. The full 176 MB validation features file.

Properties:
  * Resumable. If the slice download is interrupted, re-running picks
    up where it left off using the Range: bytes=<N>- header.
  * Hard-capped. We refuse to download more than `MAX_BYTES` regardless
    of any header confusion — protection against silently pulling the
    full 16.5 GB.
  * Idempotent. Files that exist with the expected size are skipped.
  * Verified. After download, np.load(..., mmap_mode='r') is called on
    each file and the shape is reported. If verification fails the
    file is renamed with a .bad suffix and the run aborts.
"""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import requests

# ── Slice plan from g3_verify_range.py (locked) ──────────────────────
NEG_URL = ("https://huggingface.co/datasets/davidscripka/openwakeword_features"
           "/resolve/main/openwakeword_features_ACAV100M_2000_hrs_16bit.npy")
NEG_HEADER_BYTES = 128                    # offset where data starts
NEG_BYTES_PER_ROW = 3072                  # 16 × 96 × 2 (float16)
NEG_ROWS_FULL = 5_625_000                 # full-file row count
NEG_ROWS_SLICE = 524_287                  # ≈ 1.5 GB worth of rows
NEG_DTYPE = "float16"
NEG_SHAPE_TAIL = (16, 96)                 # everything after axis 0
NEG_BYTES_TO_DOWNLOAD = (
    NEG_HEADER_BYTES + NEG_ROWS_SLICE * NEG_BYTES_PER_ROW
)

VAL_URL = ("https://huggingface.co/datasets/davidscripka/openwakeword_features"
           "/resolve/main/validation_set_features.npy")
VAL_EXPECTED_BYTES = 184_836_608          # 176.24 MB

# ── Hard safety cap. Refuse to download more than 2 GB even if
#    something goes wrong. Protects against accidentally streaming
#    the full 16.5 GB file. ────────────────────────────────────────
MAX_BYTES = 2_000_000_000

_THIS = Path(__file__).resolve()
OUT_DIR = _THIS.parent / "oww_data"
OUT_DIR.mkdir(parents=True, exist_ok=True)
NEG_PATH = OUT_DIR / "openwakeword_features_ACAV100M_1p5GB_sliced.npy"
VAL_PATH = OUT_DIR / "validation_set_features.npy"

# Stream chunks of 4 MB and print one progress line every ~10 s so the
# operator (and a tail-on-the-output-file) can see progress without
# spamming.
CHUNK_BYTES = 4 * 1024 * 1024
PROGRESS_EVERY_SEC = 10.0


def fmt_mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB"


def fmt_dur(s: float) -> str:
    if s < 60:
        return f"{s:.0f}s"
    if s < 3600:
        return f"{s / 60:.1f} min"
    return f"{s / 3600:.1f} h"


def download_range(
    url: str, dest: Path, start: int, end: int, label: str,
) -> bool:
    """Download bytes [start, end] inclusive into dest, supporting resume.

    If dest already has >= (end - start + 1) bytes from a previous run,
    we skip the network entirely.
    """
    target_total = end - start + 1
    already = dest.stat().st_size if dest.exists() else 0

    if already >= target_total:
        print(f"  [{label}] already complete ({fmt_mb(already)}). Skipping.")
        return True

    # Safety cap on total download.
    if target_total - already > MAX_BYTES:
        print(f"  [{label}] FAIL: would download {fmt_mb(target_total - already)} "
              f"which exceeds safety cap {fmt_mb(MAX_BYTES)}.")
        return False

    # Resume from `already` bytes — request the remainder via Range.
    abs_start = start + already
    range_header = f"bytes={abs_start}-{end}"
    print(f"  [{label}] requesting {range_header}  "
          f"(total target {fmt_mb(target_total)}, already on disk {fmt_mb(already)})")

    t0 = time.time()
    last_progress = t0
    bytes_received = 0

    with requests.get(url, headers={"Range": range_header},
                      stream=True, timeout=60) as resp:
        if resp.status_code not in (200, 206):
            print(f"  [{label}] FAIL: HTTP {resp.status_code}")
            return False
        # Server's view of what it's about to send.
        srv_content_range = resp.headers.get("Content-Range", "(missing)")
        srv_content_length = resp.headers.get("Content-Length", "(missing)")
        print(f"  [{label}] server status={resp.status_code}  "
              f"Content-Length={srv_content_length}  "
              f"Content-Range={srv_content_range}")

        # Open in append mode for resume; truncate to `already` first
        # to discard any stale tail from a previous failed run.
        with open(dest, "ab") as f:
            f.truncate(already)
            for chunk in resp.iter_content(chunk_size=CHUNK_BYTES):
                if not chunk:
                    continue
                f.write(chunk)
                bytes_received += len(chunk)
                now = time.time()
                if now - last_progress >= PROGRESS_EVERY_SEC:
                    last_progress = now
                    on_disk = already + bytes_received
                    pct = 100 * on_disk / target_total
                    elapsed = now - t0
                    rate_mb_s = bytes_received / elapsed / 1024 / 1024 if elapsed else 0
                    remaining = target_total - on_disk
                    eta = remaining / (bytes_received / elapsed) if elapsed else 0
                    print(f"  [{label}] {on_disk / 1024 / 1024:7.1f} MB / "
                          f"{target_total / 1024 / 1024:7.1f} MB  "
                          f"({pct:5.1f}%)  "
                          f"{rate_mb_s:.2f} MB/s  "
                          f"ETA {fmt_dur(eta)}")
                # Bail if a corrupted server pushes more than we asked for.
                if bytes_received + already > target_total:
                    print(f"  [{label}] FAIL: server overran target by "
                          f"{bytes_received + already - target_total} bytes.")
                    return False

    final = dest.stat().st_size
    print(f"  [{label}] done. {fmt_mb(final)} on disk. "
          f"Elapsed {fmt_dur(time.time() - t0)}.")
    return final >= target_total


def patch_npy_header(path: Path, new_shape: tuple, dtype: str) -> bool:
    """Rewrite the .npy header so the file declares the new shape.

    The header is the first 128 bytes (NumPy v1.0). Format:
      6 magic bytes + 2 version + 2 header-length + header-text +
      padding-with-spaces + newline
    Total header is always a multiple of 64 bytes (so first row of data
    is aligned). We preserve this alignment by padding with spaces.
    """
    header_dict_str = (
        "{'descr': '<%s', 'fortran_order': False, 'shape': %r, }"
        % ({"float16": "f2", "float32": "f4"}[dtype], tuple(new_shape))
    )
    # The header text must end with a newline and total prefix (10
    # bytes magic+ver+len) + header_text must be 64-aligned.
    prefix_bytes = 10  # 6 magic + 1 ver_major + 1 ver_minor + 2 header_len
    body_min = len(header_dict_str) + 1   # +1 for the trailing newline
    total_min = prefix_bytes + body_min
    aligned = ((total_min + 63) // 64) * 64
    pad_spaces = aligned - prefix_bytes - body_min
    header_body = (header_dict_str + " " * pad_spaces + "\n").encode("latin1")

    new_header = (
        b"\x93NUMPY"
        + bytes([1, 0])
        + len(header_body).to_bytes(2, "little")
        + header_body
    )
    if len(new_header) > 128:
        print(f"  ERROR: patched header is {len(new_header)} bytes, "
              f"won't fit in 128-byte slot.")
        return False
    # Pad to 128 with extra spaces if needed (keeping alignment).
    # In practice for our shape (524287, 16, 96) the header is well
    # under 128 bytes.
    if len(new_header) < 128:
        # Re-align: bump body up so total = 128.
        extra = 128 - len(new_header)
        header_body = (
            header_dict_str + " " * (pad_spaces + extra - 1) + "\n"
        ).encode("latin1")
        new_header = (
            b"\x93NUMPY" + bytes([1, 0])
            + len(header_body).to_bytes(2, "little") + header_body
        )

    assert len(new_header) == 128, len(new_header)
    with open(path, "r+b") as f:
        f.seek(0)
        f.write(new_header)
    print(f"  Patched header: shape={new_shape}, total={len(new_header)} bytes")
    return True


# ── Step 1: download the negatives slice ────────────────────────────
print("=" * 70)
print(f"Step 1 — download negatives slice ({fmt_mb(NEG_BYTES_TO_DOWNLOAD)})")
print("=" * 70)

# Bytes 0 through NEG_BYTES_TO_DOWNLOAD - 1 (inclusive).
ok = download_range(
    NEG_URL, NEG_PATH,
    start=0, end=NEG_BYTES_TO_DOWNLOAD - 1,
    label="negatives",
)
if not ok:
    print("Negatives download failed; aborting.")
    sys.exit(1)

print()
print("Patching .npy header to declare slice shape …")
ok = patch_npy_header(
    NEG_PATH, (NEG_ROWS_SLICE,) + NEG_SHAPE_TAIL, NEG_DTYPE,
)
if not ok:
    sys.exit(1)

# Verify by loading.
print("Verifying with np.load(mmap_mode='r') …")
try:
    arr = np.load(str(NEG_PATH), mmap_mode="r")
    print(f"  Loaded OK: shape={arr.shape}, dtype={arr.dtype}, "
          f"first-row mean={float(np.asarray(arr[0]).mean()):.4f}")
    expected_shape = (NEG_ROWS_SLICE,) + NEG_SHAPE_TAIL
    if tuple(arr.shape) != expected_shape:
        print(f"  FAIL: expected shape {expected_shape}")
        sys.exit(1)
except Exception as e:
    print(f"  FAIL: np.load raised {type(e).__name__}: {e}")
    NEG_PATH.rename(NEG_PATH.with_suffix(".npy.bad"))
    sys.exit(1)

# ── Step 2: download the full validation file ───────────────────────
print()
print("=" * 70)
print(f"Step 2 — download validation file (full, {fmt_mb(VAL_EXPECTED_BYTES)})")
print("=" * 70)

ok = download_range(
    VAL_URL, VAL_PATH,
    start=0, end=VAL_EXPECTED_BYTES - 1,
    label="validation",
)
if not ok:
    sys.exit(1)

print("Verifying with np.load(mmap_mode='r') …")
try:
    arr_v = np.load(str(VAL_PATH), mmap_mode="r")
    print(f"  Loaded OK: shape={arr_v.shape}, dtype={arr_v.dtype}")
except Exception as e:
    print(f"  FAIL: np.load raised {type(e).__name__}: {e}")
    VAL_PATH.rename(VAL_PATH.with_suffix(".npy.bad"))
    sys.exit(1)

print()
print("=" * 70)
print("G3 DOWNLOAD COMPLETE")
print("=" * 70)
print(f"  Negatives slice : {NEG_PATH.relative_to(_THIS.parents[2].parent)}")
print(f"                   {fmt_mb(NEG_PATH.stat().st_size)}, shape={arr.shape}, dtype={arr.dtype}")
print(f"  Validation set  : {VAL_PATH.relative_to(_THIS.parents[2].parent)}")
print(f"                   {fmt_mb(VAL_PATH.stat().st_size)}, shape={arr_v.shape}, dtype={arr_v.dtype}")
