#!/home/pollen/Supervaise-Reachy-Mini-Project-main/app/.venv/bin/python
"""Snapshot / diff / restore every writable XVF3800 parameter.

    xvf_snapshot.py save <file.json>     read all rw params -> file
    xvf_snapshot.py diff <file.json>     show params that drifted from file
    xvf_snapshot.py restore <file.json>  write back ONLY the drifted params

Loads reachy_mini/media/audio_control_utils.py straight from its file so the
package __init__ (onnxruntime etc.) is not imported — same trick as
~/bin/xvf-ctl, ~0.3 s per invocation.

restore writes only what actually differs, so a no-op restore costs one read
pass and touches the chip zero times. Parameters that reject a write are
reported and skipped rather than aborting the run — a partial restore of 58
of 59 values is better than none. LED/GPO/TEST/SPECIAL blocks are excluded:
they are not audio tuning and some are write-only side effects.
"""
import importlib.util
import json
import sys

MOD = ("/home/pollen/Supervaise-Reachy-Mini-Project-main/app/.venv/lib/python3.13/"
       "site-packages/reachy_mini/media/audio_control_utils.py")
SKIP_PREFIX = ("SPECIAL", "GPO", "LED", "TEST")
# rw by the chip's table, but a live meter rather than a setting: PP_AGCGAIN is
# whatever gain the AGC has hunted to this instant (observed swinging 7.8 -> 2.8
# between two reads seconds apart). Snapshotting it is useful evidence; treating
# it as drift would make every diff dirty and every restore fight the AGC.
DYNAMIC = {"PP_AGCGAIN"}
TOL = 1e-3


def _load():
    spec = importlib.util.spec_from_file_location("audio_control_utils", MOD)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _names(m):
    return [n for n, d in m.PARAMETERS.items()
            if d[3] == "rw" and not n.startswith(SKIP_PREFIX)]


def _read_all(m, dev):
    out = {}
    for n in _names(m):
        try:
            v = m.ReSpeaker._decode_parameter_values(dev, n, dev.read(n))
            out[n] = list(v) if v is not None else None
        except Exception as e:
            out[n] = None
            print(f"  ! read {n}: {e}", file=sys.stderr)
    return out


def _same(a, b):
    if a is None or b is None:
        return a == b
    if len(a) != len(b):
        return False
    return all(abs(float(x) - float(y)) <= TOL for x, y in zip(a, b))


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("save", "diff", "restore"):
        print(__doc__)
        return 2
    cmd, path = sys.argv[1], sys.argv[2]

    m = _load()
    dev = m.init_respeaker_usb()
    if dev is None:
        print(json.dumps({"ok": False, "error": "no XVF3800 USB device"}))
        return 1

    try:
        live = _read_all(m, dev)

        if cmd == "save":
            with open(path, "w") as f:
                json.dump(live, f, indent=1)
            print(f"saved {len(live)} parameters -> {path}")
            return 0

        with open(path) as f:
            want = json.load(f)

        drift = [(n, want[n], live.get(n)) for n in want
                 if n in live and n not in DYNAMIC
                 and not _same(want[n], live.get(n))]

        if not drift:
            print("no drift — chip matches the snapshot")
            return 0

        if cmd == "diff":
            print(f"{len(drift)} parameter(s) differ from {path}:")
            for n, w, l in drift:
                print(f"  {n}: snapshot={w}  live={l}")
            return 0

        fails = 0
        print(f"restoring {len(drift)} parameter(s) from {path}:")
        for n, w, l in drift:
            if w is None:
                print(f"  - {n}: snapshot value unknown, skipped")
                continue
            typ = m.PARAMETERS[n][4]
            conv = float if typ in ("float", "radians") else int
            try:
                dev.write(n, [conv(v) for v in w])
                print(f"  + {n}: {l} -> {w}")
            except Exception as e:
                fails += 1
                print(f"  ! {n}: write failed ({e})")
        print(f"done — {len(drift) - fails} restored, {fails} failed")
        return 1 if fails else 0
    finally:
        try:
            dev.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
