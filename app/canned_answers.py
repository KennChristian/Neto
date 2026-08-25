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

Exception — event mode (2026-08-25, user: "make the event script a bit
flexible"): while the event flag is on, the scripted event_* entries also
match PARAPHRASES of their question, so the emcee need not read the script
word for word. Two extra tests, after the wake/greeting prefix is stripped:
  "gist": [[alt, ...], ...]   every concept group must appear (word-prefix
                              search), and the question must be short
                              (<= EVENT_GIST_MAX_WORDS)
  fuzzy                       difflib ratio >= EVENT_FUZZY_RATIO against one
                              of the entry's "ask" phrasings (STT wobble)
The answers themselves stay verbatim.

Enable with CJ_CANNED_ENABLED=1. Every public function fails open (returns
None / False); a canned-path bug must never break a spoken turn.
"""
from __future__ import annotations

import difflib
import json
import os
import random
import re
from pathlib import Path

EVENT_GIST_MAX_WORDS = 14
EVENT_FUZZY_RATIO = 0.75
# What an emcee says before the actual question: greetings, the wake phrase,
# forms of address. Stripped before the flexible event tests only.
_EVENT_PREFIX_RE = re.compile(
    r"^(?:(?:hi|hello|hey|good (?:morning|afternoon|evening)|okay|ok|so|and|now|po|"
    r"cee ?jap|cjap|cj ?ap|see ?jap|chief justice|mister chief justice|"
    r"justice panganiban|chief|sir|justice)\s+)*")

_DEFAULT_PATH = str(Path(__file__).resolve().parent.parent
                    / "data" / "entities" / "canned_answers.json")

_cache = {"path": None, "mtime": None, "entries": []}


def enabled() -> bool:
    return os.environ.get("CJ_CANNED_ENABLED", "0").strip().lower() in {
        "1", "true", "yes", "on"}


def event_mode() -> bool:
    """Event mode: when the flag file exists, the scripted event_* entries
    take part in voice matching (an emcee's scripted question gets the
    scripted answer). When absent they are voice-inert — only the /event
    page's buttons can play them. Toggled from the /event page; checked per
    call so flips apply instantly, no restart."""
    path = os.environ.get("CJ_CANNED_PATH", _DEFAULT_PATH)
    return os.path.exists(os.path.join(os.path.dirname(path), "event_mode.on"))


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
        gist = [[normalize(a) for a in grp if normalize(a)]
                for grp in (e.get("gist") or []) if isinstance(grp, list)]
        asks = [normalize(a) for a in (e.get("ask") or []) if normalize(a)]
        # Entries with no patterns are legal: they are selected by id via
        # get() (e.g. "out_of_topic", chosen by the input gate's scope),
        # never by transcript matching.
        if answers:
            entries.append({"id": e.get("id", "?"), "patterns": pats,
                            "answers": answers,
                            "gist": [g for g in gist if g], "asks": asks})
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
        skip_event = not event_mode()
        entries = _load()
        for e in entries:
            if skip_event and e["id"].startswith("event_"):
                continue
            if any(p.fullmatch(norm) for p in e["patterns"]):
                return {"id": e["id"], "answer": random.choice(e["answers"])}
        if not skip_event:   # event mode: the script also takes paraphrases
            hit = _event_flexible(norm, entries)
            if hit is not None:
                return hit
    except Exception as err:   # never let the fast path break a turn
        print(f"[canned] match failed open: {type(err).__name__}: {err}")
    return None


def _event_core(norm: str) -> str:
    """The question without the emcee's lead-in ("Hi Cee-Jap, so, ...")."""
    return _EVENT_PREFIX_RE.sub("", norm).strip()


def _gist_hit(core: str, gist) -> bool:
    if not gist or len(core.split()) > EVENT_GIST_MAX_WORDS:
        return False
    return all(any(re.search(r"\b" + re.escape(alt), core) for alt in grp)
               for grp in gist)


def _fuzzy_hit(core: str, asks) -> float:
    return max((difflib.SequenceMatcher(None, core, a).ratio() for a in asks),
               default=0.0)


def _event_flexible(norm: str, entries):
    """Paraphrase matching for event_* entries (event mode only): gist
    concept groups first, then a fuzzy match against the scripted phrasing.
    Returns {"id", "answer"} or None."""
    core = _event_core(norm)
    if not core:
        return None
    best, best_ratio = None, 0.0
    for e in entries:
        if not e["id"].startswith("event_"):
            continue
        if _gist_hit(core, e["gist"]):
            print(f"[canned] event paraphrase (gist) -> {e['id']}: {core!r}")
            return {"id": e["id"], "answer": random.choice(e["answers"])}
        r = _fuzzy_hit(core, e["asks"])
        if r > best_ratio:
            best, best_ratio = e, r
    if best is not None and best_ratio >= EVENT_FUZZY_RATIO:
        print(f"[canned] event paraphrase (fuzzy {best_ratio:.2f}) -> {best['id']}: {core!r}")
        return {"id": best["id"], "answer": random.choice(best["answers"])}
    return None


def get(entry_id: str):
    """Random answer variant for an entry selected by id (not by transcript) —
    e.g. "out_of_topic" when the input gate scopes a question out_of_corpus.
    None when disabled, missing, or on any error (callers fall through to
    the composer)."""
    try:
        if not enabled():
            return None
        for e in _load():
            if e["id"] == entry_id:
                return random.choice(e["answers"])
    except Exception as err:
        print(f"[canned] get({entry_id!r}) failed open: {type(err).__name__}: {err}")
    return None
