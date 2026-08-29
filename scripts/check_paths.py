"""
Diagnose every file path the dashboard touches at startup.

Run this with whichever Python interpreter your venv uses — same one
you'd use to launch Streamlit:

    .\.venv\Scripts\python.exe scripts\check_paths.py
    D:\some\where\python.exe scripts\check_paths.py

Prints OK/MISSING for each path; exits 1 if any required file is
missing.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"


def check(label: str, path: Path, required: bool = True) -> bool:
    exists = path.exists()
    mark = "✓ OK    " if exists else ("✗ MISS  " if required else "○ skip  ")
    note = "" if required else " (optional)"
    print(f"  {mark} {label}: {path}{note}")
    return exists or not required


def main() -> int:
    print(f"PROJECT_ROOT = {PROJECT_ROOT}")
    print(f"APP_DIR      = {APP_DIR}")
    print(f"CWD          = {Path.cwd()}")
    print(f"Python       = {sys.executable}")
    print()

    ok = True

    print("== Required files ==")
    ok &= check("dashboard.py",   APP_DIR / "dashboard.py")
    ok &= check("cj_chat.py",     APP_DIR / "cj_chat.py")
    ok &= check("topic_map.json", PROJECT_ROOT / "corpus" / "voice" / "topic_map.json")
    ok &= check("voice_card.md",  PROJECT_ROOT / "corpus" / "voice" / "voice_card.md")
    print()

    print("== Router prompt (one of these must exist) ==")
    new = PROJECT_ROOT / "corpus" / "voice" / "router_prompt.md"
    legacy = APP_DIR / "artifacts" / "router_prompt.md"
    found_router = check("corpus/voice/router_prompt.md", new, required=False) or check(
        "app/artifacts/router_prompt.md (legacy)", legacy, required=False
    )
    if not found_router:
        ok = False
        print("    ✗ NEITHER router prompt found — runtime will fail on first turn.")
    print()

    print("== Per-doc corpus (sample) ==")
    corp_columns = PROJECT_ROOT / "corpus" / "columns"
    corp_speeches = PROJECT_ROOT / "corpus" / "speeches"
    if corp_columns.exists():
        n_cols = len(list(corp_columns.glob("**/*.json")))
        n_md = len(list(corp_columns.glob("**/*.md")))
        print(f"  ✓ OK     corpus/columns/ — {n_cols} .json, {n_md} .md")
    else:
        ok = False
        print(f"  ✗ MISS   corpus/columns/ not found at {corp_columns}")
    if corp_speeches.exists():
        n_sp = len(list(corp_speeches.glob("**/*.json")))
        print(f"  ✓ OK     corpus/speeches/ — {n_sp} .json")
    else:
        ok = False
        print(f"  ✗ MISS   corpus/speeches/ not found at {corp_speeches}")
    print()

    print("== Environment ==")
    dotenv = APP_DIR / ".env"
    check("app/.env (read by python-dotenv on cj_chat import)", dotenv, required=False)
    # Try loading .env without touching the rest of cj_chat
    try:
        from dotenv import load_dotenv  # type: ignore[import-not-found]
        load_dotenv(dotenv, override=True)
    except ImportError:
        print("    note: python-dotenv not installed — .env won't auto-load")
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key:
        print(f"  ✓ OK     ANTHROPIC_API_KEY is set (length={len(key)})")
    else:
        ok = False
        print("  ✗ MISS   ANTHROPIC_API_KEY is not set "
              "(via shell env or app/.env)")
    print()

    print("== Optional: TTS (Piper) ==")
    piper_bin = os.environ.get("PIPER_BIN", "piper")
    piper_voice = os.environ.get("PIPER_VOICE", "./voices/en_US-ryan-high.onnx")
    # PIPER_BIN may be on PATH; if relative or absolute, check it.
    if any(sep in piper_bin for sep in ("\\", "/")) or Path(piper_bin).is_absolute():
        check(f"PIPER_BIN = {piper_bin}", Path(piper_bin), required=False)
    else:
        print(f"  ○ note   PIPER_BIN = '{piper_bin}' — relies on PATH lookup")
    # PIPER_VOICE default './voices/...' is relative to cwd; resolve from
    # repo root if it isn't absolute.
    pv_path = Path(piper_voice)
    if not pv_path.is_absolute():
        pv_candidates = [Path.cwd() / piper_voice, APP_DIR / piper_voice, PROJECT_ROOT / piper_voice]
        pv_found = next((p for p in pv_candidates if p.exists()), None)
        if pv_found:
            print(f"  ✓ OK     PIPER_VOICE resolved → {pv_found}")
        else:
            print(f"  ✗ MISS   PIPER_VOICE = '{piper_voice}' not found from any of:")
            for p in pv_candidates:
                print(f"             - {p}")
            print("           (TTS will fail; router + composer still work)")
    else:
        check(f"PIPER_VOICE = {piper_voice}", pv_path, required=False)
    print()

    print("== Optional: faster-whisper cache ==")
    hf = os.environ.get("HF_HOME") or os.environ.get("HUGGINGFACE_HUB_CACHE")
    if hf:
        print(f"  ✓ OK     HF_HOME / HUGGINGFACE_HUB_CACHE = {hf}")
    else:
        default = Path.home() / ".cache" / "huggingface"
        print(f"  ○ note   HF_HOME unset — model will download to {default} on first mic use")
    print()

    print("== Python modules ==")
    for mod in ("anthropic", "streamlit", "faster_whisper", "scipy", "sounddevice"):
        try:
            __import__(mod)
            print(f"  ✓ OK     {mod}")
        except ImportError as e:
            ok = False
            print(f"  ✗ MISS   {mod} — {e}")
    print()

    if ok:
        print("All required paths and modules look good. You should be able to run:")
        print()
        print(f"  {sys.executable} -m streamlit run {APP_DIR / 'dashboard.py'}")
        return 0
    print("Some required paths or modules are missing. Resolve and re-run.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
