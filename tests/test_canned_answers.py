"""Standalone tests for the canned fast path (no pytest in the app venv):
    app/.venv/bin/python tests/test_canned_answers.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ["CJ_CANNED_ENABLED"] = "1"

import canned_answers  # noqa: E402

PASS = FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}")


def hits(q):
    m = canned_answers.match(q)
    return m["id"] if m else None


# --- normalization ---
check("normalize punctuation", canned_answers.normalize("What's the Rule of Law?")
      == "whats the rule of law")

# --- common questions HIT (incl. ASR-ish variants) ---
for q, want in [
    ("Who are you?", "who_are_you"),
    ("Can you tell me about yourself?", "who_are_you"),
    ("What's your name?", "who_are_you"),
    ("Are you a robot?", "are_you_robot"),
    ("are you an AI", "are_you_robot"),
    ("How old are you?", "how_old"),
    ("When were you born?", "how_old"),
    ("What is the rule of law?", "rule_of_law"),
    ("what does the rule of law mean to you", "rule_of_law"),
    ("What are the twin beacons?", "twin_beacons"),
    ("What are the twin beacons of liberty and prosperity?", "twin_beacons"),
    ("When were you Chief Justice?", "chief_justice_when"),
    ("What is the Foundation for Liberty and Prosperity?", "flp"),
    ("What advice do you have for young lawyers?", "advice_young"),
    ("Thank you very much!", "thanks_goodbye"),
    ("Salamat po.", "thanks_goodbye"),
    ("Hello!", "greeting"),
    ("Good morning po!", "greeting"),
]:
    check(f"hit: {q!r} -> {want}", hits(q) == want)

# --- real questions must NOT match (composer's job) ---
for q in [
    "What did the Supreme Court decide in Lambino versus Comelec?",
    "Why does the rule of law matter for ordinary Filipinos?",
    "What do you think about the ICC and Duterte?",
    "Tell me about the death penalty and Echegaray.",
    "Who are you voting for?",
    "How old is the Supreme Court?",
    "Thank you notes were sent to the donors, what do you think?",
    "What is the rule of law situation in the Philippines today?",
]:
    check(f"miss: {q!r}", hits(q) is None)

# --- out_of_topic: selected by id (gate scope), never by transcript ---
ooc = canned_answers.get("out_of_topic")
check("get out_of_topic", isinstance(ooc, str) and len(ooc) > 40)
variants = {canned_answers.get("out_of_topic") for _ in range(30)}
check("out_of_topic rotates variants", len(variants) >= 2)
check("out_of_topic never pattern-matches",
      all(hits(q) != "out_of_topic" for q in
          ("out of topic", "what is your favorite basketball team",
           "tell me about quantum physics")))
check("get unknown id -> None", canned_answers.get("nope") is None)

# --- disabled flag ---
os.environ["CJ_CANNED_ENABLED"] = "0"
check("disabled -> None", hits("Who are you?") is None)
check("disabled -> get None", canned_answers.get("out_of_topic") is None)
os.environ["CJ_CANNED_ENABLED"] = "1"

# --- every entry's answers are non-empty strings ---
entries = canned_answers._load()
check("entries loaded", len(entries) >= 10)
check("all answers non-empty",
      all(isinstance(a, str) and a.strip() for e in entries for a in e["answers"]))

print(f"\n{PASS}/{PASS + FAIL} passed")
sys.exit(1 if FAIL else 0)
