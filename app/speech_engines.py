"""speech_engines — STT + TTS engines for the CJ robot.

* transcribe_openai(): OpenAI transcription (OPENAI_STT_MODEL) with the persona
  steering prompt and echo guard.
* tts_elevenlabs_wav(): the cloned ElevenLabs voice via the repo-root voice/
  package (clip cache, alignment sidecar, request stitching); emotion speed
  deltas, slew and limits; farewell_settings().
* OpenAI tts-1 chain (tts_concatenate_parallel & co): the fallback used by
  main_voice_robot.speak() and SentenceSpeaker._synth when ElevenLabs fails.

Renamed from voice_io.py on 2026-08-29.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import shutil
import warnings
from pathlib import Path
from typing import Optional

# ============================================================
# ffmpeg discovery — required by pydub for MP3 decoding/encoding
# ============================================================
# Order of preference for the ffmpeg + ffprobe pair:
#   1. system PATH (operator installed ffmpeg system-wide)
#   2. static-ffmpeg's bundled pair (pip install static-ffmpeg) —
#      ships BOTH ffmpeg.exe AND ffprobe.exe, unlike imageio-ffmpeg.
#   3. imageio-ffmpeg's bundled ffmpeg (NO ffprobe — concat works
#      but MP3 duration measurement falls through to mutagen).
#
# Post-mortem 2026-06-09: the prior tier (imageio-ffmpeg only) gave
# us ffmpeg without ffprobe, which silently broke pydub's
# AudioSegment.from_file mid-turn — the concatenation path used in
# _concatenate_mp3_chunks() shells out to ffprobe and crashes on
# Windows when ffprobe is absent. static-ffmpeg fixes that.

# Try static-ffmpeg FIRST so its bundled pair lands on PATH and the
# rest of the discovery (shutil.which) picks both up uniformly.
try:
    import static_ffmpeg  # type: ignore[import-not-found]
    static_ffmpeg.add_paths()  # adds bundled bin dir to os.environ['PATH']
except Exception:
    pass

_FFMPEG_PATH: str | None = (
    shutil.which("ffmpeg")
    or shutil.which("avconv")
)
_FFPROBE_PATH: str | None = shutil.which("ffprobe")

if not _FFMPEG_PATH:
    try:
        import imageio_ffmpeg  # type: ignore[import-not-found]
        _FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        _FFMPEG_PATH = None

# Silence pydub's startup "Couldn't find ffmpeg" warning AND, when
# a binary was supplied, point pydub at it explicitly.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", RuntimeWarning)
    try:
        import pydub  # type: ignore[import-not-found]
        if _FFMPEG_PATH:
            pydub.AudioSegment.converter = _FFMPEG_PATH
            pydub.AudioSegment.ffmpeg = _FFMPEG_PATH
            # ffprobe — prefer the one already resolved on PATH (e.g.
            # static-ffmpeg), then fall back to "alongside ffmpeg"
            # heuristic.
            if _FFPROBE_PATH:
                pydub.AudioSegment.ffprobe = _FFPROBE_PATH
            else:
                _ffprobe_guess = Path(_FFMPEG_PATH).with_name("ffprobe")
                if _ffprobe_guess.with_suffix(".exe").exists():
                    pydub.AudioSegment.ffprobe = str(_ffprobe_guess.with_suffix(".exe"))
                    _FFPROBE_PATH = pydub.AudioSegment.ffprobe
                elif _ffprobe_guess.exists():
                    pydub.AudioSegment.ffprobe = str(_ffprobe_guess)
                    _FFPROBE_PATH = pydub.AudioSegment.ffprobe
        _PYDUB_AVAILABLE = True
    except ImportError:
        _PYDUB_AVAILABLE = False


# ============================================================
# Client factories — lazy, singleton, env-configurable
# ============================================================
_SYNC_CLIENT = None
_ASYNC_CLIENT = None


def _ensure_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add it to one of the .env files "
            "searched by answer_pipeline (cwd / repo-root / app), or set "
            "DOTENV_PATH to point at the file."
        )


def _sync_client():
    """Return a cached synchronous OpenAI client."""
    global _SYNC_CLIENT
    if _SYNC_CLIENT is None:
        _ensure_key()
        from openai import OpenAI  # imported lazily so the module
        _SYNC_CLIENT = OpenAI()    # parses even when openai is absent
    return _SYNC_CLIENT


def _async_client():
    """Return a cached asynchronous OpenAI client (used by parallel TTS)."""
    global _ASYNC_CLIENT
    if _ASYNC_CLIENT is None:
        _ensure_key()
        from openai import AsyncOpenAI
        _ASYNC_CLIENT = AsyncOpenAI()
    return _ASYNC_CLIENT


# ============================================================
# Defaults — overridable via env
# ============================================================
STT_MODEL_DEFAULT = os.environ.get("OPENAI_STT_MODEL", "whisper-1")
TTS_MODEL_DEFAULT = os.environ.get("OPENAI_TTS_MODEL", "tts-1")
# Voice — set via OPENAI_TTS_VOICE.
# Standard tts-1 / tts-1-hd voices: alloy, echo, fable, onyx, nova, shimmer.
# Newer gpt-4o-mini-tts voices: ash, ballad, coral, sage, verse, spruce.
# Default `echo` is a lighter, articulate male voice in the `tts-1`
# voice set — fits CJP's measured judicial register and works on the
# default low-cost tts-1 model (no model swap required).
# Iteration history: nova (wrong gender) → onyx → spruce → echo →
# onyx → echo (current). All remain available via OPENAI_TTS_VOICE.
TTS_VOICE_DEFAULT = os.environ.get("OPENAI_TTS_VOICE", "echo")
# Speech speed — tts-1 supports 0.25 to 4.0. 0.98 sits just below
# normal pace so the delivery still feels measured without dragging,
# which the user landed on after A/B-testing 0.75 → 0.97 → 0.98.
TTS_SPEED_DEFAULT = float(os.environ.get("OPENAI_TTS_SPEED", "0.98"))
# Voice-steering instructions for gpt-4o-mini-tts (accent/pace/tone). Ignored
# by tts-1 (which rejects the param). When set with a gpt-4o* model, `speed`
# is folded into the instructions instead (the steerable model ignores it).
TTS_INSTRUCTIONS_DEFAULT = os.environ.get("OPENAI_TTS_INSTRUCTIONS", "").strip()
# TTS engine switch: "openai" (default, everything above) or "elevenlabs"
# (the cloned voice via the repo-root voice/ package: flash_v2_5 + EQ chain +
# ~/.voice_cache; credentials come from ELEVEN_API_KEY / ELEVEN_VOICE_ID in
# app/.env). Every elevenlabs call site FAILS OPEN to the openai path.
TTS_BACKEND = os.environ.get("CJ_TTS_BACKEND", "openai").strip().lower()

# Filipino pronunciation lexicon (P2 lexicon override map): per-request
# pronunciation directions are appended for exactly the names present in the
# text being synthesized. Hand-editable JSON; hot-reloaded on mtime change.
PRONUNCIATION_LEXICON_PATH = os.environ.get(
    "CJ_PRONUNCIATION_LEXICON",
    str(Path(__file__).resolve().parent.parent / "data" / "entities"
        / "pronunciation_lexicon.json"))
_lex_cache = {"mtime": None, "compiled": [], "force": []}


def _fold_n(s: str) -> str:
    return s.replace("ñ", "n").replace("Ñ", "N").lower()


def _reload_lexicon() -> None:
    try:
        mtime = os.path.getmtime(PRONUNCIATION_LEXICON_PATH)
    except OSError:
        return
    if _lex_cache["mtime"] == mtime:
        return
    try:
        raw = json.loads(open(PRONUNCIATION_LEXICON_PATH, encoding="utf-8").read())
    except (OSError, ValueError):
        return
    _lex_cache["compiled"] = [
        (re.compile(r"(?<![a-z0-9])" + re.escape(_fold_n(k)) + r"(?![a-z0-9])"), k, v)
        for k, v in raw.items()
        if isinstance(v, str) and not k.startswith("_")]
    # "_force": stubborn words the model anglicizes even when hinted — these
    # get their respelling substituted INTO the TTS input text instead.
    force = []
    for k in raw.get("_force", []):
        phon = raw.get(k)
        if isinstance(phon, str):
            pat = re.escape(k).replace("ñ", "[ñn]").replace("Ñ", "[ÑNñn]")
            # 2026-08-25: also catch possessive / plural forms (Panganiban's,
            # Panganibans, PANGANIBAN'S) so the name is read the same way in
            # every form; the suffix is kept, lower-cased.
            force.append((re.compile(r"(?<![A-Za-z0-9])" + pat + r"(['’]?s)?(?![A-Za-z0-9])",
                                     re.IGNORECASE), phon))
    _lex_cache["force"] = force
    _lex_cache["mtime"] = mtime


def _lexicon() -> list:
    """[(compiled pattern, display key, phonetic)] with mtime hot-reload.
    Patterns are compiled once per reload — the lexicon exceeds re's
    512-entry internal cache, so per-call re.search would recompile all.
    """
    _reload_lexicon()
    return _lex_cache["compiled"]


def apply_forced_respellings(text: str) -> str:
    """Substitute the phonetic respelling directly into the TTS input for the
    lexicon's "_force" words. Captions/transcripts keep the real spelling —
    only what the voice engine READS changes."""
    _reload_lexicon()
    for pattern, phon in _lex_cache["force"]:
        text = pattern.sub(lambda m, p=phon: p + (m.group(1) or "").lower(), text)
    return text


def pronunciation_hints(text: str, cap: int = 6) -> str:
    """'Pronounce X as "Y".' lines for lexicon words present in `text`."""
    folded = _fold_n(text)
    hits = []
    for pattern, display, phon in _lexicon():
        if pattern.search(folded):
            hits.append(f'"{display}" as "{phon}"')
            if len(hits) >= cap:
                break
    if not hits:
        return ""
    return " Pronounce " + "; ".join(hits) + "."


# Name pin (2026-09-12, user: "consistent speed whenever Panganiban is
# pronounced because this is a factor of how it speaks Panganiban"). A
# sentence that carries a pinned name is synthesized at ONE fixed speed and
# delivery — the config voice settings, i.e. exactly what the canned clips and
# the pronunciation A/B were rendered with — instead of the emotion-slewed
# values, and it is exempt from the post-synthesis tempo stretch. Neighbouring
# sentences slew from the pinned values, so the seam stays smooth.
#   CJ_NAME_PIN=0                 disable
#   CJ_NAME_PIN_WORDS=a,b         names to pin (default Panganiban)
#   CJ_NAME_PIN_SPEED=0.95        ElevenLabs speed (default: CJ_SPEED_BASE, else config speed;
#                                 user picked 0.95 from a 0.90/0.95/1.00/1.05 A/B, 2026-09-12)
#   CJ_NAME_PIN_DELIVERY=0.5:0.0  stability:style (default: config values)
#   CJ_NAME_PIN_SYLLABLE=ngah:0.30 syllable of the respelled name to time-compress, and to what
#                                 length (WSOLA on that span only; alignment times follow). off = none
#   CJ_NAME_PIN_SEED=4242         fixed ElevenLabs seed for pinned sentences (0 = off). Takes of
#                                 the same text vary more than a 5 % speed step does, so the
#                                 seed is what makes the name come out the same each time.
_name_pin_cache = {"key": None, "pats": []}


def name_pin_enabled() -> bool:
    return os.environ.get("CJ_NAME_PIN", "1").strip().lower() not in {"0", "false", "no", "off"}


def pinned_name_in(text: str) -> bool:
    """True when `text` contains one of the pinned names (any case, possessive too)."""
    if not name_pin_enabled() or not text:
        return False
    words = os.environ.get("CJ_NAME_PIN_WORDS", "Panganiban")
    if _name_pin_cache["key"] != words:
        pats = []
        for w in (x.strip() for x in words.split(",")):
            if w:
                pats.append(re.compile(r"(?<![A-Za-z0-9])" + re.escape(w).replace("ñ", "[ñn]")
                                       + r"(['’]?s)?(?![A-Za-z0-9])", re.IGNORECASE))
        _name_pin_cache.update(key=words, pats=pats)
    return any(p.search(text) for p in _name_pin_cache["pats"])


def name_pin_settings() -> tuple[float, tuple[float, float]]:
    """(speed, (stability, style)) every pinned sentence is rendered with."""
    speed, stab, style = 1.0, 0.5, 0.0
    try:
        import sys as _sys
        root = str(Path(__file__).resolve().parent.parent)
        if root not in _sys.path:
            _sys.path.insert(0, root)
        from voice import config as v_config
        speed = float(v_config.VOICE_SETTINGS.get("speed", speed))
        stab = float(v_config.VOICE_SETTINGS.get("stability", stab))
        style = float(v_config.VOICE_SETTINGS.get("style", style))
    except Exception:
        pass
    for var in ("CJ_SPEED_BASE", "CJ_NAME_PIN_SPEED"):   # later wins
        try:
            speed = float(os.environ.get(var, speed))
        except ValueError:
            pass
    raw = os.environ.get("CJ_NAME_PIN_DELIVERY", "").strip()
    if raw:
        try:
            a, b = raw.split(":")
            stab, style = float(a), float(b)
        except ValueError:
            pass
    speed = round(min(1.2, max(0.7, speed)), 3)
    return speed, (round(min(1.0, max(0.0, stab)), 3), round(min(1.0, max(0.0, style)), 3))


def name_pin_syllable() -> tuple[str, float] | None:
    """CJ_NAME_PIN_SYLLABLE="ngah:0.80" -> ("ngah", 0.8): the syllable of the
    respelled name to time-compress, and the length factor. 2026-09-12 A/B
    (user, T2): "pahng-ngah-NEE-bahn" at 0.90 with the "ngah" at 30 % of its length."""
    raw = os.environ.get("CJ_NAME_PIN_SYLLABLE", "ngah:0.30").strip()
    if not raw or raw.lower() in {"0", "off", "none"}:
        return None
    try:
        syl, f = raw.split(":")
        f = float(f)
    except ValueError:
        return None
    if not syl or not 0.3 <= f < 1.0:
        return None
    return syl, f


def name_pin_shape(pcm, sr: int, align: dict) -> tuple:
    """Shorten the pinned syllable inside every pinned name of a rendered
    clip. `align` is the ElevenLabs character alignment for the text that was
    synthesized (already respelled); its times are rewritten to match. Returns
    (pcm, align, n_changed). Any failure returns the input untouched."""
    spec = name_pin_syllable()
    try:
        chars = align["characters"]
        st = list(align["character_start_times_seconds"])
        en = list(align["character_end_times_seconds"])
    except (KeyError, TypeError):
        return pcm, align, 0
    if spec is None or not chars:
        return pcm, align, 0
    syl, factor = spec
    joined = "".join(chars)
    # the respelled forms of the pinned words, as they appear in the synthesized text
    forms = []
    for w in (x.strip() for x in os.environ.get("CJ_NAME_PIN_WORDS", "Panganiban").split(",")):
        r = apply_forced_respellings(w) if w else ""
        if r and r != w and syl in r:
            forms.append(r)
    if not forms:
        return pcm, align, 0
    import numpy as _np
    spans = []
    for form in forms:
        off = form.find(syl)
        pos = joined.find(form)
        while pos >= 0:
            i = pos + off
            spans.append((i, i + len(syl) - 1))
            pos = joined.find(form, pos + 1)
    if not spans:
        return pcm, align, 0
    try:
        from audiotsm import wsola
        from audiotsm.io.array import ArrayReader, ArrayWriter
    except Exception:
        return pcm, align, 0
    pcm = _np.asarray(pcm, dtype=_np.float32)
    xf = int(0.012 * sr)
    n = 0
    for i0, i1 in sorted(spans, reverse=True):     # right to left: earlier sample indices stay valid
        a, b = int(st[i0] * sr), int(en[i1] * sr)
        if b - a < 4 * xf or a < xf or b + xf > len(pcm):
            continue
        seg = pcm[a:b]
        # target length includes the two crossfade margins, so the syllable
        # itself ends up at exactly `factor` of its rendered length
        target = int(factor * (b - a)) + 2 * xf
        pad = int(0.3 * sr)
        padded = _np.concatenate([seg, _np.zeros(pad, _np.float32)])
        reader = ArrayReader(padded[None, :].copy())
        writer = ArrayWriter(channels=1)
        wsola(channels=1, speed=len(seg) / target).run(reader, writer)
        o = writer.data[0].astype(_np.float32)
        if len(o) < target:                      # WSOLA under-delivers by up to a frame
            o = _np.concatenate([o, _np.zeros(target - len(o), _np.float32)])
        o = o[:target]
        ramp = _np.linspace(0, 1, xf, dtype=_np.float32)
        head, tail = pcm[:a], pcm[b:]
        o[:xf] = o[:xf] * ramp + head[-xf:] * (1 - ramp)
        o[-xf:] = o[-xf:] * (1 - ramp) + tail[:xf] * ramp
        pcm = _np.concatenate([head[:-xf], o, tail[xf:]])
        removed = (b - a) - len(o) + 2 * xf          # samples taken out of the timeline
        dt = removed / sr
        t_a, t_b = st[i0], en[i1]
        for k in range(len(st)):
            for arr in (st, en):
                t = arr[k]
                if t <= t_a:
                    continue
                arr[k] = (t_a + (t - t_a) * (1 - dt / (t_b - t_a))) if t <= t_b else t - dt
        n += 1
    align = dict(align)
    align["character_start_times_seconds"], align["character_end_times_seconds"] = st, en
    return pcm, align, n


def name_pin_seed() -> int | None:
    try:
        v = int(os.environ.get("CJ_NAME_PIN_SEED", "4242"))
    except ValueError:
        v = 4242
    return v if v > 0 else None


def name_pin_voice_settings() -> dict:
    """The full voice_settings dict a pinned sentence is rendered with."""
    import sys as _sys
    root = str(Path(__file__).resolve().parent.parent)
    if root not in _sys.path:
        _sys.path.insert(0, root)
    from voice.speak import effective_settings
    spd, (stab, style) = name_pin_settings()
    vs = effective_settings(spd)
    vs["stability"], vs["style"] = stab, style
    return vs


def tts_create_kwargs(model: str, voice: str, speed: float, text: str) -> dict:
    """Kwargs for audio.speech.create across both engines (tts-1 vs gpt-4o*)."""
    text = apply_forced_respellings(text)   # stubborn words: respell in-text
    kw = {"model": model, "voice": voice, "input": text}
    if TTS_INSTRUCTIONS_DEFAULT and model.startswith("gpt-4o"):
        kw["instructions"] = TTS_INSTRUCTIONS_DEFAULT + pronunciation_hints(text)
    else:
        kw["speed"] = speed
    return kw


# Dynamic speaking speed (2026-08-20): per-sentence delta on the cloned
# voice's base speed, driven by speech_streaming.classify_emotion. Solemn lines
# slow down, playful lines pick up. Values are deltas on VOICE_SETTINGS
# speed (0.9 base), clamped to ElevenLabs' 0.7–1.2. Disable with
# CJ_DYNAMIC_SPEED=0 (every sentence then uses the base speed).
# Kept small (2026-08-25, user: "his voice changes a bit"): a tempo jump
# between adjacent sentences reads as a change of voice. Was -0.06..+0.05.
_EMOTION_SPEED_DELTA = {
    "solemn": -0.04, "warm": -0.02, "neutral": 0.0,
    "question": 0.01, "emphatic": 0.03, "amused": 0.03,
}   # widened 2026-08-30 (user: "widen the dynamic speaking speed a bit"); was ±0.02


# Dynamic-speed limits (2026-08-29, user: "limit the dynamic speaking speed").
# A 0.80–1.20 sweep on a 3-sentence passage showed 0.90–1.05 is one natural
# pace band; 1.10+ turns hurried/clipped and 0.85- drags. Emotion deltas and
# the slew are clamped to [CJ_SPEED_MIN, CJ_SPEED_MAX] (default 0.95–1.05)
# instead of ElevenLabs' full 0.7–1.2, so no delta or base change can push
# an answer out of that band. Only applies to dynamic speed; farewells and
# the manual Say box use their own settings.
def _speed_limits() -> tuple[float, float]:
    try:
        lo = float(os.environ.get("CJ_SPEED_MIN", "0.94"))
        hi = float(os.environ.get("CJ_SPEED_MAX", "1.03"))   # widened 2026-08-30 (was 0.95/1.00)
    except ValueError:
        lo, hi = 0.94, 1.03
    lo, hi = max(0.7, lo), min(1.2, hi)
    return (lo, hi) if lo <= hi else (hi, lo)


def _clamp_speed(v: float) -> float:
    lo, hi = _speed_limits()
    return round(min(hi, max(lo, v)), 3)


def emotion_speed(emotion: str) -> float | None:
    """Speed for a sentence of this emotion, or None (= base) when dynamic
    speed is disabled or the voice config is unavailable."""
    if os.environ.get("CJ_DYNAMIC_SPEED", "1") != "1":
        return None
    try:
        import sys as _sys
        root = str(Path(__file__).resolve().parent.parent)
        if root not in _sys.path:
            _sys.path.insert(0, root)
        from voice import config as v_config
        base = float(v_config.VOICE_SETTINGS.get("speed", 0.9))
    except Exception:
        base = 0.9
    try:   # CJ_SPEED_BASE (2026-08-30, "he reads a bit fast"): base pace for
        base = float(os.environ.get("CJ_SPEED_BASE", base))   # composed answers only —
    except ValueError:                                         # curated clips keep the
        pass                                                   # config speed (cache keys)
    return _clamp_speed(base + _EMOTION_SPEED_DELTA.get(emotion, 0.0))


# Smooth speed transitions (2026-08-29, user: "make sure the transition per
# sentence on the dynamic voice speed is smooth"): the pace glides toward
# each sentence's emotion target instead of jumping to it. Max change
# between adjacent sentences = CJ_SPEED_MAX_STEP (default 0.01, i.e. a
# solemn→amused swing of 0.04 is spread over four sentences). The first
# sentence of an answer starts from the base speed so the answer never
# opens with a jump either.
def smooth_speed(target: float | None, prev: float | None) -> float | None:
    """Slew `prev` (last sentence's speed; None = start of answer) toward
    `target`. Returns None when dynamic speed is off (target None)."""
    if target is None:
        return None
    try:
        step = float(os.environ.get("CJ_SPEED_MAX_STEP", "0.02"))
    except ValueError:
        step = 0.02
    if step <= 0:
        return target
    if prev is None:
        try:
            import sys as _sys
            root = str(Path(__file__).resolve().parent.parent)
            if root not in _sys.path:
                _sys.path.insert(0, root)
            from voice import config as v_config
            prev = float(v_config.VOICE_SETTINGS.get("speed", 0.9))
        except Exception:
            prev = 0.9
        try:
            prev = float(os.environ.get("CJ_SPEED_BASE", prev))
        except ValueError:
            pass
    delta = max(-step, min(step, target - prev))
    return _clamp_speed(prev + delta)


# Per-emotion delivery on Flash v2.5 (2026-08-30, user A/B'd three takes of an
# emphatic line and picked the strongest: stability .30 / style .55). The same
# per-sentence emotion tag that drives gestures and pace now also sets the
# ElevenLabs stability/style, so the delivery follows the meaning without a
# different model (Eleven v3 was tried and sounded less like him). Composed
# answers are not cached, so this costs no re-rendering; curated text (canned
# clips, farewells, the out-of-topic deflection) stays at the base settings.
# Override any entry with CJ_VOICE_<EMOTION>="stability:style"; disable all
# with CJ_DYNAMIC_DELIVERY=0 (speed-only, as before).
_EMOTION_DELIVERY = {
    "neutral": None,                 # base VOICE_SETTINGS
    "solemn": (0.55, 0.15),
    "warm": (0.40, 0.30),
    "question": (0.45, 0.20),
    "emphatic": (0.30, 0.55),
    "amused": (0.30, 0.55),
}


def smooth_delivery(target: tuple | None, prev: tuple | None) -> tuple:
    """Slew (stability, style) toward the emotion target by at most
    CJ_DELIVERY_STEP_STABILITY / _STYLE per sentence (defaults 0.05 / 0.10),
    starting from the base settings. 2026-08-30, user: "there are times his
    voice changes" — adjacent sentences jumping 0.50/0.00 → 0.30/0.55 read as
    a different voice; a gradual glide does not."""
    try:
        import sys as _sys
        root = str(Path(__file__).resolve().parent.parent)
        if root not in _sys.path:
            _sys.path.insert(0, root)
        from voice import config as v_config
        base = (float(v_config.VOICE_SETTINGS.get("stability", 0.5)),
                float(v_config.VOICE_SETTINGS.get("style", 0.0)))
    except Exception:
        base = (0.5, 0.0)
    # 2026-08-31: a CJ_VOICE_NEUTRAL override is the operator's chosen resting
    # voice — start every answer there, not at the code base, or the first
    # sentences of each answer would always be at 0.50 while the slew catches up.
    try:
        neutral = emotion_delivery_target("neutral")
        if neutral:
            base = neutral
    except Exception:
        pass
    tgt = target or base
    cur = prev or base
    try:
        ds = float(os.environ.get("CJ_DELIVERY_STEP_STABILITY", "0.05"))
        dy = float(os.environ.get("CJ_DELIVERY_STEP_STYLE", "0.10"))
    except ValueError:
        ds, dy = 0.05, 0.10
    stab = cur[0] + max(-ds, min(ds, tgt[0] - cur[0]))
    style = cur[1] + max(-dy, min(dy, tgt[1] - cur[1]))
    return (round(stab, 3), round(style, 3))


def emotion_delivery_target(emotion: str) -> tuple | None:
    """(stability, style) target for an emotion, None = base settings."""
    if os.environ.get("CJ_DYNAMIC_DELIVERY", "1").strip().lower() in {"0", "off", "false"}:
        return None
    spec = os.environ.get(f"CJ_VOICE_{(emotion or 'neutral').upper()}")
    try:
        if spec:
            stab, _, style = spec.partition(":")
            return (float(stab), float(style))
    except ValueError:
        pass
    return _EMOTION_DELIVERY.get(emotion or "neutral")


# Farewell delivery (A/B'd by ear 2026-08-25, user picked the most expressive
# of three): lower stability + style exaggeration + a touch slower makes the
# goodbye sound warm instead of flat. Separate cache keys (settings are part
# of the key). Tunable via CJ_FAREWELL_STABILITY / _STYLE / _SPEED.
def farewell_settings() -> dict | None:
    """voice_settings dict for farewells, or None when the ElevenLabs voice
    config is unavailable (callers then fall back to the default delivery)."""
    try:
        import sys as _sys
        root = str(Path(__file__).resolve().parent.parent)
        if root not in _sys.path:
            _sys.path.insert(0, root)
        from voice.speak import effective_settings
        st = effective_settings(float(os.environ.get("CJ_FAREWELL_SPEED", "0.97")))
        st["stability"] = float(os.environ.get("CJ_FAREWELL_STABILITY", "0.30"))
        st["style"] = float(os.environ.get("CJ_FAREWELL_STYLE", "0.50"))
        return st
    except Exception:
        return None


def tts_elevenlabs_wav(text: str, out_dir: str = "/dev/shm",
                       speed: float | None = None,
                       previous_text: str | None = None,
                       voice_settings: dict | None = None,
                       previous_request_ids: list | None = None,
                       meta_out: dict | None = None,
                       seed: int | None = None) -> str:
    """Synthesize with the cloned voice (repo-root voice/ package) and return
    the path of a 24 kHz mono PCM_16 wav. Uses the local clip cache, so
    repeat lines are instant. Raises on any failure — callers keep the
    openai path as the fallback.

    pronunciation_hints are OpenAI-only (no instructions param here). The
    lexicon's forced respellings are OFF by default — the cloned Filipino
    voice reads Tagalog natively — but can be enabled with CJ_ELEVEN_RESPELL=1
    (A/B-tested 2026-08-19) if specific names still come out wrong. Entity
    correction (process_tts_sentence) still happens at the call sites,
    engine-agnostic."""
    import sys as _sys
    import tempfile as _tempfile
    root = str(Path(__file__).resolve().parent.parent)
    if root not in _sys.path:
        _sys.path.insert(0, root)
    import soundfile as sf
    from voice import audio as v_audio
    from voice import cache as v_cache
    from voice.speak import effective_settings, synthesize as v_synthesize

    if os.environ.get("CJ_ELEVEN_RESPELL", "0") == "1":
        text = apply_forced_respellings(text)
    norm = v_cache.normalize_text(text)
    settings = voice_settings or effective_settings(speed)  # full override (farewells)
    key = v_cache.cache_key(norm, settings if seed is None else
                            {**settings, "_seed": int(seed), "_shape": os.environ.get("CJ_NAME_PIN_SYLLABLE", "ngah:0.30")})
    align_path = v_cache.cache_dir() / f"{key}.align.json"
    words = None
    hit = v_cache.get(key)
    if hit is not None:
        try:  # usage tally: cache hits are not billed by ElevenLabs
            import usage_meter
            usage_meter.elevenlabs(len(norm), cached=True)
        except Exception:
            pass
        pcm, sr = hit
        try:  # sidecar exists only for clips synthesized post-2026-08-22
            words = json.loads(align_path.read_text())
        except (OSError, ValueError):
            words = None
    else:
        align: dict = {}
        pcm = v_audio.process(v_synthesize(norm, speed=speed, align_out=align,
                                           previous_text=previous_text,
                                           settings=settings,
                                           previous_request_ids=previous_request_ids,
                                           seed=seed),
                              v_audio.SYNTH_SAMPLE_RATE)
        if meta_out is not None:   # request stitching id for the next sentence
            meta_out["request_id"] = align.get("_request_id")
            meta_out["cached"] = False
        sr = v_audio.SYNTH_SAMPLE_RATE
        if seed is not None:       # pinned name: shape its syllable before the clip is cached
            try:
                pcm, align, _n = name_pin_shape(pcm, sr, align)
                if _n:
                    print(f"[namepin] syllable shaped in {_n} name(s)")
            except Exception as _e:
                print(f"[namepin] shaping skipped ({type(_e).__name__}: {_e})")
        v_cache.put(key, pcm, sr)
        try:  # usage tally: billed chars, counted only after synthesis succeeded
            import usage_meter
            usage_meter.elevenlabs(len(norm), cached=False)
        except Exception:
            pass
        words = _align_to_words(align)
        if words:
            try:
                align_path.write_text(json.dumps(words))
            except OSError:
                pass
    f = _tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=out_dir)
    f.close()
    sf.write(f.name, pcm, sr, subtype="PCM_16")
    if words:
        try:  # sidecar rides beside the temp wav for the speaking feed
            with open(f.name + ".align.json", "w") as af:
                json.dump(words, af)
        except OSError:
            pass
    return f.name


def _align_to_words(align: dict) -> list | None:
    """ElevenLabs character alignment → [[word, start_s, end_s], ...]."""
    try:
        triples = zip(align["characters"],
                      align["character_start_times_seconds"],
                      align["character_end_times_seconds"])
    except (KeyError, TypeError):
        return None
    words, cur, s0, e0 = [], "", 0.0, 0.0
    for ch, s, e in triples:
        if ch.isspace():
            if cur:
                words.append([cur, round(s0, 3), round(e0, 3)])
                cur = ""
            continue
        if not cur:
            s0 = s
        cur += ch
        e0 = e
    if cur:
        words.append([cur, round(s0, 3), round(e0, 3)])
    return words or None


# ============================================================
# STT — one Whisper call per recording
# ============================================================
def transcribe_openai(
    audio_path: str | Path,
    model: str | None = None,
    language: Optional[str] = None,
    prompt: Optional[str] = None,
) -> str:
    """Transcribe an audio file via OpenAI Whisper API.

    Called once per push-to-talk recording. The file is opened in
    binary mode and POSTed to OpenAI; the response is plain text.

    Cost (whisper-1, late 2025): $0.006 per minute of audio.

    Args:
        audio_path: path to a WAV / MP3 / WEBM / OGG / M4A file.
        model: override STT_MODEL_DEFAULT (whisper-1).
        language: optional 2-letter language hint ("en", "tl");
                  None lets Whisper auto-detect.

    Returns:
        Trimmed transcript string. Empty string if Whisper returned
        nothing usable.
    """
    client = _sync_client()
    audio_path = Path(audio_path)
    with open(audio_path, "rb") as f:
        kwargs: dict = {
            "model": model or STT_MODEL_DEFAULT,
            "file": f,
            "response_format": "text",
        }
        if language:
            kwargs["language"] = language
        if prompt is None:   # steer the decoder toward Taglish + our names (2026-08-25)
            prompt = os.environ.get("CJ_STT_PROMPT", _STT_PROMPT_DEFAULT).strip()
        if prompt:
            kwargs["prompt"] = prompt
        resp = client.audio.transcriptions.create(**kwargs)
    try:  # usage tally (fails open)
        import wave, usage_meter
        with wave.open(str(audio_path), "rb") as w:
            secs = w.getnframes() / float(w.getframerate())
        usage_meter.openai_stt(secs)
    except Exception:
        pass
    # response_format="text" returns a plain string; defensively
    # handle the structured-response shape too.
    text = resp.strip() if isinstance(resp, str) else str(getattr(resp, "text", "")).strip()
    # Echo guard (2026-08-25 review): on noisy/short captures the model
    # returns the steering prompt itself (journal 15:45-15:48: "Sige po. Ano
    # po ang..." x5, the full prompt once) — treat that as silence.
    if text and prompt and _echoes_stt_prompt(text, prompt):
        print(f"[stt] discarded — transcript echoes the STT prompt: {text[:80]!r}")
        return ""
    return text


# Default steering prompt: a DESCRIPTION, deliberately not ending in an
# example utterance — a dangling "Sige po. Ano po ang…" was parroted back as
# the transcript on noise and the robot answered it (2026-08-25).
_STT_PROMPT_DEFAULT = (
    "A conversation in English and Filipino (Tagalog, Taglish) with retired "
    "Philippine Chief Justice Artemio Panganiban about law, liberty and "
    "prosperity, the Supreme Court, and the Foundation for Liberty and Prosperity.")


def _echoes_stt_prompt(text: str, prompt: str) -> bool:
    """True if `text` is (a chunk of) the STT prompt rather than speech: a
    >=3-word contiguous slice of the prompt, or a long transcript that is
    mostly prompt vocabulary with a >=6-word contiguous overlap."""
    import re as _re
    tw = _re.findall(r"[^\W_]+", text.lower())
    pw = _re.findall(r"[^\W_]+", prompt.lower())
    if len(tw) < 3 or not pw:
        return False
    # common contiguous runs (DP); mark transcript words inside runs >= 4
    best, prev, covered = 0, [0] * (len(pw) + 1), [False] * len(tw)
    for i, a in enumerate(tw):
        cur = [0] * (len(pw) + 1)
        for j, b in enumerate(pw, 1):
            if a == b:
                cur[j] = prev[j - 1] + 1
                best = max(best, cur[j])
                if cur[j] >= 4:
                    for k in range(i - cur[j] + 1, i + 1):
                        covered[k] = True
        prev = cur
    if best >= len(tw):          # the whole transcript is a slice of the prompt
        return True
    if len(tw) >= 5 and tw[:5] == pw[:5]:   # paraphrased echo: opens like the prompt
        return True
    # a long transcript made mostly of prompt phrases (>= 4 words in a row):
    # a real question reuses our names, not our sentence structure
    return len(tw) >= 8 and sum(covered) / len(tw) >= 0.7


# ============================================================
# Cadence enhancement — inject reflective pauses for CJP's voice
# ============================================================
# CJP speaks deliberately and groups his sentences into distinct
# phrases. We pre-insert ellipses after his signature reflective
# markers so the TTS engine takes a longer, more thoughtful breath
# at those points (in addition to the slower base TTS_SPEED_DEFAULT).
#
# Rules are conservative: only well-known CJP markers, only when
# followed by a comma (so we don't trigger inside quoted text or
# at sentence boundaries that already have natural pauses).
_REFLECTIVE_MARKERS = [
    r"In my humble opinion",
    r"In my view",
    r"In my respectful view",
    r"With due respect",
    r"Au contraire",
    r"IMHO",
    r"In conclusion",
    r"More importantly",
    r"That said",
    r"Indeed",
    r"Allow me to say",
    r"Permit me to say",
    r"As I have said before",
    r"As I have written",
]
_CADENCE_RE = re.compile(
    r"\b(" + "|".join(_REFLECTIVE_MARKERS) + r"),",
    re.IGNORECASE,
)


def add_reflective_pauses(text: str) -> str:
    """Inject ellipses after CJP's signature reflective markers.

    Converts e.g. "In my humble opinion, the rule of law…" into
    "In my humble opinion... the rule of law…" — OpenAI TTS treats
    the ellipsis as a longer reflective breath than a comma.

    Conservative by design: only touches the ~14 markers in
    `_REFLECTIVE_MARKERS`. Leaves the rest of the text alone so we
    don't accidentally split mid-thought.
    """
    if not text:
        return text
    return _CADENCE_RE.sub(r"\1...", text)


# ============================================================
# Sentence chunking — pack text into TTS-ready bites
# ============================================================
# Sentence boundary regex: end punctuation followed by whitespace, OR
# a blank line. The negative lookbehind `(?<!\.\.)` keeps us from
# splitting on the LAST period of an ellipsis (`...`) — those are
# reflective pauses, not sentence terminators.
_SENTENCE_END = re.compile(r"(?<=[.!?])(?<!\.\.)\s+|\n\n+")
_MIN_CHUNK_CHARS = 30   # smaller than this wastes an API call
_MAX_CHUNK_CHARS = 240  # OpenAI TTS handles this gracefully; longer chunks
                        #   delay first-audio-out for the slowest sentence


def sentence_chunks(text: str) -> list[str]:
    """Split text into TTS-ready chunks.

    Each chunk ends at a sentence boundary and is roughly 30-240 chars.
    Very short trailing fragments are merged into their neighbour so we
    don't fire one TTS call per stray exclamation.
    """
    text = (text or "").strip()
    if not text:
        return []

    raw_pieces = [p.strip() for p in _SENTENCE_END.split(text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for piece in raw_pieces:
        candidate = f"{buf} {piece}".strip() if buf else piece
        if len(candidate) <= _MAX_CHUNK_CHARS:
            buf = candidate
        else:
            if buf:
                chunks.append(buf)
            buf = piece
    if buf:
        chunks.append(buf)

    # Merge any chunk shorter than _MIN_CHUNK_CHARS into the previous.
    merged: list[str] = []
    for c in chunks:
        if merged and len(c) < _MIN_CHUNK_CHARS:
            merged[-1] = f"{merged[-1]} {c}".strip()
        else:
            merged.append(c)
    return merged


# ============================================================
# Async parallel TTS — fan-out per sentence, gather, concatenate
# ============================================================
async def _tts_one_async(client, text: str, voice: str, model: str, speed: float) -> bytes:
    """One TTS call. Uses with_streaming_response so OpenAI flushes
    bytes as they're generated — but we still consume the whole stream
    here because Streamlit's `st.audio` needs a complete blob."""
    async with client.audio.speech.with_streaming_response.create(
        response_format="mp3",
        **tts_create_kwargs(model, voice, speed, text),
    ) as response:
        out = bytearray()
        async for chunk in response.iter_bytes():
            out.extend(chunk)
        return bytes(out)


async def tts_chunks_parallel_async(
    text: str,
    voice: str = TTS_VOICE_DEFAULT,
    model: str = TTS_MODEL_DEFAULT,
    speed: float = TTS_SPEED_DEFAULT,
    apply_cadence: bool = True,
) -> list[bytes]:
    """Fire TTS for every sentence chunk concurrently. Returns a list
    of MP3 byte blobs in source order.

    When `apply_cadence` is True (default), the text is passed through
    `add_reflective_pauses()` so CJP's signature markers get a longer
    reflective breath. Set to False for a raw passthrough during
    debugging or when testing alternative voices.
    """
    client = _async_client()
    if apply_cadence:
        text = add_reflective_pauses(text)
    chunks = sentence_chunks(text)
    if not chunks:
        return []
    return list(await asyncio.gather(
        *[_tts_one_async(client, c, voice, model, speed) for c in chunks]
    ))


# ============================================================
# Audio concatenation — pydub if available, raw fallback otherwise
# ============================================================
def _concatenate_mp3_chunks(chunks: list[bytes]) -> bytes:
    """Concatenate per-sentence MP3 blobs into one playable MP3.

    Three-tier fallback:
      1. pydub + ffmpeg present  → clean re-encoded concatenation
         (no frame-boundary artefacts).
      2. pydub installed, ffmpeg missing  → skip pydub entirely and
         fall back to raw byte concatenation. We catch every
         exception in case pydub's import succeeded but a runtime
         decode still fails on systems where the ffmpeg binary is
         malformed or unreadable.
      3. pydub not installed     → raw byte concatenation.

    OpenAI's `tts-1` returns constant-bitrate MP3, which concatenates
    reasonably well at the byte level. Strict players may produce a
    soft click at chunk seams; the audio player in browsers (Streamlit
    uses HTML5 <audio>) handles this gracefully.
    """
    if not chunks:
        return b""
    if len(chunks) == 1:
        return chunks[0]
    if not (_PYDUB_AVAILABLE and _FFMPEG_PATH):
        return b"".join(chunks)
    try:
        from pydub import AudioSegment  # type: ignore[import-not-found]
        segments = [
            AudioSegment.from_file(io.BytesIO(c), format="mp3") for c in chunks
        ]
        combined = segments[0]
        for s in segments[1:]:
            combined = combined + s
        out = io.BytesIO()
        combined.export(out, format="mp3")
        return out.getvalue()
    except Exception:
        # Decoder errors, ffmpeg subprocess failures, file-handle issues —
        # never let a TTS-concat error block the response from reaching
        # the user. Fall back to raw concat.
        return b"".join(chunks)


# ============================================================
# Top-level synchronous API for Streamlit
# ============================================================
def tts_concatenate_parallel(
    text: str,
    voice: str | None = None,
    model: str | None = None,
    speed: float | None = None,
) -> bytes:
    """The single function the dashboard calls.

    Returns one MP3 byte blob synthesised by parallel per-sentence
    OpenAI TTS calls and concatenated end-to-end. Total wall-clock
    time ≈ the slowest single sentence (because the calls run
    concurrently), not the sum of all of them.
    """
    audio_chunks = asyncio.run(
        tts_chunks_parallel_async(
            text,
            voice=voice or TTS_VOICE_DEFAULT,
            model=model or TTS_MODEL_DEFAULT,
            speed=speed if speed is not None else TTS_SPEED_DEFAULT,
        )
    )
    return _concatenate_mp3_chunks(audio_chunks)


# ============================================================
# Cost estimator (advisory — printed in operator dashboard)
# ============================================================
# Late-2025 OpenAI list prices ($/1K of the relevant unit)
PRICE_PER_KCHAR_TTS_1 = 0.015
PRICE_PER_KCHAR_TTS_1_HD = 0.030
PRICE_PER_MIN_WHISPER = 0.006


__all__ = [
    "transcribe_openai",
    "add_reflective_pauses",
    "sentence_chunks",
    "tts_chunks_parallel_async",
    "tts_concatenate_parallel",
    "STT_MODEL_DEFAULT",
    "TTS_MODEL_DEFAULT",
    "TTS_VOICE_DEFAULT",
    "TTS_SPEED_DEFAULT",
]
