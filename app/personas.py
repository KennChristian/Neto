"""Personas — both characters loaded at boot, one active (2026-09-10).

Two Reachy Mini units, two characters:

* ``cjap`` — Chief Justice Panganiban. Composes live from the corpus
  (router + composer), speaks with the cloned ElevenLabs voice
  ``ELEVEN_VOICE_ID``. Prompt: ``corpus/voice/voice_card.md``.
* ``host`` — the Host. Never composes, never runs the router or the
  composer. One pre-rendered intro line (rotating variants), pre-rendered
  duet playback, then silent. Authoring brief: ``corpus/voice/host_card.md``
  (used by the render scripts, never as a runtime prompt). Voice:
  ``ELEVEN_HOST_VOICE_ID`` (only the render scripts synthesise with it).

Which machine plays which is ``cjap_is`` (alpha | beta), held by the lease
authority (dashboard/console.py) and delivered to each robot in its lease
reply. Both cards and both voice ids are loaded here at boot so a switch is
``activate()`` — no restart, no corpus reload. When the authority is
unreachable the robot keeps its last known persona (losing the mic is
safe; losing the persona mid-sentence is not) — that is floor_lease's job;
this module just makes activation cheap and idempotent.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

PERSONAS = ("cjap", "host")
ROOT = Path(__file__).resolve().parent.parent
VOICE_CARD = ROOT / "corpus" / "voice" / "voice_card.md"
HOST_CARD = ROOT / "corpus" / "voice" / "host_card.md"

_state = {"active": None, "loaded": False, "cards": {}, "voices": {}, "warnings": []}
_lock = threading.Lock()


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def load(log=print) -> dict:
    """Read both cards and both voice ids once. A missing host card is a
    warning, not an error: the host role only needs its PRE-RENDERED audio
    at runtime (data/prerendered/), the card is for the render scripts."""
    with _lock:
        if _state["loaded"]:
            return _state
        cards = {"cjap": _read(VOICE_CARD), "host": _read(HOST_CARD)}
        voices = {"cjap": os.environ.get("ELEVEN_VOICE_ID", "").strip() or None,
                  "host": os.environ.get("ELEVEN_HOST_VOICE_ID", "").strip() or None}
        warnings = []
        if cards["cjap"] is None:
            warnings.append(f"voice card missing: {VOICE_CARD}")
        if cards["host"] is None:
            warnings.append(f"host card not on disk yet: {HOST_CARD} (host role plays pre-rendered audio only)")
        if not voices["cjap"]:
            warnings.append("ELEVEN_VOICE_ID unset — Panganiban falls back to the OpenAI voice")
        if not voices["host"]:
            warnings.append("ELEVEN_HOST_VOICE_ID unset — only the render scripts need it")
        _state.update(cards=cards, voices=voices, warnings=warnings, loaded=True)
        for w in warnings:
            log(f"[persona] {w}")
        log(f"[persona] loaded: voice card {len(cards['cjap'] or '')} chars, "
            f"host card {len(cards['host'] or '')} chars, voices "
            f"cjap={'set' if voices['cjap'] else 'unset'} host={'set' if voices['host'] else 'unset'}")
        return _state


def active() -> str | None:
    return _state["active"]


def is_cjap() -> bool:
    return _state["active"] == "cjap"


def is_host() -> bool:
    return _state["active"] == "host"


def activate(persona: str | None, log=print) -> bool:
    """Make `persona` the live one. Idempotent, cheap, no I/O beyond a log
    line: points the ElevenLabs voice at the right id. Returns True on a
    change. None = no persona known yet (fresh boot before the first lease
    reply): nothing speaks, nothing listens."""
    if persona is not None and persona not in PERSONAS:
        log(f"[persona] ignoring unknown persona {persona!r}")
        return False
    load(log)
    with _lock:
        if persona == _state["active"]:
            return False
        prev, _state["active"] = _state["active"], persona
    voice_id = _state["voices"].get(persona) if persona else None
    if voice_id:
        try:
            root = str(ROOT)
            if root not in sys.path:
                sys.path.insert(0, root)
            from voice import config as vconfig   # repo-root cloned-voice package
            vconfig.ELEVEN_VOICE_ID = voice_id    # read at synthesis time by voice/speak.py
        except Exception as e:
            log(f"[persona] voice id not switched ({type(e).__name__}: {e})")
    os.environ["CJ_ACTIVE_PERSONA"] = persona or ""
    log(f"[persona] ACTIVE: {persona or 'none'}" + (f" (was {prev})" if prev else "")
        + (" — composes live from the corpus" if persona == "cjap" else
           " — intro + pre-rendered duet only; router/composer OFF" if persona == "host" else ""))
    return True


def status() -> dict:
    return {"active": _state["active"], "loaded": _state["loaded"],
            "cards": {k: (len(v) if v else 0) for k, v in _state["cards"].items()},
            "voices": {k: bool(v) for k, v in _state["voices"].items()},
            "warnings": list(_state["warnings"])}
