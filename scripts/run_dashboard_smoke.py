"""P2.5 benchmark — dashboard responsiveness against the LIVE server on :8080.

Measures, repeatably:
  * event-to-visible latency: writes a labeled note into the transcript feed
    and polls /api/state until it appears (the number both views' freshness
    depends on),
  * /api/state fetch latency (p50/p95 over 20 fetches),
  * camera: /api/camera.jpg fetch time, frame size, and effective refresh rate
    over 3 seconds,
  * page weights (audience/maintain must stay lightweight for the demo LAN).

Writes reports/dashboard_smoke.json. Exit 1 if any check fails hard.

Run on the Pi:  python3 scripts/run_dashboard_smoke.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path
from urllib.request import urlopen

BASE = "http://localhost:8080"
ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPT = "/dev/shm/cj_transcript.jsonl"


def fetch(path, timeout=8):
    t0 = time.perf_counter()
    body = urlopen(BASE + path, timeout=timeout).read()
    return body, (time.perf_counter() - t0) * 1000


def main():
    report, fails = {}, []

    # --- state fetch latency ---
    times = []
    for _ in range(20):
        _, ms = fetch("/api/state")
        times.append(ms)
    report["state_ms_p50"] = round(statistics.median(times), 1)
    report["state_ms_p95"] = round(sorted(times)[int(0.95 * len(times)) - 1], 1)
    if report["state_ms_p50"] > 500:
        fails.append("state fetch p50 > 500ms")

    # --- event-to-visible latency ---
    marker = f"(dashboard smoke test {int(time.time())})"
    with open(TRANSCRIPT, "a") as f:
        f.write(json.dumps({"ts": time.time(), "role": "note", "text": marker}) + "\n")
    t0 = time.perf_counter()
    seen = None
    while time.perf_counter() - t0 < 5:
        body, _ = fetch("/api/state")
        if marker in body.decode():
            seen = (time.perf_counter() - t0) * 1000
            break
        time.sleep(0.05)
    report["event_to_visible_ms"] = round(seen, 1) if seen else None
    if seen is None:
        fails.append("smoke marker never appeared in /api/state")

    # --- camera ---
    try:
        frame, ms = fetch("/api/camera.jpg", timeout=12)
        report["camera_first_frame_ms"] = round(ms, 1)
        report["camera_frame_bytes"] = len(frame)
        n, t0 = 0, time.time()
        last = b""
        while time.time() - t0 < 3:
            f2, _ = fetch("/api/camera.jpg")
            if f2 != last:
                n += 1
                last = f2
            time.sleep(0.08)
        report["camera_fps_effective"] = round(n / 3.0, 1)
        if report["camera_fps_effective"] < 2:
            fails.append("camera effective fps < 2")
    except Exception as e:
        report["camera_error"] = str(e)
        fails.append(f"camera: {e}")

    # --- page weights ---
    for name in ("audience", "maintain"):
        body, ms = fetch("/" + name)
        report[f"{name}_page_kb"] = round(len(body) / 1024, 1)
        report[f"{name}_page_ms"] = round(ms, 1)

    report["ok"] = not fails
    report["fails"] = fails
    out = ROOT / "reports" / "dashboard_smoke.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    print(f"[dashboard-smoke] {'PASS' if not fails else 'FAIL'} -> {out}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
