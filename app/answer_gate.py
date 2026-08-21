"""P0 answer gate — deterministic keyword recheck of composed answers ($0, no LLM).

Verifies the composed answer against hand-curated expected-data rules BEFORE
the robot speaks (pre-TTS). Complements the LLM fidelity checker: this gate is
zero-cost and deterministic, so it catches the concrete slips a sampled judge
can miss — a wrong year, a missing case name, AI self-description — and can
never hallucinate a verdict itself.

Rules file: config.ANSWER_GATE_RULES_PATH (data/entities/answer_gate_rules.json),
mtime hot-reloaded like entity_overrides.json — edits land without a restart.

Pattern convention (everywhere in the rules file):
  * plain string      -> case-insensitive substring match
  * "re:<pattern>"    -> regex, re.IGNORECASE

Rule semantics: a rule APPLIES to a turn when any `trigger.question_any`
pattern matches the question, OR a routed topic id is in `trigger.topics_any`.
An applied rule TRIPS when some `expect_groups` group has no alternate present
in the answer (kind=missing_expected), or a `forbid` pattern matches the
answer (kind=forbidden). `global_forbid` patterns are checked against every
answer regardless of triggers.

Fail-open: an unreadable/invalid rules file disables the gate for that call
(ok=True with a note) — the composer and fidelity checker remain the primary
safety surface. This module never raises into the caller.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config


# ---------------------------------------------------------------------------
# Pattern compilation ("re:" prefix = regex, else casefolded substring)
# ---------------------------------------------------------------------------
def _compile(pat: str):
    if pat.startswith("re:"):
        return re.compile(pat[3:], re.IGNORECASE)
    return pat.casefold()


def _matches(compiled, text_folded: str, text_raw: str) -> bool:
    if isinstance(compiled, str):
        return compiled in text_folded
    return compiled.search(text_raw) is not None


class GateRules:
    """Compiled form of the rules file. Bad individual patterns are dropped
    (logged into self.pattern_errors) rather than failing the whole file."""

    def __init__(self, doc: dict):
        self.pattern_errors: list[str] = []

        def _plist(pats) -> list:
            out = []
            for p in pats or []:
                try:
                    out.append((p, _compile(str(p))))
                except re.error as e:
                    self.pattern_errors.append(f"{p!r}: {e}")
            return out

        self.global_forbid = [
            {"id": str(gf.get("id", "global")), "patterns": _plist(gf.get("patterns"))}
            for gf in doc.get("global_forbid", [])
        ]
        self.rules = []
        for r in doc.get("rules", []):
            trig = r.get("trigger", {}) or {}
            self.rules.append({
                "id": str(r.get("id", "?")),
                "question_any": _plist(trig.get("question_any")),
                "topics_any": set(trig.get("topics_any") or []),
                "expect_groups": [_plist(g) for g in r.get("expect_groups", [])],
                "forbid": _plist(r.get("forbid")),
            })


# ---------------------------------------------------------------------------
# Loading (resident; mtime hot-reload; fail-open)
# ---------------------------------------------------------------------------
_STATE: dict = {"rules": None, "mtime": None, "error": None}


def load(force: bool = False) -> GateRules | None:
    """Resident rules, reloaded when the file's mtime changes.
    Returns None when the file is missing/invalid (fail-open)."""
    path = config.ANSWER_GATE_RULES_PATH
    try:
        mt = path.stat().st_mtime_ns
    except OSError as e:
        _STATE.update(rules=None, mtime=None, error=f"rules file unreadable: {e}")
        return None
    if force or _STATE["rules"] is None or mt != _STATE["mtime"]:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            _STATE.update(rules=GateRules(doc), mtime=mt, error=None)
        except (json.JSONDecodeError, OSError, TypeError, AttributeError) as e:
            _STATE.update(rules=None, mtime=mt, error=f"{type(e).__name__}: {e}")
            return None
    return _STATE["rules"]


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------
def check_answer(question: str, answer: str,
                 topic_ids: list | None = None,
                 audit: bool = True,
                 forbid_only: bool = False) -> dict:
    """Deterministic recheck of a composed answer. Pure string matching,
    never raises. Returns:
      {ok, applied: [rule ids], tripped: [{rule, kind, detail}],
       note, elapsed_ms}
    kind is "missing_expected" (an expect_groups group had no alternate in
    the answer; detail lists the alternates) or "forbidden" (a forbid /
    global_forbid pattern matched; detail is the pattern).

    forbid_only=True skips the expect_groups checks — for screening a
    SINGLE SENTENCE mid-stream, where expected facts may legitimately
    live in a later sentence but a forbidden phrase is wrong anywhere."""
    t0 = time.perf_counter()
    result = {"ok": True, "applied": [], "tripped": [], "note": "", "elapsed_ms": 0.0}
    try:
        rules = load()
        if rules is None:
            result["note"] = f"gate fail-open: {_STATE['error']}"
            return result

        q_raw, a_raw = str(question), str(answer)
        q_fold, a_fold = q_raw.casefold(), a_raw.casefold()
        topics = set(topic_ids or [])

        for gf in rules.global_forbid:
            for raw, comp in gf["patterns"]:
                if _matches(comp, a_fold, a_raw):
                    result["tripped"].append(
                        {"rule": gf["id"], "kind": "forbidden", "detail": raw})

        for r in rules.rules:
            applies = any(_matches(c, q_fold, q_raw) for _, c in r["question_any"]) \
                or bool(topics & r["topics_any"])
            if not applies:
                continue
            result["applied"].append(r["id"])
            for group in ([] if forbid_only else r["expect_groups"]):
                if group and not any(_matches(c, a_fold, a_raw) for _, c in group):
                    result["tripped"].append(
                        {"rule": r["id"], "kind": "missing_expected",
                         "detail": " / ".join(raw for raw, _ in group)})
            for raw, comp in r["forbid"]:
                if _matches(comp, a_fold, a_raw):
                    result["tripped"].append(
                        {"rule": r["id"], "kind": "forbidden", "detail": raw})

        result["ok"] = not result["tripped"]
    except Exception as e:  # absolute backstop — never raise into the pipeline
        result.update(ok=True, note=f"gate fail-open: {type(e).__name__}: {e}")
    result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 3)
    if audit and result["tripped"]:
        _audit(question, answer, result, topic_ids)
    return result


def correction_hint(result: dict) -> str:
    """Composer-facing recompose hint built from a tripped gate result.
    Appended to the user message (never the system prompt) so the cached
    prefix stays valid — same pattern as the fidelity_correction hint."""
    lines = []
    for t in result["tripped"]:
        if t["kind"] == "missing_expected":
            lines.append(f"- The answer MUST state this fact (any of): {t['detail']}")
        else:
            lines.append(f"- The answer must NOT contain: {t['detail']}")
    return ("<answer_correction>\n"
            "A prior draft failed a factual recheck against the documented "
            "record. Recompose, staying fully in voice, and fix the following:\n"
            + "\n".join(lines) + "\n</answer_correction>")


# ---------------------------------------------------------------------------
# Audit trail (JSONL, append-only; empty path disables)
# ---------------------------------------------------------------------------
def _audit(question: str, answer: str, result: dict, topic_ids) -> None:
    path = config.ANSWER_GATE_LOG_PATH
    if not str(path):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.time(), "question": question, "answer": answer,
               "topic_ids": list(topic_ids or []),
               "applied": result["applied"], "tripped": result["tripped"]}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass
