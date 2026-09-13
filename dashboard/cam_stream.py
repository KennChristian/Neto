#!/usr/bin/python3
"""Camera capture for the dashboard (2026-09-01): a GStreamer pipeline that
writes concatenated JPEG frames to stdout — exactly what gst-launch did — but
with focus policy decided at start (libcamerasrc ignores AF changes once
PLAYING, measured 2026-09-01) and a clean stdin/SIGTERM shutdown so the
dashboard can restart it in ~2 s for a refocus or a new focus preset.

Usage: cam_stream.py WIDTH HEIGHT FPS sw|hw [auto|<dioptres>] [x0,y0,x1,y1]

  auto        continuous autofocus (default) measured ONLY inside the window
  <dioptres>  fixed focus: 0 = infinity, 0.5 = 2 m, 1 = 1 m, 2 = 50 cm
  window      fractions of the frame the AF looks at; default 0.15,0.05,0.85,0.55
              (upper middle: faces at 1-3 m, not the table, keyboard or the
              robot's own housing — libcamera's AF otherwise picks the NEAREST
              object in view, which parked the lens at macro on stage).
All logging goes to stderr; stdout carries only JPEG bytes.
"""
import signal
import sys

import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst, GLib  # noqa: E402

AF_MANUAL, AF_AUTO, AF_CONTINUOUS = 0, 1, 2
SENSOR_W, SENSOR_H = 4608, 2592          # IMX708 ScalerCropMaximum (AfWindows units)


def log(msg):
    print(f"[cam_stream] {msg}", file=sys.stderr, flush=True)


def main():
    w, h, fps = (int(a) for a in sys.argv[1:4])
    enc = sys.argv[4] if len(sys.argv) > 4 else "sw"
    focus = sys.argv[5] if len(sys.argv) > 5 else "auto"
    win = sys.argv[6] if len(sys.argv) > 6 else "0.15,0.05,0.85,0.55"
    Gst.init(None)
    encoder = "v4l2jpegenc" if enc == "hw" else "jpegenc quality=70"
    if focus == "auto":
        try:
            x0, y0, x1, y1 = (float(v) for v in win.split(","))
            rect = (int(x0 * SENSOR_W), int(y0 * SENSOR_H),
                    int((x1 - x0) * SENSOR_W), int((y1 - y0) * SENSOR_H))
        except ValueError:
            rect = None
        af = f"af-mode={AF_CONTINUOUS}"
        if rect and rect[2] > 0 and rect[3] > 0:
            af += " af-metering=1 af-windows=<<%d,%d,%d,%d>>" % rect
        desc_focus = f"continuous AF, window {win}" if rect else "continuous AF (whole frame)"
    else:
        af = f"af-mode={AF_MANUAL} lens-position={float(focus)}"
        desc_focus = f"fixed focus {float(focus):g} dioptres"
    desc = (f"libcamerasrc name=src {af} ! "
            f"video/x-raw,width={w},height={h},framerate={fps}/1,format=NV12 ! "
            f"{encoder} ! fdsink fd=1 sync=false")
    pipe = Gst.parse_launch(desc)
    loop = GLib.MainLoop()

    def on_bus(bus, msg):
        t = msg.type
        if t == Gst.MessageType.ERROR:
            err, dbg = msg.parse_error()
            log(f"ERROR {err} ({dbg})"); loop.quit()
        elif t == Gst.MessageType.EOS:
            log("EOS"); loop.quit()
        return True

    bus = pipe.get_bus(); bus.add_signal_watch(); bus.connect("message", on_bus)

    def stop(*_):
        loop.quit(); return False

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, stop)

    def stdin_watch(fd, cond):
        line = sys.stdin.readline()
        if not line or line.strip() == "quit":
            loop.quit(); return False
        return True

    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, stdin_watch)

    pipe.set_state(Gst.State.PLAYING)
    log(f"started {w}x{h}@{fps} {encoder}, {desc_focus}")
    try:
        loop.run()
    finally:
        pipe.set_state(Gst.State.NULL)
        log("stopped")


if __name__ == "__main__":
    main()
