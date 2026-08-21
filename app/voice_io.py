"""
Cost-efficient voice I/O for the CJ Panganiban dashboard.

Replaces the prior faster-whisper + Piper TTS stack with OpenAI's
hosted STT (Whisper-1) and TTS (tts-1 / tts-1-hd) — keeping push-to-talk
recording and per-sentence chunked TTS so we never pay for an always-on
realtime audio stream.

Design constraints (per the user's spec):

  - Push-to-talk ONLY: the mic is never continuously open. The user
    presses "Start Talking", speaks, presses "Stop", and we transcribe
    the resulting blob in ONE Whisper call. No streaming STT.

  - Progressive TTS: Claude's response is sentence-chunked; each chunk
    fires an OpenAI TTS request IN PARALLEL via asyncio.gather. The
    audio chunks are concatenated (pydub if available, raw byte
    concatenation otherwise) and returned as one MP3 blob — so the
    Streamlit `st.audio(autoplay=True)` element starts playing the
    full response within ~1-2 s of the text stream finishing.

  - No always-on streaming: we don't use OpenAI's per-minute Realtime
    API; per-utterance Whisper at $0.006/min and per-sentence TTS at
    $0.015/1k chars is roughly 10-20× cheaper.

Per-turn voice-IO cost (late-2025 prices, typical 10-15 s utterance
and 200-300 char response):
  - STT (whisper-1)       : ~$0.001
  - TTS (tts-1, parallel) : ~$0.003 - $0.005
  - Total voice overhead  : ~$0.004 - $0.006

This module deliberately has NO Streamlit imports — it's plain
Python and is reusable from cj_chat.py CLI smoke tests.
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
            "searched by cj_chat (cwd / repo-root / app), or set "
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
            force.append((re.compile(r"(?<![A-Za-z0-9])" + pat + r"(?![A-Za-z0-9])",
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
        text = pattern.sub(phon, text)
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
# voice's base speed, driven by stream_speak.classify_emotion. Solemn lines
# slow down, playful lines pick up. Values are deltas on VOICE_SETTINGS
# speed (0.9 base), clamped to ElevenLabs' 0.7–1.2. Disable with
# CJ_DYNAMIC_SPEED=0 (every sentence then uses the base speed).
_EMOTION_SPEED_DELTA = {
    "solemn": -0.06, "warm": -0.02, "neutral": 0.0,
    "question": 0.02, "emphatic": 0.04, "amused": 0.05,
}


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
    return round(min(1.2, max(0.7, base + _EMOTION_SPEED_DELTA.get(emotion, 0.0))), 3)


def tts_elevenlabs_wav(text: str, out_dir: str = "/dev/shm",
                       speed: float | None = None) -> str:
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
    key = v_cache.cache_key(norm, effective_settings(speed))
    hit = v_cache.get(key)
    if hit is not None:
        pcm, sr = hit
    else:
        pcm = v_audio.process(v_synthesize(norm, speed=speed),
                              v_audio.SYNTH_SAMPLE_RATE)
        sr = v_audio.SYNTH_SAMPLE_RATE
        v_cache.put(key, pcm, sr)
    f = _tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=out_dir)
    f.close()
    sf.write(f.name, pcm, sr, subtype="PCM_16")
    return f.name


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
        if prompt:
            kwargs["prompt"] = prompt
        resp = client.audio.transcriptions.create(**kwargs)
    # response_format="text" returns a plain string; defensively
    # handle the structured-response shape too.
    if isinstance(resp, str):
        return resp.strip()
    text = getattr(resp, "text", "")
    return str(text).strip()


# Wake-window STT prompt: the wake phrase AND its forbidden near-misses as
# contrast vocabulary. A bare "Cee-Jap" in a 1.5s window is an OOV word whisper
# otherwise mangles ("You"), but biasing toward ONLY "Cee-Jap" flips a spoken
# "See Jay" into the wake phrase (WW-5 violation, measured 2026-08-03). Listing
# both lets whisper pick the acoustically closer spelling.
_WAKE_PROMPT = "Words that may occur: Cee-Jap, See Jay, CJ, Japan."

_LOCAL_WHISPER = None


def _local_whisper():
    """Resident faster-whisper model for on-device wake spotting (loaded once).
    CJ_WAKE_LOCAL_MODEL sizes it; tiny/int8 is the Pi 4 budget."""
    global _LOCAL_WHISPER
    if _LOCAL_WHISPER is None:
        from faster_whisper import WhisperModel
        _LOCAL_WHISPER = WhisperModel(os.environ.get("CJ_WAKE_LOCAL_MODEL", "tiny"),
                                      device="cpu", compute_type="int8")
    return _LOCAL_WHISPER


def transcribe(audio_path: str | Path, backend: Optional[str] = None,
               language: Optional[str] = None) -> str:
    """Adapter for develop-branch callers (wake_word.SttKeywordDetector expects
    voice_io.transcribe(path, backend=..., language=...)). backend "local" runs
    faster-whisper ON the robot — the idle wake loop then needs no network and
    costs $0 — with OpenAI whisper-1 as the exception fallback; any other
    backend value goes straight to whisper-1.

    Echo guard (both backends): on noisy windows whisper sometimes parrots the
    bias prompt itself ('Cee-Jap, See Jay, CJ, Japan.') — which contains the
    wake phrase and caused a false wake (journal 2026-08-03 15:59). A real
    visitor never says two-plus contrast terms in one 1.5s breath, so such
    transcripts are dropped."""
    def _local(p):
        segments, _ = _local_whisper().transcribe(
            str(p), language=language or "en", initial_prompt=_WAKE_PROMPT,
            beam_size=1, condition_on_previous_text=False)
        return " ".join(s.text.strip() for s in segments).strip()

    def _cloud(p):
        return transcribe_openai(p, language=language, prompt=_WAKE_PROMPT)

    # Measured on the Pi 4 (2026-08-03): local tiny takes ~5.2s per 1.5s window
    # and misses most spoken forms of "Cee-Jap" — NOT viable as the primary.
    # whisper-1 (~1s, accurate) leads; local is the no-network degraded mode.
    order = [("local", _local), ("openai", _cloud)] if (backend or "").lower() == "local" \
        else [("openai", _cloud), ("local", _local)]
    text = None
    for name, fn in order:
        try:
            text = fn(audio_path)
            break
        except Exception as e:
            print(f"[stt] {name} wake STT failed ({type(e).__name__}: {e}); trying next")
    if text is None:
        return ""
    norm = text.lower()
    echo_hits = ("see jay" in norm) + ("japan" in norm) + bool(re.search(r"\bcj\b", norm))
    if echo_hits >= 2:
        return ""
    return text


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


def estimate_voice_cost(text: str, tts_model: str = TTS_MODEL_DEFAULT) -> dict:
    """Return a dict {tts_usd, …} estimating the cost of one turn's TTS.
    STT cost is estimated separately by the caller because it depends
    on audio duration, which the module doesn't see."""
    n_chars = len(text or "")
    rate = PRICE_PER_KCHAR_TTS_1_HD if "hd" in tts_model else PRICE_PER_KCHAR_TTS_1
    return {
        "tts_chars": n_chars,
        "tts_model": tts_model,
        "tts_usd": round(rate * n_chars / 1000, 5),
    }


