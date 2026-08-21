"""Canned fast path: hand-written answers for common questions.

A matched question skips STT->route->compose entirely and speaks a curated
answer through the normal TTS path — the ElevenLabs clip cache makes every
repeat play instantly at zero token cost.

The answer file is data/entities/canned_answers.json (env CJ_CANNED_PATH),
hand-editable and mtime hot-reloaded like the entity overlay and gate rules:

    {"entries": [{"id": "...",
                  "match": ["<regex>", ...],   # fullmatch vs normalized text
                  "answer": "..."              # or "answers": ["...", ...]
                 }, ...]}

Matching is deliberately conservative: the WHOLE normalized question must
match one of the entry's regexes (re.fullmatch). Loose keyword matching would
hijack real questions — when in doubt, let the composer answer.

Enable with CJ_CANNED_ENABLED=1. Every public function fails open (returns
None / False); a canned-path bug must never break a spoken turn.
"""
from __future__ import annotations

import json
import os
import random
import re
from pathlib import Path

_DEFAULT_PATH = str(Path(__file__).resolve().parent.parent
                    / "data" / "entities" / "canned_answers.json")

_cache = {"path": None, "mtime": None, "entries": []}


def enabled() -> bool:
    return os.environ.get("CJ_CANNED_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on"}


def normalize(text: str) -> str:
    """Lowercase, drop apostrophes, collapse all other punctuation to spaces —
    so "What's the Rule of Law?" and "whats the rule of law" both match."""
    t = text.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def _load():
    path = os.environ.get("CJ_CANNED_PATH", _DEFAULT_PATH)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return []
    if _cache["path"] == path and _cache["mtime"] == mtime:
        return _cache["entries"]
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    entries = []
    for e in raw.get("entries", []):
        pats = []
        for p in e.get("match", []):
            try:
                pats.append(re.compile(p))
            except re.error as err:
                print(f"[canned] bad regex in {e.get('id')!r} skipped: {err}")
        answers = e.get("answers") or ([e["answer"]] if e.get("answer") else [])
        if pats and answers:
            entries.append({"id": e.get("id", "?"), "patterns": pats,
                            "answers": answers})
    _cache.update(path=path, mtime=mtime, entries=entries)
    print(f"[canned] loaded {len(entries)} entries from {path}")
    return entries


def match(question: str):
    """Return {"id", "answer"} for a matched common question, else None."""
    try:
        if not enabled():
            return None
        norm = normalize(question)
        if not norm:
            return None
        for e in _load():
            if any(p.fullmatch(norm) for p in e["patterns"]):
                return {"id": e["id"], "answer": random.choice(e["answers"])}
    except Exception as err:   # never let the fast path break a turn
        print(f"[canned] match failed open: {type(err).__name__}: {err}")
    return None
