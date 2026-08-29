"""WakeWordEngine — sliding-window wake-word detector for the kiosk.

Architecture (PLAN-0008 §3 — three threads, one writer to st.session_state):

  audio thread (sounddevice callback)
        │   each 80 ms: int16[1280] frame
        ▼
   queue.Queue(maxsize=100, drop-oldest)
        │
  worker thread (this engine, daemon)
        │   model.predict(frame) → {model_name: float}
        │   if score >= threshold: write to lock-protected member
        ▼
  threading.Event (._detected_event)
        │
  main Streamlit thread
        │   reads via engine.poll_detection() each rerun
        │   (driven by streamlit-autorefresh @ 500 ms while running)
        ▼
  st.session_state update + visible UI banner

The engine NEVER touches `st.session_state` itself. All cross-thread
state lives in member fields guarded by `self._lock`; the main thread
reads via `poll_detection()` and is the only writer to session_state.

Idempotent `start()` so a Streamlit rerun that hits the start path
twice doesn't spawn duplicate streams or workers.

Engine ports verbatim to Reachy Mini in Task 4: swap the
`AudioSource` instance. Engine code stays.
"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from collections import deque
from typing import Callable, Optional

import numpy as np

from .sources import AudioSource, SoundDeviceSource


# Optional phase-progress callback: engine calls `cb(msg)` at each
# phase of `start()` so the UI can paint "downloading… / loading… /
# starting audio…" rather than freezing under a single spinner. The
# callback runs on the calling (main Streamlit) thread; it must be
# non-blocking and exception-tolerant — the engine swallows any
# exception it raises.
PhaseCallback = Callable[[str], None]


# Substrings that identify "openWakeWord can't find a required model
# file on disk." Surfaces as ONNXRuntimeError NO_SUCHFILE on the ONNX
# backend, FileNotFoundError on tflite, and various wordings in
# between depending on backend version.
_MISSING_FILE_MARKERS = (
    "NO_SUCHFILE",       # ONNX Runtime error code
    "No such file",      # generic POSIX
    "doesn't exist",     # generic Windows
    "cannot find",       # tflite_runtime wording
)


def _looks_like_missing_model_file(err: BaseException) -> bool:
    """True if the error from Model(...) is most likely a missing
    pretrained-model file on disk — i.e. the openWakeWord package was
    pip-installed but `openwakeword.utils.download_models()` has never
    been run.
    """
    if isinstance(err, FileNotFoundError):
        return True
    msg = str(err)
    return any(marker in msg for marker in _MISSING_FILE_MARKERS)


# Stock openWakeWord pretrained models confirmed from the package's
# `openwakeword/__init__.py` MODELS dict. (Verified via WebFetch on
# 2026-06-03 — do not invent additional names without re-checking
# the source.)
AVAILABLE_STOCK_MODELS = (
    "hey_jarvis",
    "hey_mycroft",
    "alexa",
    "hey_rhasspy",
    "timer",
    "weather",
)


class WakeWordEngine:
    """Continuous wake-word detector built around openWakeWord.

    Typical lifecycle:

        eng = WakeWordEngine(model_name="hey_jarvis", threshold=0.5)
        eng.start()
        ...
        det = eng.poll_detection()   # called from main Streamlit thread
        if det is not None:
            handle_wake(det)
        ...
        eng.stop()

    Held in `st.session_state.wake_engine` so a single instance survives
    Streamlit reruns; `start()` is idempotent so the rerun-driven
    start path can't double-instantiate.
    """

    # Drop-oldest-on-overflow queue: a momentary worker stall mustn't
    # back up audio. 100 frames × 80 ms = 8 seconds of headroom.
    _QUEUE_MAXSIZE = 100

    def __init__(
        self,
        model_name: str = "hey_jarvis",
        threshold: float = 0.35,
        source: Optional[AudioSource] = None,
    ):
        # Default threshold 0.35 — retuned 2026-06-11 after the
        # consolidation to the C: venv revealed wake_test.py firing
        # ~15/20 at 0.35 vs the prior 0.40 default. Offline scores
        # on held-out real-voice clips were ~0.92 but live-mic peaks
        # land lower in this room (mic gain / acoustics / distance);
        # 0.35 catches the bottom 20% of those peaks without
        # triggering on background speech in operator's testing.
        # Stock hey_jarvis is unaffected — its scores sit well above
        # 0.5 on a clean trigger.
        if model_name not in AVAILABLE_STOCK_MODELS:
            # Allow non-stock paths through — Task 1 trains a custom
            # "hey cj" model that lives at e.g. app/wake/models/hey_cj.onnx
            # and is loaded by absolute path. For Task 0 the dev page
            # constrains the dropdown to AVAILABLE_STOCK_MODELS.
            pass
        self.model_name = model_name
        self.threshold = float(threshold)
        self.source: AudioSource = source or SoundDeviceSource()

        # openWakeWord model — lazy-loaded inside start() so import is
        # cheap and load latency is owned by the start() call.
        self.model = None  # type: ignore[assignment]

        # Internal threading state
        self._frame_queue: queue.Queue[np.ndarray] = queue.Queue(
            maxsize=self._QUEUE_MAXSIZE
        )
        self._worker_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Cross-thread signal bridge (worker → main)
        self._detected_event = threading.Event()
        self._lock = threading.Lock()
        self._last_detection: Optional[dict] = None

        # Diagnostics (cheap atomic-int writes, no lock needed for
        # observation — slight tearing on read is fine for a counter)
        self._start_count = 0
        self._frames_processed = 0
        self._predictions_made = 0
        self._worker_errors = 0
        self._last_error: Optional[str] = None
        self._last_score: float = 0.0  # most recent score, regardless of threshold
        self._started_at: Optional[float] = None

        # Rolling history of (timestamp, score) tuples — used by
        # wake_test.py's score-capture UI to compute the peak score
        # over the last N seconds for a user-spoken utterance.
        # deque.append() is atomic in CPython so the worker thread can
        # write while the main thread reads without a lock; iteration
        # may miss the most recent few entries but that's irrelevant
        # for peak-finding.
        # 250 entries × 80 ms/frame = 20 s of history.
        self._score_history: "deque[tuple[float, float]]" = deque(maxlen=250)

    # ── Model-file provisioning ─────────────────────────────────────
    @staticmethod
    def ensure_models_downloaded(
        model_names: list[str],
        progress_cb: Optional[PhaseCallback] = None,
    ) -> None:
        """Make sure the required openWakeWord model files exist on disk.

        **openWakeWord's pip package does NOT bundle the pretrained
        model files.** They must be downloaded explicitly after
        install via `openwakeword.utils.download_models()`. The Model
        constructor does NOT auto-download — calling it before the
        files exist raises NoSuchFile.

        This wrapper:
          • imports `openwakeword.utils.download_models` lazily,
          • fetches both `.tflite` and `.onnx` formats for every
            requested wake-word model (per source: the wake-word
            download branch unconditionally fetches both variants),
          • fetches the shared FEATURE_MODELS (`melspectrogram`,
            `embedding_model`) in both formats,
          • fetches the VAD model (`silero_vad.onnx`),
          • is idempotent — `download_models()` checks for file
            existence and skips already-present files, so this is
            cheap to call on every start.

        Pass `progress_cb` to receive phase messages for the UI.
        """
        def _phase(msg: str) -> None:
            if progress_cb is None:
                return
            try:
                progress_cb(msg)
            except Exception:
                pass

        try:
            from openwakeword.utils import download_models
        except ImportError as e:
            raise RuntimeError(
                "`openwakeword` package is not importable. "
                "Run `pip install -r app/requirements.txt`. "
                f"Underlying error: {e}"
            ) from e

        names = list(model_names)
        if not names:
            _phase("No model names supplied; nothing to download.")
            return

        # Filter out any name that looks like a filesystem path (custom
        # trained model). download_models() only knows the stock-model
        # name registry; passing a path makes it 404. The shared mel-
        # spec + embedding + VAD models still need to be present, so
        # we call download_models() with an empty list to fetch only
        # those if needed.
        path_names = [n for n in names if n.endswith(".onnx") or n.endswith(".tflite")
                                          or "/" in n or "\\" in n]
        stock_names = [n for n in names if n not in path_names]

        if path_names:
            _phase(
                f"Custom model paths supplied — verifying shared mel-spec / "
                f"embedding / VAD models are on disk…"
            )
        else:
            _phase(
                f"Checking openWakeWord model files for "
                f"{', '.join(stock_names)} (downloads on first run, "
                f"~10-30 MB)…"
            )
        try:
            # Pass only stock names. Empty list triggers a fetch of
            # the shared FEATURE_MODELS + VAD only, which is what we
            # need for custom-path models (they're standalone .onnx
            # files but the embedding pipeline still runs through the
            # shared mel-spec + embedding models).
            download_models(model_names=stock_names)
        except Exception as e:
            raise RuntimeError(
                "openWakeWord model download failed. This is required "
                "on first run only; subsequent starts reuse the cached "
                "files. Check network access to github.com release "
                f"assets. Underlying error: {type(e).__name__}: {e}"
            ) from e
        _phase("Model files ready.")

    # ── Lifecycle ───────────────────────────────────────────────────
    def start(self, progress_cb: Optional[PhaseCallback] = None) -> None:
        """Boot the engine: load model, start audio source, start worker.

        Idempotent — calling twice is a no-op. Returns once the engine
        is running (or raises if model load / source open failed).

        If the openWakeWord pretrained-model files aren't on disk yet
        (first run after `pip install`), the loader catches the
        NoSuchFile error, downloads the required models via
        `ensure_models_downloaded`, and retries the load **once**.
        Defensive — for a clear UI download experience, callers
        should invoke `WakeWordEngine.ensure_models_downloaded(...)`
        explicitly BEFORE `start()` so the download phase is its own
        visible step in the UI.

        `progress_cb`, if supplied, receives phase strings:
          "Loading openWakeWord model 'X'…"
          "Model files not present — auto-downloading (first run only)…"
          "Starting audio source…"
        """
        def _phase(msg: str) -> None:
            if progress_cb is None:
                return
            try:
                progress_cb(msg)
            except Exception:
                pass

        if self._worker_thread is not None and self._worker_thread.is_alive():
            # Already running; honour idempotency contract.
            return

        # Reset internal state for this start cycle.
        self._stop_event.clear()
        self._detected_event.clear()
        with self._lock:
            self._last_detection = None
        # Drain any stale frames from a previous cycle.
        while True:
            try:
                self._frame_queue.get_nowait()
            except queue.Empty:
                break

        # Import the openWakeWord Model class. ImportError here means
        # the package isn't installed in this venv at all — distinct
        # from "package installed but model files missing."
        try:
            from openwakeword.model import Model
        except ImportError as e:
            raise RuntimeError(
                "openWakeWord is not installed in the active venv. "
                "Run `pip install -r app/requirements.txt`. "
                f"Underlying error: {e}"
            ) from e

        # Use the ONNX inference backend rather than the default
        # tflite — onnxruntime wheels are reliable on Win/Py 3.10+
        # whereas tflite_runtime can fail to install. Confirmed
        # supported from openwakeword/model.py source.
        _phase(f"Loading openWakeWord model '{self.model_name}'…")
        try:
            self.model = Model(
                wakeword_models=[self.model_name],
                inference_framework="onnx",
            )
        except Exception as first_err:
            # Distinguish "missing files" (recoverable via auto-
            # download) from genuine load errors (broken install,
            # wrong inference framework, OOM…). For missing files,
            # auto-download once and retry. For anything else,
            # surface immediately.
            if not _looks_like_missing_model_file(first_err):
                raise RuntimeError(
                    f"openWakeWord.Model() failed to load "
                    f"'{self.model_name}'. Underlying error: "
                    f"{type(first_err).__name__}: {first_err}"
                ) from first_err

            _phase(
                "Model files not present in the openwakeword package — "
                "auto-downloading (first run only)…"
            )
            try:
                self.ensure_models_downloaded([self.model_name], progress_cb)
            except Exception as dl_err:
                # ensure_models_downloaded already wraps its errors
                # in RuntimeError with a clear message.
                raise dl_err

            # Retry the load. If it still fails, fall through to a
            # final raise — we don't loop further.
            _phase(f"Loading openWakeWord model '{self.model_name}' (retry)…")
            try:
                self.model = Model(
                    wakeword_models=[self.model_name],
                    inference_framework="onnx",
                )
            except Exception as retry_err:
                raise RuntimeError(
                    f"openWakeWord.Model() still failed after auto-"
                    f"downloading models. Underlying error: "
                    f"{type(retry_err).__name__}: {retry_err}"
                ) from retry_err

        # Start the audio source AFTER model load — otherwise frames
        # queue up during the (potentially multi-second) model load
        # and the worker spends its first cycles burning stale audio.
        _phase("Starting audio source…")
        try:
            self.source.start(self._on_audio_frame)
        except Exception as e:
            # If audio fails, tear down what we just built so the
            # next start() call has a clean slate.
            self.model = None
            raise RuntimeError(
                f"Audio source failed to start. "
                f"Underlying error: {type(e).__name__}: {e}"
            ) from e

        # Start the worker thread. daemon=True so a process exit
        # doesn't block waiting for it (Streamlit doesn't give us
        # a reliable teardown hook).
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="WakeWordEngineWorker",
            daemon=True,
        )
        self._worker_thread.start()
        self._start_count += 1
        self._started_at = time.time()

    def stop(self) -> None:
        """Stop audio capture, signal the worker to exit, join briefly.

        Idempotent — safe to call before start(), after stop(), or twice.
        """
        # Signal worker to exit first so any in-flight predict() call
        # finishes and the next loop iteration sees the flag.
        self._stop_event.set()

        # Close audio source so the audio thread stops queueing frames.
        try:
            self.source.stop()
        except Exception:
            pass

        # Join worker with a generous timeout. If it doesn't exit we
        # log it but keep going — daemon=True means it dies on
        # process exit anyway.
        t = self._worker_thread
        if t is not None and t.is_alive():
            t.join(timeout=2.0)
        self._worker_thread = None

        self.model = None
        self._started_at = None

    # ── Audio source callback ───────────────────────────────────────
    def _on_audio_frame(self, frame: np.ndarray) -> None:
        """Called from the sounddevice audio thread.

        Pushes frame onto bounded queue. On overflow, drops the
        oldest frame and inserts the new one — the worker is
        momentarily behind and we'd rather have current audio than
        a stale backlog.
        """
        try:
            self._frame_queue.put_nowait(frame)
        except queue.Full:
            # Drop oldest, retry. If still full (extremely unlikely),
            # silently drop the new frame — audio thread must not
            # block.
            try:
                self._frame_queue.get_nowait()
                self._frame_queue.put_nowait(frame)
            except (queue.Empty, queue.Full):
                pass

    # ── Worker thread ───────────────────────────────────────────────
    def _worker_loop(self) -> None:
        """Pull frames, run prediction, raise the detection flag."""
        while not self._stop_event.is_set():
            try:
                frame = self._frame_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            self._frames_processed += 1

            try:
                preds = self.model.predict(frame)  # type: ignore[union-attr]
            except Exception as e:
                # Don't crash the worker — log and continue. If
                # this becomes chronic the dev-page diagnostics
                # will show worker_errors climbing.
                self._worker_errors += 1
                self._last_error = (
                    f"{type(e).__name__}: {e}\n{traceback.format_exc()[:1000]}"
                )
                continue

            self._predictions_made += 1
            # predict() returns dict keyed by model name (for stock
            # models) or by basename-without-extension (for paths
            # loaded from disk). Try the exact name first; fall back
            # to the first prediction value since we always load
            # exactly one model (so the dict has at most one entry).
            score = float(preds.get(self.model_name, 0.0))
            if score == 0.0 and preds:
                score = float(next(iter(preds.values())))
            self._last_score = score
            self._score_history.append((time.time(), score))

            if score >= self.threshold:
                with self._lock:
                    self._last_detection = {
                        "model_name": self.model_name,
                        "score": score,
                        "ts": time.time(),
                    }
                self._detected_event.set()

    # ── Main-thread API ─────────────────────────────────────────────
    def recent_peak(self, seconds: float = 2.0) -> tuple[float, Optional[float]]:
        """Return (peak_score, timestamp_of_peak) over the last
        `seconds` of scored frames.

        Used by wake_test.py's "capture last utterance" button: the
        operator says a phrase, then clicks capture, and we return the
        highest score seen in the most recent rolling window. If the
        history is empty (engine just started, mic still warming up)
        returns (0.0, None).
        """
        if not self._score_history:
            return 0.0, None
        cutoff = time.time() - seconds
        # Iterate a copy of the snapshot to be safe — deque iteration
        # during concurrent appends is allowed in CPython but the
        # snapshot is conceptually cleaner.
        snap = [(ts, s) for ts, s in tuple(self._score_history) if ts >= cutoff]
        if not snap:
            return 0.0, None
        ts_peak, s_peak = max(snap, key=lambda p: p[1])
        return s_peak, ts_peak

    def poll_detection(self) -> Optional[dict]:
        """Return-and-consume the most recent wake detection.

        Called from the main Streamlit thread on every rerun. Returns
        a dict `{model_name, score, ts}` if a detection has fired
        since the last poll, else None. Atomically clears the flag
        so the next poll returns None until the worker raises it
        again.
        """
        if not self._detected_event.is_set():
            return None
        with self._lock:
            d = self._last_detection
            self._last_detection = None
        self._detected_event.clear()
        return d

    def stats(self) -> dict:
        """Return a snapshot of engine internals for the diagnostics expander."""
        return {
            "model_name": self.model_name,
            "threshold": self.threshold,
            "model_loaded": self.model is not None,
            "thread_alive": (
                self._worker_thread is not None
                and self._worker_thread.is_alive()
            ),
            "device_name": self.source.device_name,
            "start_count": self._start_count,
            "frames_processed": self._frames_processed,
            "predictions_made": self._predictions_made,
            "queue_size": self._frame_queue.qsize(),
            "worker_errors": self._worker_errors,
            "last_error": self._last_error,
            "last_score": round(self._last_score, 4),
            "uptime_s": (
                round(time.time() - self._started_at, 1)
                if self._started_at else None
            ),
        }
