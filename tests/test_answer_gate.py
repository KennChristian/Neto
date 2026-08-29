"""P0 answer-gate tests — deterministic pre-TTS recheck ($0, offline).

Pytest-compatible; also runnable standalone:  python tests/test_answer_gate.py
Uses a small fixture rules file for mechanics plus the real
data/entities/answer_gate_rules.json for integration checks.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))

import config  # noqa: E402
import answer_gate as ag  # noqa: E402

# ---------------------------------------------------------------------------
# fixture rules
# ---------------------------------------------------------------------------

FIXTURE_DOC = {
    "schema_version": 1,
    "global_forbid": [
        {"id": "no-ai", "patterns": ["re:\\bI am (an AI|a robot)\\b",
                                     "re:\\bas an AI\\b"]},
    ],
    "rules": [
        {"id": "cj-year",
         "trigger": {"question_any": ["re:when.*chief justice"], "topics_any": []},
         "expect_groups": [["2005"]], "forbid": []},
        {"id": "philosophy",
         "trigger": {"question_any": ["twin beacons"], "topics_any": []},
         "expect_groups": [["liberty"], ["prosperity"]], "forbid": []},
        {"id": "topic-triggered",
         "trigger": {"question_any": [], "topics_any": ["faith_journey"]},
         "expect_groups": [], "forbid": ["astrology"]},
    ],
}

_TMP = Path(tempfile.mkdtemp(prefix="cj_answer_gate_test_"))
FIXTURE_RULES = _TMP / "answer_gate_rules.json"
FIXTURE_LOG = _TMP / "answer_gate.jsonl"
FIXTURE_RULES.write_text(json.dumps(FIXTURE_DOC), encoding="utf-8")

_SAVED = {}


def _use_fixture():
    _SAVED.setdefault("rules", config.ANSWER_GATE_RULES_PATH)
    _SAVED.setdefault("log", config.ANSWER_GATE_LOG_PATH)
    config.ANSWER_GATE_RULES_PATH = FIXTURE_RULES
    config.ANSWER_GATE_LOG_PATH = FIXTURE_LOG
    ag.load(force=True)


def _use_real():
    config.ANSWER_GATE_RULES_PATH = _SAVED.get("rules", config.ANSWER_GATE_RULES_PATH)
    config.ANSWER_GATE_LOG_PATH = _SAVED.get("log", config.ANSWER_GATE_LOG_PATH)
    ag.load(force=True)


# ---------------------------------------------------------------------------
# mechanics (fixture rules)
# ---------------------------------------------------------------------------

def test_pass_when_expected_present():
    _use_fixture()
    r = ag.check_answer("When did you become Chief Justice?",
                        "I was named Chief Justice in December 2005.", audit=False)
    assert r["ok"] and r["applied"] == ["cj-year"] and not r["tripped"]


def test_trip_on_missing_expected():
    _use_fixture()
    r = ag.check_answer("When did you become Chief Justice?",
                        "I was named Chief Justice by the President.", audit=False)
    assert not r["ok"]
    assert r["tripped"][0]["rule"] == "cj-year"
    assert r["tripped"][0]["kind"] == "missing_expected"
    assert "2005" in r["tripped"][0]["detail"]


def test_all_groups_required():
    _use_fixture()
    r = ag.check_answer("Tell me about the twin beacons.",
                        "Liberty is one of my touchstones.", audit=False)
    assert not r["ok"] and r["tripped"][0]["detail"] == "prosperity"
    r2 = ag.check_answer("Tell me about the twin beacons.",
                         "Liberty and prosperity must sail together.", audit=False)
    assert r2["ok"]


def test_substring_trigger_and_case_insensitive():
    _use_fixture()
    r = ag.check_answer("What are the TWIN BEACONS about?",
                        "LIBERTY and PROSPERITY.", audit=False)
    assert r["ok"] and r["applied"] == ["philosophy"]


def test_topic_trigger_and_rule_forbid():
    _use_fixture()
    r = ag.check_answer("Tell me about your faith.",
                        "I consulted astrology charts daily.",
                        topic_ids=["faith_journey"], audit=False)
    assert not r["ok"] and r["tripped"][0]["kind"] == "forbidden"
    r2 = ag.check_answer("Tell me about your faith.",
                         "My faith journey began in Sampaloc.",
                         topic_ids=["faith_journey"], audit=False)
    assert r2["ok"] and r2["applied"] == ["topic-triggered"]


def test_global_forbid_applies_without_trigger():
    _use_fixture()
    r = ag.check_answer("What is the rule of law?",
                        "As an AI, I cannot say.", audit=False)
    assert not r["ok"] and r["tripped"][0]["rule"] == "no-ai"


def test_global_forbid_word_boundary():
    _use_fixture()
    # "as an aide" must NOT match the "as an AI" regex
    r = ag.check_answer("Tell me about your work.",
                        "I served as an aide to the committee.", audit=False)
    assert r["ok"]


def test_no_rules_applied_passes():
    _use_fixture()
    r = ag.check_answer("What is due process?",
                        "Due process is the heart of fairness.", audit=False)
    assert r["ok"] and not r["applied"]


def test_fail_open_on_missing_file():
    _use_fixture()
    config.ANSWER_GATE_RULES_PATH = _TMP / "does_not_exist.json"
    r = ag.check_answer("When did you become Chief Justice?", "No year here.",
                        audit=False)
    assert r["ok"] and "fail-open" in r["note"]
    config.ANSWER_GATE_RULES_PATH = FIXTURE_RULES
    ag.load(force=True)


def test_fail_open_on_invalid_json():
    _use_fixture()
    bad = _TMP / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    config.ANSWER_GATE_RULES_PATH = bad
    r = ag.check_answer("q", "a", audit=False)
    assert r["ok"] and "fail-open" in r["note"]
    config.ANSWER_GATE_RULES_PATH = FIXTURE_RULES
    ag.load(force=True)


def test_hot_reload_on_mtime_change():
    _use_fixture()
    assert not ag.check_answer("when chief justice", "in 2005", audit=False)["tripped"]
    doc2 = dict(FIXTURE_DOC)
    doc2 = json.loads(json.dumps(FIXTURE_DOC))
    doc2["rules"][0]["expect_groups"] = [["1999"]]
    time.sleep(0.01)  # ensure a distinct mtime_ns
    FIXTURE_RULES.write_text(json.dumps(doc2), encoding="utf-8")
    r = ag.check_answer("when did you become chief justice", "in 2005", audit=False)
    assert not r["ok"] and "1999" in r["tripped"][0]["detail"]
    FIXTURE_RULES.write_text(json.dumps(FIXTURE_DOC), encoding="utf-8")
    ag.load(force=True)


def test_audit_log_written_on_trip():
    _use_fixture()
    if FIXTURE_LOG.exists():
        FIXTURE_LOG.unlink()
    ag.check_answer("when did you become chief justice", "no year", audit=True)
    rec = json.loads(FIXTURE_LOG.read_text(encoding="utf-8").splitlines()[-1])
    assert rec["tripped"][0]["rule"] == "cj-year"


def test_correction_hint_contents():
    _use_fixture()
    r = ag.check_answer("when chief justice?", "As an AI, no year.", audit=False)
    hint = ag.correction_hint(r)
    assert "2005" in hint and "must NOT contain" in hint
    assert hint.startswith("<answer_correction>")


def test_forbid_only_skips_expects():
    _use_fixture()
    # mid-stream sentence screening: expected facts may come in a LATER
    # sentence, so forbid_only must not trip missing_expected...
    r = ag.check_answer("When did you become Chief Justice?",
                        "Ah, a fine question about my elevation.",
                        forbid_only=True, audit=False)
    assert r["ok"]
    # ...but forbidden phrases still trip
    r2 = ag.check_answer("When did you become Chief Justice?",
                         "As an AI, I recall it well.",
                         forbid_only=True, audit=False)
    assert not r2["ok"] and r2["tripped"][0]["kind"] == "forbidden"


# ---------------------------------------------------------------------------
# integration (real rules file)
# ---------------------------------------------------------------------------

def test_real_rules_load_and_core_facts():
    _use_real()
    rules = ag.load(force=True)
    assert rules is not None and not rules.pattern_errors

    good = ag.check_answer(
        "Who appointed you Chief Justice?",
        "President Gloria Macapagal-Arroyo named me the 21st Chief Justice.",
        audit=False)
    assert good["ok"] and "cj-appointer" in good["applied"]

    bad = ag.check_answer(
        "When did you become Chief Justice?",
        "I became Chief Justice in 2003.", audit=False)
    assert not bad["ok"]

    # third-person AI discussion must not trip the identity forbid
    ai_talk = ag.check_answer(
        "What do you think of artificial intelligence?",
        "Artificial intelligence will test the rule of law in new ways.",
        audit=False)
    assert ai_talk["ok"]

    persona_break = ag.check_answer(
        "Are you a robot?",
        "I am a robot rendering of the Chief Justice.", audit=False)
    assert not persona_break["ok"]


if __name__ == "__main__":
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)
