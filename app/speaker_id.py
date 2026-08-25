"""Speaker-verification gate: only answer the enrolled voice.

Embeds utterances with WeSpeaker CAM++ (ONNX, ~0.2 s on the Pi 4, no
torch) and cosine-compares against an enrolled reference embedding.

Files:
    ~/speaker_id/wespeaker_en_voxceleb_CAM++.onnx   the model
    ~/speaker_id/enrolled.npz                        reference embedding
    ~/speaker_id/enabled                             flag: gate is ON
    /dev/shm/cj_speaker_last.json                    last check, for the dashboard

Enrollment happens through the robot mic (dashboard "Enroll voice" button
touches /dev/shm/cj_enroll_trigger; cj_voice_cloud records ~10 s and calls
enroll()). Threshold via CJ_SPEAKER_THRESHOLD, default 0.40 — measured
2026-08-05: same voice scores ~0.88, different sources ~0.12.
"""
import json
import os
import time

import numpy as np

DIR = os.path.expanduser("~/speaker_id")
# 2026-08-24: CAM++ export replaced — its embedding depended on input LENGTH
# (cos 0.35 after trimming 0.3 s off a 4 s clip) and, length held constant,
# gave every voice 0.7-0.9 vs CJ. ERes2Net (3D-Speaker, VoxCeleb) is stable
# (cos 0.98-1.0 under cuts) and separates: same voice 0.57-0.67, other TTS
# voices 0.07-0.17, white noise 0.12; ~1.5 s per embedding on the Pi.
MODEL = os.path.join(DIR, os.environ.get(
    "CJ_SPEAKER_MODEL", "3dspeaker_speech_eres2net_sv_en_voxceleb_16k.onnx"))
ENROLLED = os.path.join(DIR, "enrolled.npz")
ENABLED_FLAG = os.path.join(DIR, "enabled")
LAST = "/dev/shm/cj_speaker_last.json"

_extractor = None


def _load():
    global _extractor
    if _extractor is None:
        import sherpa_onnx
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=MODEL, num_threads=int(os.environ.get("CJ_SPEAKER_THREADS", "3")))
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    return _extractor


def read_wav(path):
    """(sample_rate, int16 mono samples) — cheap; lets callers grab the audio
    before a temp file is unlinked and embed later / off-thread."""
    from scipy.io import wavfile
    sr, data = wavfile.read(path)
    if data.ndim > 1:
        data = data[:, 0]
    return sr, np.ascontiguousarray(data)


def embed_samples(sr, data):
    ex = _load()
    st = ex.create_stream()
    st.accept_waveform(sr, data.astype(np.float32) / 32768.0)
    st.input_finished()
    emb = np.array(ex.compute(st), dtype=np.float32)
    # Guard (2026-08-25): sherpa returns [] for empty audio and NaNs for a few
    # ms of audio; a bad reference then makes every later check raise
    # ("matmul: Input operand 0 does not have enough dimensions") and the lock
    # silently fails open for the whole conversation.
    if emb.ndim != 1 or emb.size == 0 or not np.isfinite(emb).all():
        raise ValueError(f"no usable embedding (audio too short: {len(data) / float(sr or 1):.2f}s)")
    return emb / (np.linalg.norm(emb) + 1e-9)


def embed_wav(path):
    return embed_samples(*read_wav(path))


def enroll(path):
    emb = embed_wav(path)
    os.makedirs(DIR, exist_ok=True)
    np.savez(ENROLLED, emb=emb)
    open(ENABLED_FLAG, "w").close()   # enrolling turns the gate on


def gate_active():
    return os.path.exists(ENROLLED) and os.path.exists(ENABLED_FLAG)


def threshold():
    return float(os.environ.get("CJ_SPEAKER_THRESHOLD", "0.40"))


def verify(path):
    """Returns (ok, similarity). Publishes the result for the dashboard."""
    thr = threshold()
    ref = np.load(ENROLLED)["emb"]
    sim = float(ref @ embed_wav(path))
    ok = sim >= thr
    try:
        with open(LAST + ".tmp", "w") as f:
            json.dump({"ts": time.time(), "sim": round(sim, 3),
                       "ok": ok, "threshold": thr}, f)
        os.replace(LAST + ".tmp", LAST)
    except OSError:
        pass
    return ok, sim


