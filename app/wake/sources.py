"""Audio source seam for the wake-word engine.

PLAN-0008 §3 specifies "behind a clean audio-source interface (the
'I/O seam') so the source can later swap `sounddevice → Reachy SDK`
without touching wake logic."

This module defines:

  * `AudioSource` — the abstract contract every source must implement.
  * `SoundDeviceSource` — concrete implementation using the
    `sounddevice` library. Used by the laptop kiosk.

The Reachy Mini implementation will later land as `ReachySource(AudioSource)`
in this same file (or a sibling module imported here). The engine
should never need to know which source it is talking to.

Contract (all sources MUST):
  * deliver mono 16 kHz 16-bit PCM frames,
  * deliver them in chunks of exactly `BLOCK_SAMPLES` (1280 samples = 80 ms),
    matching the openWakeWord per-call ideal,
  * invoke `on_frame(frame: np.ndarray)` from whichever thread the
    source uses (the engine queues + drains on a separate worker so
    the source thread is never held up by inference),
  * be idempotent on `.stop()` (safe to call when not started).
"""

from __future__ import annotations

import abc
from typing import Callable, Optional

import numpy as np


# ── Shared audio-format constants ─────────────────────────────────────
# openWakeWord docs/source: "16-bit 16khz PCM audio data", ideally in
# multiples of 80 ms (1280 samples). We always deliver exactly 1280
# samples per callback — the smallest unit predict() prefers.
SAMPLE_RATE = 16_000
BLOCK_SAMPLES = 1280
CHANNELS = 1
DTYPE = "int16"


FrameCallback = Callable[[np.ndarray], None]


class AudioSource(abc.ABC):
    """Abstract base for any continuous mic audio source."""

    @abc.abstractmethod
    def start(self, on_frame: FrameCallback) -> None:
        """Begin delivering frames to `on_frame` until `stop()` is called.

        `on_frame(frame)` receives a **1-D `np.int16` ndarray of length
        `BLOCK_SAMPLES`**. Implementations MUST .copy() any
        reusable native buffer before passing it through.

        May raise on hardware errors. Engine surfaces the exception to
        the UI rather than crashing.
        """

    @abc.abstractmethod
    def stop(self) -> None:
        """Stop the source and release the audio device.

        Idempotent — safe to call when never started or already stopped.
        """

    @property
    @abc.abstractmethod
    def device_name(self) -> str:
        """Human-readable name of the active input device (for diagnostics)."""


# ── Concrete: sounddevice ────────────────────────────────────────────
class SoundDeviceSource(AudioSource):
    """Continuous mic source backed by the `sounddevice` library.

    Defaults to the system's default input device. Pass `device=<int>`
    or `device=<str-substring>` to override — useful when the kiosk
    laptop has multiple inputs (built-in mic vs USB array).

    The sounddevice callback runs on a high-priority audio thread.
    Our callback only does cheap work (slice + dtype + copy + callout),
    so we never hold up audio capture.
    """

    def __init__(self, device: Optional[int | str] = None):
        self.device = device
        self._stream = None          # type: ignore[assignment]
        self._on_frame: Optional[FrameCallback] = None
        self._device_name = ""

    # ── AudioSource API ──
    def start(self, on_frame: FrameCallback) -> None:
        # Import inside start() so the module imports cleanly even on
        # machines without PortAudio (e.g. Reachy Mini robot, where
        # ReachySource will be used instead). Engine catches and
        # reports ImportError to the UI.
        import sounddevice as sd

        self._on_frame = on_frame

        # Resolve and remember the active device so the dev page can
        # show it. `query_devices` failures are non-fatal — we still
        # try to open the stream.
        try:
            info = sd.query_devices(self.device, "input")
            self._device_name = (
                f"{info['name']} "
                f"(default_sr={int(info['default_samplerate'])}, "
                f"max_channels={info['max_input_channels']})"
            )
        except Exception as e:
            self._device_name = f"<query_devices failed: {type(e).__name__}: {e}>"

        # The InputStream callback receives `indata` shaped (frames,
        # channels). We grab channel 0, copy out, and hand to the
        # engine. `status` is set by sounddevice when xruns happen;
        # ignored for now (not user-actionable inside Task 0).
        def _callback(indata, frames, time_info, status):  # noqa: ARG001
            try:
                cb = self._on_frame
                if cb is None:
                    return
                # indata.dtype is np.int16 because we requested it
                # via dtype="int16" on the InputStream. Flatten the
                # (frames, 1) → (frames,) for a 1-D PCM vector and
                # copy off the reusable buffer.
                mono = indata[:, 0].astype(np.int16, copy=True)
                cb(mono)
            except Exception:
                # Never let an exception propagate out of the
                # sounddevice callback — that crashes the audio
                # thread. Worker thread is where prediction errors
                # are surfaced.
                pass

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=BLOCK_SAMPLES,
            device=self.device,
            callback=_callback,
        )
        self._stream.start()

    def stop(self) -> None:
        s = self._stream
        if s is None:
            return
        try:
            s.stop()
        except Exception:
            pass
        try:
            s.close()
        except Exception:
            pass
        self._stream = None

    @property
    def device_name(self) -> str:
        return self._device_name or "(not started)"
