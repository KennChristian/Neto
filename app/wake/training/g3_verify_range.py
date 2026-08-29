"""Verify HuggingFace serves genuine HTTP-Range partial downloads for
the openWakeWord features .npy, then parse the header to compute the
exact byte offset needed for a 1.5 GB slice.

If the server doesn't return HTTP 206 Partial Content + the requested
byte range, this script HALTS — we never fall back to a full download.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import numpy as np
import requests

URL = (
    "https://huggingface.co/datasets/davidscripka/openwakeword_features"
    "/resolve/main/openwakeword_features_ACAV100M_2000_hrs_16bit.npy"
)
EXPECTED_TOTAL_BYTES = 17_280_000_128   # 16.48 GB
TARGET_SLICE_GB = 1.5
TARGET_SLICE_BYTES = int(TARGET_SLICE_GB * 1024**3)

print("=" * 70)
print("Step 1 — pull just the first 8 KB via HTTP Range and verify 206.")
print("=" * 70)

# Use a streaming GET with allow_redirects so HF's redirect → CloudFront
# works, but ONLY pull 8 KB. The Range header asks for bytes 0-8191.
with requests.get(URL, headers={"Range": "bytes=0-8191"},
                  stream=True, timeout=60) as r:
    status = r.status_code
    final_url = r.url
    received_bytes = r.content   # 8 KB max
    server_accept_ranges = r.headers.get("Accept-Ranges", "(missing)")
    server_content_range = r.headers.get("Content-Range", "(missing)")
    server_content_length = r.headers.get("Content-Length", "(missing)")

print(f"  Final URL after redirect: {final_url[:80]}...")
print(f"  Response status:       {status}")
print(f"  Content-Length:        {server_content_length}")
print(f"  Content-Range:         {server_content_range}")
print(f"  Accept-Ranges:         {server_accept_ranges}")
print(f"  Actual bytes received: {len(received_bytes)}")

if status != 206:
    print()
    print(f"FAIL — server returned HTTP {status}, not 206 Partial Content.")
    print("HuggingFace CDN does NOT honour Range requests for this file.")
    print("DO NOT proceed with the partial download; stop and reconsider.")
    sys.exit(1)

if len(received_bytes) > 16_384:
    print()
    print(f"FAIL — server returned {len(received_bytes)} bytes but we "
          f"asked for max 8192. Server is ignoring our Range header.")
    sys.exit(1)

print()
print("✓ HTTP 206 confirmed. Server honoured the byte-range request.")
print(f"✓ Only {len(received_bytes)} bytes pulled (asked ≤ 8192).")

# ── Step 2: parse the NumPy header to learn dtype/shape ────────────
print()
print("=" * 70)
print("Step 2 — parse the .npy header to figure out dtype + shape.")
print("=" * 70)

# .npy format spec: magic = b"\x93NUMPY", then version, then header_len,
# then a Python literal dict, then raw array data starts.
buf = io.BytesIO(received_bytes)
magic = buf.read(6)
if magic != b"\x93NUMPY":
    print(f"FAIL — not a .npy file (magic = {magic!r}).")
    sys.exit(1)
print(f"  Magic:                 {magic!r}  ✓")

ver_major = buf.read(1)[0]
ver_minor = buf.read(1)[0]
print(f"  NumPy format version:  {ver_major}.{ver_minor}")

# v1.0 uses 2-byte header length; v2.0+ uses 4-byte.
if (ver_major, ver_minor) == (1, 0):
    header_len = int.from_bytes(buf.read(2), "little")
    data_start = 10 + header_len
else:
    header_len = int.from_bytes(buf.read(4), "little")
    data_start = 12 + header_len

header_bytes = buf.read(header_len)
header_str = header_bytes.decode("latin1").rstrip("\x00").rstrip()
print(f"  Header length:         {header_len}  bytes")
print(f"  Data starts at offset: {data_start}  bytes")
print(f"  Header literal:        {header_str}")

# header is a Python literal dict, e.g.
#   {'descr': '<f4', 'fortran_order': False, 'shape': (1234, 96), }
import ast
hdr = ast.literal_eval(header_str)
descr = hdr["descr"]
shape = hdr["shape"]
fortran_order = hdr["fortran_order"]

dtype = np.dtype(descr)
elem_bytes = dtype.itemsize
n_rows_total = shape[0]
cols = shape[1:] if len(shape) > 1 else ()
cols_product = 1
for c in cols:
    cols_product *= c
bytes_per_row = elem_bytes * cols_product

print(f"  Parsed dtype:          {dtype}  ({elem_bytes} bytes/element)")
print(f"  Parsed shape:          {shape}")
print(f"  fortran_order:         {fortran_order}")
print(f"  Bytes per row:         {bytes_per_row}")

# Sanity: header data_start + n_rows_total * bytes_per_row should
# equal the file size.
expected_size = data_start + n_rows_total * bytes_per_row
print(f"  Implied file size:     {expected_size:,} bytes")
print(f"  Actual file size:      {EXPECTED_TOTAL_BYTES:,} bytes")
if expected_size != EXPECTED_TOTAL_BYTES:
    print(f"FAIL — size mismatch by {abs(expected_size - EXPECTED_TOTAL_BYTES):,} bytes.")
    sys.exit(1)
print("  ✓ Header math matches actual file size.")

# ── Step 3: compute how many rows fit in our 1.5 GB slice ──────────
print()
print("=" * 70)
print(f"Step 3 — plan a {TARGET_SLICE_GB} GB slice.")
print("=" * 70)

# We'll download data_start + N * bytes_per_row bytes, where N is
# chosen so the total stays under TARGET_SLICE_BYTES.
n_rows_to_pull = (TARGET_SLICE_BYTES - data_start) // bytes_per_row
slice_data_bytes = n_rows_to_pull * bytes_per_row
slice_total_bytes = data_start + slice_data_bytes
hours_total = n_rows_total / (3600 * 80)        # 80 mel-frames/sec = 80 Hz
hours_in_slice = n_rows_to_pull / (3600 * 80)

print(f"  Target slice (GB):           {TARGET_SLICE_GB}")
print(f"  Rows in full file:           {n_rows_total:,}")
print(f"  Rows in slice:               {n_rows_to_pull:,}")
print(f"  Fraction of full file:       {n_rows_to_pull / n_rows_total:.2%}")
print(f"  Approximate hours in slice:  {hours_in_slice:.1f} hrs  "
      f"(of {hours_total:.0f} hrs total)")
print(f"  Total bytes to download:     {slice_total_bytes:,}  "
      f"≈ {slice_total_bytes / 1024**3:.3f} GB")

# Time estimates at the operator's bandwidth.
for mbps in (4, 10, 25):
    bytes_per_sec = mbps * 1_000_000 / 8
    seconds = slice_total_bytes / bytes_per_sec
    print(f"    At {mbps:>2d} Mbps: ~{seconds / 60:.1f} min")

print()
print("Ready to proceed with the slice download.")
print(f"  Range header will be: bytes=0-{slice_total_bytes - 1}")
print()
print("After the slice lands, we rewrite the NumPy header to declare")
print(f"shape=({n_rows_to_pull}, ...) so the file is a valid standalone .npy")
print("of just the sliced portion.")
