"""Local clip cache for the voice output module.

Stores POST-EQ mono PCM as 16-bit WAV files under config.CACHE_DIR, keyed by

    SHA256(normalized_text + voice_id + model_id + str(voice_settings))

so changing the voice, model, or any voice setting invalidates cleanly.
LRU eviction (by file mtime; a cache hit re-touches the file) keeps the
directory under config.CACHE_MAX_MB.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from . import config
from . import audio

log = logging.getLogger("voice.cache")


def cache_dir() -> Path:
    d = Path(config.CACHE_DIR).expanduser()
    d.mkdir(parents=True, exist_ok=True)
    return d


def normalize_text(text: str) -> str:
    return " ".join(text.split()).strip()


def cache_key(normalized_text: str, settings: dict | None = None) -> str:
    """settings defaults to config.VOICE_SETTINGS; pass the effective dict
    when a per-call override (e.g. dynamic speed) changed it, so each speed
    variant caches separately."""
    s = settings if settings is not None else config.VOICE_SETTINGS
    material = (normalized_text + config.ELEVEN_VOICE_ID + config.MODEL_ID
                + str(s))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _path_for(key: str) -> Path:
    return cache_dir() / f"{key}.wav"


def get(key: str) -> tuple[np.ndarray, int] | None:
    """Cache lookup. Returns (pcm float32 mono, sample_rate) or None.
    A hit re-touches the file so LRU eviction sees it as recently used."""
    path = _path_for(key)
    if not path.is_file():
        return None
    try:
        pcm, sr = sf.read(path, dtype="float32", always_2d=False)
        os.utime(path, None)
        return pcm, int(sr)
    except (OSError, RuntimeError, sf.LibsndfileError) as e:
        log.warning("cache read failed for %s (%s) — treating as miss",
                    path.name, type(e).__name__)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def put(key: str, pcm: np.ndarray, sr: int) -> None:
    """Store post-EQ PCM; never raises (a failed write is just a non-cache)."""
    path = _path_for(key)
    try:
        tmp = path.with_suffix(".tmp.wav")
        sf.write(tmp, pcm, sr, subtype="PCM_16")
        tmp.replace(path)
        _evict_lru()
    except (OSError, RuntimeError) as e:
        log.warning("cache write failed for %s: %s", path.name, type(e).__name__)


def _evict_lru() -> None:
    """Delete oldest-used clips until the cache fits config.CACHE_MAX_MB."""
    limit = config.CACHE_MAX_MB * 1024 * 1024
    try:
        files = [(p, p.stat()) for p in cache_dir().glob("*.wav")]
    except OSError:
        return
    total = sum(st.st_size for _, st in files)
    if total <= limit:
        return
    for p, st in sorted(files, key=lambda t: t[1].st_mtime):
        try:
            p.unlink()
            total -= st.st_size
            log.info("cache evicted %s", p.name)
        except OSError:
            continue
        if total <= limit:
            break


def prerender(lines: list[str]) -> dict[str, bool]:
    """Warm the cache with common phrases (run once, online). Returns
    {line: cached_ok}. Lines already cached are skipped instantly."""
    # NOTE: import from the submodule directly — the package __init__ rebinds
    # the name `speak` to the function, shadowing the module.
    from .speak import synthesize  # local import — speak.py imports this module
    results: dict[str, bool] = {}
    for line in lines:
        norm = normalize_text(line)
        if not norm:
            continue
        key = cache_key(norm)
        if get(key) is not None:
            results[line] = True
            continue
        try:
            pcm = synthesize(norm)
            processed = audio.process(pcm, audio.SYNTH_SAMPLE_RATE)
            put(key, processed, audio.SYNTH_SAMPLE_RATE)
            results[line] = True
            log.info("prerendered: %.60s", norm)
            time.sleep(0.2)  # gentle on the API
        except Exception as e:
            results[line] = False
            log.error("prerender failed for %.60r: %s", norm, type(e).__name__)
    return results
