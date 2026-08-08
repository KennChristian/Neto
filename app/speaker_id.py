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
MODEL = os.path.join(DIR, "wespeaker_en_voxceleb_CAM++.onnx")
ENROLLED = os.path.join(DIR, "enrolled.npz")
ENABLED_FLAG = os.path.join(DIR, "enabled")
LAST = "/dev/shm/cj_speaker_last.json"

_extractor = None


def _load():
    global _extractor
    if _extractor is None:
        import sherpa_onnx
        cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=MODEL, num_threads=2)
        _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    return _extractor


def embed_wav(path):
    from scipy.io import wavfile
    sr, data = wavfile.read(path)
    if data.ndim > 1:
        data = data[:, 0]
    ex = _load()
    st = ex.create_stream()
    st.accept_waveform(sr, data.astype(np.float32) / 32768.0)
    st.input_finished()
    emb = np.array(ex.compute(st), dtype=np.float32)
    return emb / (np.linalg.norm(emb) + 1e-9)


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
