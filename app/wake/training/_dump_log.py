"""Decode the g5 training log (PowerShell *> default is UTF-16 LE on
Win 5.1) and dump the tail so we can see why training died."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

p = Path(__file__).resolve().parent / "g5_train_v2.log"
text = None
for enc in ("utf-16", "utf-16-le", "utf-8", "cp1252"):
    try:
        text = p.read_text(encoding=enc)
        print(f"--- decoded as {enc!r}, {len(text)} chars ---")
        break
    except UnicodeError as e:
        print(f"  {enc} failed: {e}")

if text is None:
    print("FAIL: no encoding worked.")
    sys.exit(1)

lines = text.splitlines()
print(f"--- total lines: {len(lines)} ---\n")
print("=" * 70)
print("TAIL — last 80 lines")
print("=" * 70)
for line in lines[-80:]:
    print(line)