def measure_mp3_duration_ms(mp3_bytes: bytes) -> int:
    """Length of an MP3 blob in milliseconds.  Returns 0 on any failure.

    Used by the kiosk to gate wake-engine restart on TTS playback
    completion (PLAN-0008 Task 2 — without this duration we'd risk
    restarting the wake engine onto the tail of our own TTS and
    self-triggering).

    Implementation note (post-mortem 2026-06-09):
        The original implementation used pydub's `AudioSegment.from_file`,
        which shells out to **ffprobe** to parse the MP3 header.  Our
        `_FFMPEG_PATH` discovery only validated `ffmpeg` (the encoder),
        not `ffprobe` (the prober) — so on a Windows kiosk where
        imageio-ffmpeg supplied ffmpeg but ffprobe was absent, the guard
        passed and the call raised `[WinError 2] The system cannot find
        the file specified.` mid-turn, crashing the response.

        We now use **mutagen** (pure-Python, no external binary).  Same
        accurate result, no toolchain dependency, consistent with this
        project's "minimise Windows binary deps" history.  A blanket
        try/except guarantees the caller's text-length fallback (see
        `_run_pipeline`) can always run — a timing helper must never
        be able to crash a turn.
    """
    if not mp3_bytes:
        return 0
    try:
        from mutagen.mp3 import MP3  # type: ignore[import-not-found]
        return int(MP3(io.BytesIO(mp3_bytes)).info.length * 1000)
    except Exception:
        # ImportError (mutagen missing), HeaderNotFoundError (corrupt
        # MP3), FileNotFoundError (shouldn't apply to mutagen but
        # belt-and-braces), or anything else — return 0 so the caller
        # falls back to a text-length estimate. Never raise.
        return 0


def voice_io_summary() -> dict[str, object]:
    """Sidebar-friendly summary of the active OpenAI voice config."""
    return {
        "openai_key_present": bool(os.environ.get("OPENAI_API_KEY")),
        "stt_model": STT_MODEL_DEFAULT,
        "tts_model": TTS_MODEL_DEFAULT,
        "tts_voice": TTS_VOICE_DEFAULT,
        "tts_speed": TTS_SPEED_DEFAULT,
        "pydub_available": _PYDUB_AVAILABLE,
        "ffmpeg_path": _FFMPEG_PATH or "(missing — using raw byte concat)",
        "ffprobe_path": _FFPROBE_PATH or "(missing — pydub from_file will fail; mutagen used for duration)",
    }


__all__ = [
    "transcribe_openai",
    "add_reflective_pauses",
    "sentence_chunks",
    "tts_chunks_parallel_async",
    "tts_concatenate_parallel",
    "measure_mp3_duration_ms",
    "estimate_voice_cost",
    "voice_io_summary",
    "STT_MODEL_DEFAULT",
    "TTS_MODEL_DEFAULT",
    "TTS_VOICE_DEFAULT",
    "TTS_SPEED_DEFAULT",
]
