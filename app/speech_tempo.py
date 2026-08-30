"""Per-sentence tempo normalisation (2026-08-29).

The answer is synthesized one sentence per ElevenLabs request, and each
request comes back at its own articulation rate — a 0.80–1.20 speed sweep
showed take-to-take variance larger than any deliberate speed delta, and the
user hears it as "observable jumps in reading" between sentences.

This module measures each sentence's rate from the word alignment sidecar
(characters per second of *voiced* time, pauses excluded) and time-stretches
the audio a few percent toward the running average with WSOLA (pitch is
unchanged — it is not a resample). The first sentence of an answer sets the
target; later ones are pulled toward the EMA, never more than CJ_TEMPO_MAX
(default 15 %). The word times in the sidecar are rescaled so captions and
the avatar lips stay in sync.

The target is seeded from a session-wide running average persisted in
SESSION_AVG (so answers match each other, not just their own opener); the
first sentence of an answer is never stretched (first-audio latency) — it
only refines the target.

Speed limit (2026-08-29 evening, user: "can we limit the speaking speed"):
the target is capped at CJ_TEMPO_RATE_MAX chars/s (default 15.0 ≈ the median
of the clip cache; p75 is 17.2) and sentences are only ever SLOWED
(CJ_TEMPO_SPEEDUP=1 re-enables speeding up). A too-fast opener is slowed too.

Env: CJ_TEMPO_SMOOTH=0 disables; CJ_TEMPO_MAX (0.10); CJ_TEMPO_ALPHA (0.5);
CJ_TEMPO_DEADBAND (0.01) — stretches smaller than this are skipped.
"""
from __future__ import annotations

import json
import os
import threading

import soundfile as sf

SESSION_AVG = "/dev/shm/cj_tempo_avg.json"


def _load_session_avg():
    try:
        v = float(json.load(open(SESSION_AVG)).get("avg"))
        return v if 8.0 < v < 30.0 else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def _save_session_avg(v):
    try:
        with open(SESSION_AVG + ".tmp", "w") as f:
            json.dump({"avg": round(v, 3)}, f)
        os.replace(SESSION_AVG + ".tmp", SESSION_AVG)
    except OSError:
        pass


def enabled() -> bool:
    return os.environ.get("CJ_TEMPO_SMOOTH", "1").strip().lower() not in {"0", "false", "no", "off"}


