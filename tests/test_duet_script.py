"""The duet script and its renderer (2026-09-12).

DUET mode trades PRE-RENDERED lines between the two robots with no microphone
and no network — the attract loop for an empty room, and the fallback when the
venue router dies. These lines are words written ahead of time for a living
person, so they carry exactly the fidelity risk the live pipeline exists to
avoid: every one of them declares where its phrasing comes from, and no line
may assert a specific the corpus cannot back.
"""
from __future__ import annotations

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "corpus", "voice", "duet_script.json")
DOC = json.load(open(SCRIPT, encoding="utf-8"))
LINES = DOC["lines"]


def test_shape_is_what_the_renderer_and_player_expect():
    assert LINES and len({l["id"] for l in LINES}) == len(LINES)
    for l in LINES:
        assert re.fullmatch(r"d\d{2}", l["id"]), l["id"]
        assert l["who"] in ("host", "cjap")
        assert l["text"].strip() and len(l["text"]) <= 200
        assert isinstance(l.get("pause_after_s", 0.6), (int, float))
        assert 0 <= l.get("pause_after_s", 0.6) <= 5


def test_the_host_opens_and_frames_it_honestly():
    """The frame is the Host's whole reason to exist: it says this is a
    recreation BEFORE he speaks, so an identity question never has to break
    his persona later."""
    assert LINES[0]["who"] == "host"
    opening = " ".join(l["text"].lower() for l in LINES[:3])
    assert "recreat" in opening
    assert "not a recording" in opening or "published" in opening
    first_cjap = next(i for i, l in enumerate(LINES) if l["who"] == "cjap")
    assert first_cjap > 0, "he must not speak before the frame is set"


def test_the_host_never_speaks_for_him():
    """It asks, frames and invites. It never paraphrases his position."""
    for l in LINES:
        if l["who"] != "host":
            continue
        t = l["text"].lower()
        assert not re.search(r"\bi (believe|argued|wrote|held|ruled)\b", t), l["id"]
        assert "in my humble" not in t


def test_every_line_declares_where_its_phrasing_came_from():
    for l in LINES:
        assert l.get("source", "").strip(), f"{l['id']} has no source"


def test_no_line_asserts_a_specific_the_corpus_cannot_back():
    """No date, year, count or case title in a pre-written line. Anything
    factual has to come from the live composer, which now reads the corpus."""
    for l in LINES:
        t = l["text"]
        assert not re.search(r"\b(19|20)\d{2}\b", t), f"{l['id']} names a year"
        assert not re.search(r"\bv\.\s+[A-Z]", t), f"{l['id']} looks like a case title"
        digits = re.findall(r"\d+", t)
        assert not digits, f"{l['id']} carries figures: {digits}"


def test_it_alternates_enough_to_read_as_a_conversation():
    whos = [l["who"] for l in LINES]
    assert whos.count("host") >= 3 and whos.count("cjap") >= 3
    assert sum(1 for a, b in zip(whos, whos[1:]) if a != b) >= 5   # turn changes
    assert whos[-1] == "cjap", "he should have the last word — it invites the visitor"


def test_it_is_long_enough_to_stop_someone_and_short_enough_to_loop():
    words = sum(len(l["text"].split()) for l in LINES)
    assert 80 <= words <= 400, words        # ~45-120 s spoken


def test_the_manifest_matches_the_script_when_it_exists():
    """Rendered audio is gitignored; the manifest is not, so a machine with no
    API key can still tell what the audio should be."""
    mf = os.path.join(ROOT, "data", "prerendered", "duet", "manifest.json")
    if not os.path.exists(mf):
        return
    m = json.load(open(mf, encoding="utf-8"))
    assert [e["id"] for e in m["lines"]] == [l["id"] for l in LINES]
    assert all(e["text"] == l["text"] for e, l in zip(m["lines"], LINES))
    voices = {e["who"]: e["voice"] for e in m["lines"]}
    assert len(set(voices.values())) == 2, "the Host must not share his voice"
    assert m["total_seconds"] > 20
