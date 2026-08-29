"""Compile the canned Q&A into a readable text file for the team.

Reads data/entities/canned_answers.json and writes ~/canned_qa.txt
(override with --out). Re-run after editing the JSON. The dashboard
serves the file at GET /canned-qa, so from Windows:

    Invoke-WebRequest http://reachy-mini.local:8080/canned-qa -OutFile canned_qa.txt
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "entities" / "canned_answers.json"
OUT = Path(sys.argv[sys.argv.index("--out") + 1]) if "--out" in sys.argv \
    else Path.home() / "canned_qa.txt"

data = json.loads(SRC.read_text(encoding="utf-8"))
lines = [
    "CANNED QUESTIONS & ANSWERS — CJ Panganiban robot",
    f"Generated {time.strftime('%Y-%m-%d %H:%M')} from {SRC}",
    "",
    "One answer variant is picked at random each time a question matches.",
    "The 'out_of_topic' entry has no question patterns — it plays whenever a",
    "question falls outside his published record.",
    "=" * 70,
]
n_entries = n_answers = 0
for e in data["entries"]:
    n_entries += 1
    lines += ["", f"[{n_entries}] {e['id'].upper().replace('_', ' ')}"]
    for q in e.get("ask", []):
        lines.append(f"  Q: {q}")
    answers = e.get("answers") or [e.get("answer", "")]
    for i, a in enumerate(answers, 1):
        n_answers += 1
        lines.append(f"  A{i}: {a}")
    lines.append("-" * 70)
lines += ["", f"TOTAL: {n_entries} question groups, {n_answers} answer variants."]
OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"wrote {OUT} — {n_entries} entries, {n_answers} answers")
