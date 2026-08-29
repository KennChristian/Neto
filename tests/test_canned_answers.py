"""Standalone tests for the canned fast path (no pytest in the app venv):
    app/.venv/bin/python tests/test_canned_answers.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))
os.environ["CJ_CANNED_ENABLED"] = "1"

import answer_canned  # noqa: E402

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
    m = answer_canned.match(q)
    return m["id"] if m else None


# --- normalization ---
check("normalize punctuation", answer_canned.normalize("What's the Rule of Law?")
      == "whats the rule of law")

# event mode ON for the hit cases below — scripted event_* entries only
# voice-match while the flag file exists (toggled from the /event page)
EVENT_FLAG = os.path.join(os.path.dirname(answer_canned._DEFAULT_PATH),
                          "event_mode.on")
_had_event_flag = os.path.exists(EVENT_FLAG)
open(EVENT_FLAG, "w").close()

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
    ("Nice to meet you!", "greeting"),
    ("Sino ka po?", "who_are_you"),
    ("How are you today?", "how_are_you"),
    ("Kumusta po?", "how_are_you"),
    ("Where are you from?", "where_from"),
    ("How many children do you have?", "family_children"),
    ("Who is your wife?", "family_children"),
    ("Where did you study law?", "education"),
    ("What are the four Ins?", "four_ins"),
    ("What are the ACID problems?", "acid_problems"),
    ("Tell me about With Due Respect.", "column"),
    ("Can you speak Tagalog?", "speak_tagalog"),
    ("Tell me a joke!", "tell_joke"),
    ("What is the Supreme Court?", "supreme_court_what"),
    ("What was your most famous decision?", "famous_case"),
    ("Why did you become a lawyer?", "why_lawyer"),
    ("Tell me about your faith.", "faith"),
    ("Are you religious?", "faith"),
    ("Who made you?", "who_built_you"),
    ("What do you do now?", "what_do_now"),
    ("Are you retired?", "what_do_now"),
    ("What is your message to the Filipino people?", "message_filipinos"),
    ("What do you think about the West Philippine Sea?", "west_philippine_sea"),
    ("Tell me about the Arbitral Award.", "west_philippine_sea"),
    ("Can you sing?", "can_you_sing"),
    ("Did you top the bar exam?", "education"),
    # event-day scripted questions (2026-08-24, single verbatim answers)
    ("Good afternoon. How are you feeling today?", "event_feeling"),
    ("Hi CJAP, good afternoon! How are you feeling today?", "event_feeling"),
    ("How are you feeling today?", "event_feeling"),
    ("Are you ready to answer some questions today?", "event_ready"),
    ("Hi CJAP, are you ready to answer a few questions?", "event_ready"),
    ("What can you say to our donor, the State Properties Corporation?", "event_donor"),
    ("What can you say to the State Properties Corporation?", "event_donor"),
    ("Any message for our donors?", "event_donor"),
    ("We are about to end our program. What can you say to our guests today?", "event_closing"),
    ("What can you say to our guests today?", "event_closing"),
    # the generic entries must survive the event entries sitting above them
    ("How are you today?", "how_are_you"),
    ("Kumusta po?", "how_are_you"),
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
    "How old is the Supreme Court?",
    "What did the Supreme Court decide about the ICC?",
    "How are you going to fix the judiciary?",
    "Tell me about your family's political connections.",
    "Where did you study the death penalty issue?",
    "What can you say about the rule of law?",
    "What can you say to the Supreme Court about corruption?",
    "Are you ready to rule on the ICC case?",
]:
    check(f"miss: {q!r}", hits(q) is None)

# --- event mode gating: flag off -> event_* voice-inert, generics intact ---
os.unlink(EVENT_FLAG)
check("event off: scripted question falls through",
      hits("Good afternoon. How are you feeling today?") is None)
check("event off: donor question falls through",
      hits("What can you say to our donor, the State Properties Corporation?")
      is None)
check("event off: generic how_are_you unaffected",
      hits("How are you today?") == "how_are_you")
check("event off: get-by-id still works (button path)",
      isinstance(answer_canned.get("event_ready"), str))
open(EVENT_FLAG, "w").close()
check("event on: scripted question matches again",
      hits("Good afternoon. How are you feeling today?") == "event_feeling")
if not _had_event_flag:
    os.unlink(EVENT_FLAG)

# --- out_of_topic: selected by id (gate scope), never by transcript ---
ooc = answer_canned.get("out_of_topic")
check("get out_of_topic", isinstance(ooc, str) and len(ooc) > 40)
variants = {answer_canned.get("out_of_topic") for _ in range(30)}
check("out_of_topic rotates variants", len(variants) >= 2)
check("out_of_topic never pattern-matches",
      all(hits(q) != "out_of_topic" for q in
          ("out of topic", "what is your favorite basketball team",
           "tell me about quantum physics")))
check("get unknown id -> None", answer_canned.get("nope") is None)

# --- disabled flag ---
os.environ["CJ_CANNED_ENABLED"] = "0"
check("disabled -> None", hits("Who are you?") is None)
check("disabled -> get None", answer_canned.get("out_of_topic") is None)
os.environ["CJ_CANNED_ENABLED"] = "1"

# --- every entry's answers are non-empty strings ---
entries = answer_canned._load()
check("entries loaded", len(entries) >= 25)
check("all answers non-empty",
      all(isinstance(a, str) and a.strip() for e in entries for a in e["answers"]))
check("every entry has >=5 variants",   # event_* = verbatim scripts, 1 answer
      all(len(e["answers"]) >= 5 for e in entries
          if not e["id"].startswith("event_")))
variants2 = {answer_canned.match("Who are you?")["answer"] for _ in range(40)}
check("pattern entries rotate variants", len(variants2) >= 3)

print(f"\n{PASS}/{PASS + FAIL} passed")
sys.exit(1 if FAIL else 0)