# ---------------------------------------------------------------------------
# Voice lock (2026-08-24): after a wake word the robot locks onto the voice
# that asked the first question and keeps conversing with THAT voice only —
# no further wake word — until it says goodbye or stays quiet for
# CJ_VOICE_LOCK_IDLE_S. Other voices are ignored (no STT, no answer) and a
# stranger's wake word cannot take the lock (user decision 2026-08-24).
# In-memory only: every session starts fresh.
# ---------------------------------------------------------------------------
LOCK_STATE = "/dev/shm/cj_voice_lock.json"


def lock_enabled():
    return os.environ.get("CJ_VOICE_LOCK", "1").strip().lower() not in {
        "0", "false", "no", "off"}


def lock_threshold():
    # ERes2Net, measured 2026-08-24 with TTS clips: same voice 0.57-0.67
    # (3-5 s), other voices 0.07-0.17, noise 0.12. 0.40 sits mid-gap; tune
    # from the [lock] journal lines after a two-person test on the robot.
    # Real-mic 2026-08-24: the same speaker scored 0.37 and 0.60 on
    # follow-ups (single-question reference) -> 0.32 default.
    return float(os.environ.get("CJ_VOICE_LOCK_THRESHOLD", "0.32"))


def lock_idle_s():
    return max(2.0, float(os.environ.get("CJ_VOICE_LOCK_IDLE_S", "10")))


def _wav_seconds(path):
    try:
        from scipy.io import wavfile
        sr, data = wavfile.read(path)
        return len(data) / float(sr or 1)
    except Exception:
        return None


class VoiceLock:
    def __init__(self):
        self.ref = None
        self.n = 0
        self.since = None
        self.last_sim = None
        self._pending = None      # thread computing the initial reference

    def active(self):
        return self.ref is not None or (self._pending is not None and self._pending.is_alive())

    def lock(self, path):
        """Lock onto the speaker of this recording (the first question).
        Reads the audio now, embeds in the background (~1.5 s) so the first
        turn is not delayed; check() waits for it if needed."""
        import threading
        sr, data = read_wav(path)
        self.ref, self.n, self.since, self.last_sim = None, 0, time.time(), None

        def _run():
            try:
                self.ref = embed_samples(sr, data)
                self.n = 1
                self._publish(None, True, lock_threshold())
            except Exception:
                self.ref = None
        self._pending = threading.Thread(target=_run, daemon=True)
        self._pending.start()

    def check_samples(self, sr, data):
        """(ok, similarity) of this audio against the locked voice. A confident
        match folds into the running reference so the lock adapts over the
        conversation. Recordings under ~2.5 s embed weakly: 0.10 lenient band."""
        if self._pending is not None:
            self._pending.join(timeout=8)
            self._pending = None
        ref = self.ref
        if ref is None or np.ndim(ref) != 1 or ref.size == 0:
            return True, None            # no (usable) reference: fail open
        emb = embed_samples(sr, data)
        sim = float(ref @ emb)
        thr = lock_threshold()
        if len(data) / float(sr or 1) < 2.5:
            thr -= 0.07
        ok = sim >= thr
        if ok and sim >= thr + 0.15:
            ref = self.ref * self.n + emb
            self.ref = ref / (np.linalg.norm(ref) + 1e-9)
            self.n += 1
        self.last_sim = sim
        self._publish(sim, ok, thr)
        return ok, sim

    def check(self, path):
        return self.check_samples(*read_wav(path))

    def release(self):
        self.ref, self.n, self.since, self.last_sim = None, 0, None, None
        self._pending = None
        self._publish(None, None, lock_threshold())

    def _publish(self, sim, ok, thr):
        try:
            with open(LOCK_STATE + ".tmp", "w") as f:
                json.dump({"ts": time.time(), "locked": self.active(),
                           "since": self.since, "utterances": self.n,
                           "last_sim": (round(sim, 3) if sim is not None else None),
                           "last_ok": ok, "threshold": round(thr, 2)}, f)
            os.replace(LOCK_STATE + ".tmp", LOCK_STATE)
        except OSError:
            pass