def _f(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def rate_from_words(words) -> float | None:
    """chars per second of voiced time, or None when too little speech."""
    try:
        voiced = sum(float(e) - float(s) for _w, s, e in words if float(e) > float(s))
        chars = sum(len(str(w).strip(".,;:!?\"'()")) for w, _s, _e in words)
    except (TypeError, ValueError):
        return None
    if voiced < 0.4 or chars < 8:
        return None
    return chars / voiced


def stretch_wav(path: str, factor: float) -> float:
    """Time-stretch `path` in place so its duration becomes duration*factor
    (factor > 1 = slower). Returns the achieved factor."""
    from audiotsm import wsola
    from audiotsm.io.array import ArrayReader, ArrayWriter
    pcm, sr = sf.read(path, dtype="float32", always_2d=True)   # (n, ch)
    n0 = pcm.shape[0]
    reader = ArrayReader(pcm.T.copy())                          # (ch, n)
    writer = ArrayWriter(channels=pcm.shape[1])
    wsola(channels=pcm.shape[1], speed=1.0 / factor).run(reader, writer)
    out = writer.data.T                                         # (m, ch)
    sf.write(path, out, sr, subtype="PCM_16")
    return out.shape[0] / max(1, n0)


CAP_CACHE = os.path.expanduser("~/.voice_cache/tempo")


def cap_clip(wav: str) -> tuple | None:
    """Speed ceiling for a whole curated clip (canned / event / farewell —
    the paths that bypass SentenceSpeaker). If the clip's articulation rate
    exceeds CJ_TEMPO_RATE_MAX it is slowed (≤ CJ_TEMPO_MAX) and the result is
    cached under CAP_CACHE keyed by the clip's bytes + factor, so a clip pays
    the WSOLA cost (~0.1 s per second of audio) once, then plays instantly.
    Returns (factor, rate_before, rate_after) or None when nothing changed."""
    if not enabled():
        return None
    align = wav + ".align.json"
    try:
        words = json.load(open(align))
    except (OSError, ValueError):
        return None
    r = rate_from_words(words)
    rate_max, max_stretch = _f("CJ_TEMPO_RATE_MAX", 13.0), _f("CJ_TEMPO_MAX", 0.15)
    if not r or r <= rate_max * 1.01:
        return None
    factor = min(1.0 + max_stretch, r / rate_max)   # > 1 = slower
    try:
        import hashlib, shutil
        key = hashlib.sha1(open(wav, "rb").read()).hexdigest()[:16] + f"_x{factor:.3f}"
        os.makedirs(CAP_CACHE, exist_ok=True)
        cached = os.path.join(CAP_CACHE, key + ".wav")
        if os.path.exists(cached):
            shutil.copyfile(cached, wav)
        else:
            factor = stretch_wav(wav, factor)
            shutil.copyfile(wav, cached)
        scaled = [[w, round(float(s) * factor, 3), round(float(e) * factor, 3)] for w, s, e in words]
        with open(align, "w") as af:
            json.dump(scaled, af)
        return factor, r, r / factor
    except Exception as e:
        print(f"[tempo] clip cap skipped ({type(e).__name__}: {e})")
        return None


class TempoSmoother:
    """One per answer. process(wav) is thread-safe (synth pool has 2 workers)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.avg = None          # EMA of the (post-stretch) rate, chars/s
        self.seed = _load_session_avg()   # previous answers' tempo (may be None)
        self._n = 0
        self.max = _f("CJ_TEMPO_MAX", 0.10)   # >10 % stretch starts to colour the timbre
        self.alpha = _f("CJ_TEMPO_ALPHA", 0.5)
        self.deadband = _f("CJ_TEMPO_DEADBAND", 0.01)
        self.rate_max = _f("CJ_TEMPO_RATE_MAX", 13.0)        # chars/s ceiling (user 2026-08-30: "a bit fast")
        self.speedup = os.environ.get("CJ_TEMPO_SPEEDUP", "0").strip() == "1"
        self.step = _f("CJ_TEMPO_STEP", 0.05)   # max factor change between adjacent sentences
        self._factors = {}                       # idx -> factor applied

    def process(self, wav: str, idx=None, speed=None):
        """Returns (factor, rate_before, rate_after) or None when skipped.
        idx: sentence index in the answer (0 = opener; with the 2-worker synth
        pool the first synth to FINISH is not always sentence 0, so "first" is
        keyed on idx). speed: the ElevenLabs speed the sentence was requested
        at — rates are normalised by it so an emotion slow-down does not drag
        the session target down."""
        if not enabled():
            return None
        align = wav + ".align.json"
        try:
            words = json.load(open(align))
        except (OSError, ValueError):
            return None
        r0 = rate_from_words(words)
        if not r0:
            return None
        r = r0 / (speed or 1.0)          # pace at base speed (see docstring)
        with self._lock:
            target = self.avg
            first = (idx == 0) if idx is not None else (self._n == 0)
            self._n += 1
            prev_factor = self._factors.get((idx or 0) - 1) if idx is not None else None
        factor = 1.0
        if first and r <= self.rate_max:
            # opener within the limit: no stretch (latency); seed the target
            new_rate = r if self.seed is None else 0.5 * self.seed + 0.5 * r
            new_rate = min(new_rate, self.rate_max)
            with self._lock:
                self.avg = new_rate
            _save_session_avg(new_rate)
            return 1.0, r, r
        if first:
            target = self.rate_max          # too-fast opener: slow it to the ceiling
            seed_blend = min(self.rate_max, r if self.seed is None else 0.5 * self.seed + 0.5 * r)
            with self._lock:
                self.avg = seed_blend
        if target:
            target = min(target, self.rate_max)
            # duration multiplier: rate above target → factor > 1 (longer, slower)
            factor = max(1.0 - self.max, min(1.0 + self.max, r / target))
            if not self.speedup:
                factor = max(1.0, factor)   # limit only: never speed a sentence up
            if prev_factor is not None:     # no tempo jump between neighbours either
                factor = max(prev_factor - self.step, min(prev_factor + self.step, factor))
        if abs(factor - 1.0) >= self.deadband:
            try:
                factor = stretch_wav(wav, factor)
                scaled = [[w, round(float(s) * factor, 3), round(float(e) * factor, 3)]
                          for w, s, e in words]
                with open(align, "w") as af:
                    json.dump(scaled, af)
            except Exception as e:
                print(f"[tempo] stretch skipped ({type(e).__name__}: {e})")
                factor = 1.0
        new_rate = r / factor
        with self._lock:
            if idx is not None:
                self._factors[idx] = factor
            self.avg = new_rate if self.avg is None else (
                self.alpha * new_rate + (1.0 - self.alpha) * self.avg)
            _save_session_avg(self.avg)
        return factor, r0, r0 / factor
