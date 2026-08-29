"""
PLAN-0008 Task 1 — Gate 2 (listening test for tts-1 pronunciation).

Generates one short WAV per OpenAI tts-1 voice (12 voices across the
two model tiers) saying the phrase "Hey CJ" at default speed. The
operator listens to all 12 and decides:

  * Does tts-1 pronounce "CJ" as "see-jay" (correct) or as "sip"
    (Piper-style mispronunciation)?
  * If even one voice mispronounces, we add phonetic-spelled phrase
    variants ("Hey see jay", "Hey C-J-P") to the full G4 generation
    set.

Cost guard: refuses to call the API if the estimated character total
multiplied by the tts-1 rate would push session spend above the
per-script cap. For G2 with 12 calls × ~7 chars × $0.015/1k chars
the expected cost is ~$0.001, well below any cap.

Run from the repo root:

    .\\app\\.venv-training\\Scripts\\Activate.ps1
    python app\\wake\\training\\g2_listen.py

After it finishes, the 12 .wav files land in:

    app/wake/training/g2_clips/

Listen to each one (play in Explorer / VLC / Media Player), then
report back with one of:

  * "all clean"             — every voice says "see jay" properly;
                              proceed to G3 with just ["Hey CJ",
                              "Hey CJP"] in the phrase list.
  * "some mispronounce"     — add phonetic variants; I'll regenerate
                              and we'll repeat G2 with the expanded
                              list before G3.
  * "voice X is unusable"   — drop that voice from G4's variation
                              matrix.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Force UTF-8 on stdout/stderr so the script's Unicode logging arrows
# don't crash the Windows cp1252 console. Without this, prints
# containing → / ✓ / etc. raise UnicodeEncodeError after the API call
# has already completed, which makes the script look like it failed
# when it actually succeeded.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# ── Locate and load the kiosk's existing .env so we reuse OPENAI_API_KEY ──
# The training venv lives at app/.venv-training/; the .env file lives at
# app/.env. We don't import the kiosk's voice_io because that would pull
# Streamlit into this CLI; instead we just read the env directly.
_THIS_FILE = Path(__file__).resolve()
_APP_DIR = _THIS_FILE.parents[2]   # .../app/wake/training/g2_listen.py → .../app
_DOTENV_PATH = _APP_DIR / ".env"

try:
    from dotenv import load_dotenv
    load_dotenv(_DOTENV_PATH, override=False)
except ImportError:
    pass  # if dotenv isn't there for some reason we'll fail loudly on the key check

if not os.environ.get("OPENAI_API_KEY"):
    print(
        f"ERROR: OPENAI_API_KEY not in environment. Expected to find it in:\n"
        f"  {_DOTENV_PATH}\n"
        f"This script reuses the same key the kiosk uses for runtime TTS.",
        file=sys.stderr,
    )
    sys.exit(1)

# ── Voices to test ────────────────────────────────────────────────────
# Per OpenAI's TTS docs: tts-1 voice set (6) + the newer gpt-4o-mini-tts
# voices (6). We test all 12 with the tts-1 model (the cheap one); some
# of the newer voices may require the gpt-4o-mini-tts model — we handle
# that fallback per voice.
TTS1_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
NEW_VOICES  = ("ash", "ballad", "coral", "sage", "verse", "spruce")
ALL_VOICES  = TTS1_VOICES + NEW_VOICES

PHRASE = "Hey CJ"
SPEED  = 1.0
OUT_DIR = _THIS_FILE.parent / "g2_clips"
OUT_DIR.mkdir(exist_ok=True, parents=True)

# ── Cost guard ────────────────────────────────────────────────────────
PRICE_PER_KCHAR_TTS_1 = 0.015     # tts-1 model
PRICE_PER_KCHAR_GPT4O_TTS = 0.060 # gpt-4o-mini-tts (~4× tts-1) — used as fallback
HARD_CAP_USD = 0.10               # script refuses to spend more than this
expected_chars = len(ALL_VOICES) * len(PHRASE)
# Pessimistic price assumption: assume ALL voices land on gpt-4o-mini-tts
worst_case_cost = expected_chars / 1000 * PRICE_PER_KCHAR_GPT4O_TTS
if worst_case_cost > HARD_CAP_USD:
    print(
        f"ABORT: worst-case cost estimate ${worst_case_cost:.4f} exceeds "
        f"hard cap ${HARD_CAP_USD:.2f}. Edit the script if intentional.",
        file=sys.stderr,
    )
    sys.exit(1)
print(
    f"Phrase:              '{PHRASE}'\n"
    f"Voices to test:      {len(ALL_VOICES)} ({', '.join(ALL_VOICES)})\n"
    f"Output directory:    {OUT_DIR.relative_to(_APP_DIR.parent)}\n"
    f"Worst-case cost:     ${worst_case_cost:.4f}  "
    f"(actual will be lower; tts-1 calls cost ${PRICE_PER_KCHAR_TTS_1:.3f}/1k chars)\n"
)

# ── Run ───────────────────────────────────────────────────────────────
from openai import OpenAI
client = OpenAI()

total_chars = 0
total_cost = 0.0
n_ok = 0
n_skip = 0
t_start = time.time()

for voice in ALL_VOICES:
    out_path = OUT_DIR / f"{voice}.wav"
    print(f"  [{voice:8s}]  ", end="", flush=True)
    # Try tts-1 first; fall back to gpt-4o-mini-tts if the voice isn't
    # supported on the older model.
    for model_name, price in (("tts-1", PRICE_PER_KCHAR_TTS_1),
                              ("gpt-4o-mini-tts", PRICE_PER_KCHAR_GPT4O_TTS)):
        try:
            with client.audio.speech.with_streaming_response.create(
                model=model_name,
                voice=voice,
                input=PHRASE,
                speed=SPEED,
                response_format="wav",
            ) as resp:
                resp.stream_to_file(str(out_path))
            cost = len(PHRASE) / 1000 * price
            total_chars += len(PHRASE)
            total_cost += cost
            n_ok += 1
            print(
                f"→ {model_name:16s} ${cost:.5f}  → {out_path.name}",
                flush=True,
            )
            break
        except Exception as e:
            err_str = str(e)[:140]
            # Only fall back on "voice not supported" — don't auto-fallback
            # on auth errors etc.
            if model_name == "tts-1" and "voice" in err_str.lower():
                continue
            print(f"FAILED on {model_name}: {err_str}")
            n_skip += 1
            break
    else:
        # Both models exhausted
        n_skip += 1

# ── Summary ───────────────────────────────────────────────────────────
print(
    f"\n"
    f"Wrote {n_ok}/{len(ALL_VOICES)} clips to {OUT_DIR}\n"
    f"Skipped: {n_skip}\n"
    f"Actual chars billed: {total_chars}\n"
    f"Actual session cost: ${total_cost:.5f}\n"
    f"Elapsed:             {time.time() - t_start:.1f} s\n"
)

print("Next step — listen to each .wav and report back with one of:")
print('  "all clean"            — every voice says "see jay"; proceed to G3.')
print('  "some mispronounce"    — phonetic variants needed; we regenerate.')
print('  "voice X is unusable"  — name the voice(s) to drop from G4.')
