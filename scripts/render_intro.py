#!/usr/bin/env python3
"""Render the Host's intro variants to audio, once, offline.

    app/.venv/bin/python scripts/render_intro.py [--force] [--dry-run]

Until 2026-09-13 there was ONE intro line and it was synthesised live, over the
network, every time a visitor arrived — so every visitor heard the identical
sentence, and a network stall delayed the one moment the installation gets to
explain itself. config/modes/direct.json has claimed "variants rotate; see
data/prerendered/intro/" since it was written; that directory never existed.

Each variant is rendered once PER MODE, because the closing instruction differs:
direct-kiosk tells the visitor to say the wake phrase, direct-event tells them
to use the handheld microphone. The text carries a {how_to_start} placeholder
and this script fills it from corpus/voice/intro_variants.json.

Everything is spoken by the HOST voice (ELEVEN_HOST_VOICE_ID) — a stock voice
deliberately not his, per corpus/voice/host_card.md.

Output: data/prerendered/intro/<id>_<mode>.wav plus manifest.json. The audio is
gitignored (media, re-renderable); the manifest is not, so a machine with no
key can still tell what the audio should be.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "corpus" / "voice" / "intro_variants.json"
OUT = ROOT / "data" / "prerendered" / "intro"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="re-render every variant")
    ap.add_argument("--dry-run", action="store_true", help="say what would be rendered")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "app"))
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / "app" / ".env")
    except ImportError:
        pass

    try:
        doc = json.loads(SRC.read_text(encoding="utf-8"))
    except OSError as e:
        print(f"cannot read {SRC}: {e}", file=sys.stderr)
        return 1
    variants = [v for v in doc.get("variants", []) if v.get("text")]
    how = doc.get("how_to_start") or {}
    if not variants:
        print("no variants in the file", file=sys.stderr)
        return 1
    if not how:
        print("no how_to_start mapping — nothing to substitute", file=sys.stderr)
        return 1

    voice = os.environ.get("ELEVEN_HOST_VOICE_ID", "").strip()
    if not voice:
        print("ELEVEN_HOST_VOICE_ID is not set — set it on /maintain's Guest tab", file=sys.stderr)
        return 2

    OUT.mkdir(parents=True, exist_ok=True)
    mf = OUT / "manifest.json"
    old = {}
    if mf.exists() and not args.force:
        try:
            old = {e["id"]: e for e in json.loads(mf.read_text(encoding="utf-8"))["clips"]}
        except (OSError, ValueError, KeyError):
            old = {}

    jobs = []
    for v in variants:
        for mode, tail in how.items():
            jobs.append({"id": f"{v['id']}_{mode}", "variant": v["id"], "mode": mode,
                         "text": v["text"].replace("{how_to_start}", tail).strip()})

    if args.dry_run:
        for j in jobs:
            prev = old.get(j["id"])
            why = "up to date" if prev and prev.get("text") == j["text"] else "would render"
            print(f"  {j['id']:14} {why}  {j['text'][:64]}")
        return 0

    import soundfile as sf
    import speech_engines as se
    from text_entities import process_tts_sentence
    from voice import config as vconfig

    vconfig.ELEVEN_VOICE_ID = voice
    clips, rendered = [], 0
    for j in jobs:
        dst = OUT / f"{j['id']}.wav"
        prev = old.get(j["id"])
        if prev and prev.get("text") == j["text"] and dst.exists() and prev.get("voice") == voice:
            clips.append(prev)
            print(f"  {j['id']:14} cached")
            continue
        text = process_tts_sentence(j["text"])
        t0 = time.time()
        try:
            wav = se.tts_elevenlabs_wav(text)
        except Exception as e:
            print(f"  {j['id']:14} FAILED ({type(e).__name__}: {e})", file=sys.stderr)
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
        print(f"  {j['id']:14} rendered {dur:5.2f}s in {time.time()-t0:.1f}s")
        clips.append({"id": j["id"], "variant": j["variant"], "mode": j["mode"],
                      "text": j["text"], "wav": dst.name, "seconds": dur, "voice": voice})

    mf.write_text(json.dumps({"version": 1, "rendered_at": time.time(),
                              "variants": len(variants), "clips": clips}, indent=2) + "\n",
                  encoding="utf-8")
    print(f"\n{rendered} rendered, {len(clips) - rendered} cached -> {OUT}")
    print(f"manifest: {mf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
