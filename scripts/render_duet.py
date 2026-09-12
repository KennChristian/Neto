#!/usr/bin/env python3
"""Render the duet exchanges to audio, once, offline.

    app/.venv/bin/python scripts/render_duet.py [--force] [--dry-run] [--play]

DUET mode trades PRE-RENDERED lines between the two robots: no microphone
opens and nothing is composed live, so the exchange runs with no internet —
which is the point, since it is both the attract loop for an empty room and
the fallback when the venue network dies. That only works if the audio is on
disk beforehand. This puts it there.

Each line is rendered in the voice of whoever says it:

  host  ->  ELEVEN_HOST_VOICE_ID, a stock voice chosen to be unmistakably
            not his (corpus/voice/host_card.md)
  cjap  ->  ELEVEN_VOICE_ID, the cloned voice, with the name pin applied, so
            "Panganiban" here sounds identical to a live answer

Output: data/prerendered/duet/<id>.wav plus manifest.json, which records the
text, speaker, duration and the voice each line was rendered with. The audio
is gitignored (media, and re-renderable); the manifest is not, so a machine
with no key can still tell what the audio should be.

Re-running renders only what is missing or whose text has changed. --force
re-renders everything (use after a voice change).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "corpus" / "voice" / "duet_script.json"
OUT = ROOT / "data" / "prerendered" / "duet"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-render every line")
    ap.add_argument("--dry-run", action="store_true", help="say what would be rendered")
    ap.add_argument("--play", action="store_true", help="play the whole duet when done")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "app" / ".env")
    except ImportError:
        pass

    try:
        doc = json.loads(SCRIPT.read_text(encoding="utf-8"))
    except OSError as e:
        print(f"cannot read {SCRIPT}: {e}", file=sys.stderr)
        return 1
    lines = [ln for ln in doc.get("lines", []) if ln.get("text") and ln.get("who") in ("host", "cjap")]
    if not lines:
        print("no lines in the script", file=sys.stderr)
        return 1

    voices = {"cjap": os.environ.get("ELEVEN_VOICE_ID", "").strip(),
              "host": os.environ.get("ELEVEN_HOST_VOICE_ID", "").strip()}
    missing = [w for w in ("host", "cjap") if not voices[w] and any(ln["who"] == w for ln in lines)]
    if missing:
        print(f"no voice id for {', '.join(missing)} — set it on /maintain's Guest tab "
              f"(ELEVEN_HOST_VOICE_ID / ELEVEN_VOICE_ID in app/.env)", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    old = {}
    mf = OUT / "manifest.json"
    if mf.exists() and not args.force:
        try:
            old = {e["id"]: e for e in json.loads(mf.read_text(encoding="utf-8"))["lines"]}
        except (OSError, ValueError, KeyError):
            old = {}

    if args.dry_run:
        for ln in lines:
            prev = old.get(ln["id"])
            why = "up to date" if prev and prev.get("text") == ln["text"] else "would render"
            print(f"  {ln['id']}  {ln['who']:4}  {why}  {ln['text'][:60]}")
        return 0

    import soundfile as sf
    import speech_engines as se
    from text_entities import process_tts_sentence
    from voice import config as vconfig

    entries, rendered = [], 0
    for ln in lines:
        dst = OUT / f"{ln['id']}.wav"
        prev = old.get(ln["id"])
        if prev and prev.get("text") == ln["text"] and dst.exists() and prev.get("voice") == voices[ln["who"]]:
            entries.append(prev)
            print(f"  {ln['id']}  {ln['who']:4}  cached")
            continue
        # the voice package reads the id at synthesis time, so swap it per line
        vconfig.ELEVEN_VOICE_ID = voices[ln["who"]]
        text = process_tts_sentence(ln["text"])
        kw = {}
        if ln["who"] == "cjap" and se.pinned_name_in(text):
            kw = {"voice_settings": se.name_pin_voice_settings(), "seed": se.name_pin_seed()}
        t0 = time.time()
        try:
            wav = se.tts_elevenlabs_wav(text, **kw)
        except Exception as e:
            print(f"  {ln['id']}  FAILED ({type(e).__name__}: {e})", file=sys.stderr)
            return 3
        pcm, sr = sf.read(wav, dtype="float32")
        sf.write(str(dst), pcm, sr, subtype="PCM_16")
        for p in (wav, wav + ".align.json"):
            try:
                os.unlink(p)
            except OSError:
                pass
        dur = round(len(pcm) / float(sr), 2)
        rendered += 1
        print(f"  {ln['id']}  {ln['who']:4}  rendered {dur:5.2f}s in {time.time()-t0:.1f}s")
        entries.append({"id": ln["id"], "who": ln["who"], "text": ln["text"],
                        "wav": dst.name, "seconds": dur, "voice": voices[ln["who"]],
                        "pause_after_s": ln.get("pause_after_s", 0.6),
                        "source": ln.get("source", "")})

    total = sum(e["seconds"] + e.get("pause_after_s", 0) for e in entries)
    mf.write_text(json.dumps({"version": doc.get("version", 1), "rendered_at": time.time(),
                              "total_seconds": round(total, 1), "lines": entries},
                             ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(entries)} lines ({rendered} new) — {total:.0f}s of duet in {OUT}")

    if args.play:
        print("playing…")
        for e in entries:
            subprocess.run(["aplay", "-q", str(OUT / e["wav"])], stderr=subprocess.DEVNULL)
            time.sleep(e.get("pause_after_s", 0.6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
