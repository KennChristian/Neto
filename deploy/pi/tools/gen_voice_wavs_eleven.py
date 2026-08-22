"""Regenerate ~/fillers (40 clips) and ~/fillers_bail (4 notices) in the
CLONED ElevenLabs voice (2026-08-19 switch), replacing the gpt-4o-mini-tts
accent clips so pre-recorded audio matches the cloned-voice answers.

Uses the develop checkout's voice/ package (synth + the same EQ chain the
live answers get), so the clips sound identical to streamed speech. Bail
texts come from scratchpad/bail_texts.json (whisper-recovered, with
enroll_prompt's true text hardcoded — whisper garbles that one).

Run in the DEVELOP venv (the voice package's credentials live there):
  ~/Supervaise-Reachy-Mini-Project-develop/.venv/bin/python ~/gen_voice_wavs_eleven.py

Stages into *.new dirs, backs up the old dirs, then swaps — safe while the
service runs (aplay opens files per-utterance).
"""
import json
import os
import shutil
import sys
import time

DEV = os.path.expanduser("~/Supervaise-Reachy-Mini-Project-develop")
sys.path.insert(0, DEV)

import soundfile as sf  # noqa: E402

from voice import audio as v_audio  # noqa: E402
from voice import cache as v_cache  # noqa: E402
from voice.speak import SynthError, synthesize  # noqa: E402

FILLER_TEXTS = [
    "Ah — a fine question. Allow me a moment to consult what my record holds.",
    "Yes; let me give that the consideration it deserves — a moment, if you please.",
    "A thoughtful question. Permit me to gather my recollections properly.",
    "Let me reflect on that for a moment; a proper answer deserves a proper pause.",
    "Hmm — allow me to draw the threads together before I speak.",
    "Well now, that is worth answering with care. Bear with me a moment.",
    "I should like to answer this properly, so let me consult my record first.",
    "A moment, if you would — I prefer to weigh my words before I offer them.",
    "Let me think this through as it deserves; I shall be with you shortly.",
    "Ah — give me just a moment to marshal my thoughts on this.",
    "Ah, yes. Let me look back through my years on the bench for this one.",
    "One moment po — I want to give you an answer worthy of the question.",
    "Hmm. There is something in my record that speaks to this; let me recall it properly.",
    "Patience, my friend — good judgment is never rushed.",
    "Let me search my memory; fifty years of law leaves many pages to turn.",
    "A moment po. Even on the Court, I never answered without reflection.",
    "That touches something I have written about; allow me to find the thread.",
    "Give me a breath to set my thoughts in order.",
    "Ah — I have opinions on this, in both senses of the word. One moment.",
    "Let me weigh this as I would have weighed a case — carefully.",
    "Hmm, a question after my own heart. Bear with me briefly.",
    "I am gathering my recollections — the archive of an old jurist is vast.",
    "Steady now — the right words are worth a short wait.",
    "Yes, I recall something on this. Let me bring it into focus.",
    "Allow an old Chief Justice a moment of deliberation.",
    "The law taught me never to speak before thinking. A moment, please.",
    "Let me consult the record of my years — it rarely fails me.",
    "Ah, this deserves more than a quick reply. Give me a moment po.",
    "I shall answer presently — deliberation first, pronouncement after.",
    "Hold on briefly — I want to be precise, as a judge must be.",
    "Hmm — let me turn this over once or twice before I speak.",
    "There is wisdom in the pause; allow me mine.",
    "A fine point. I am drawing on many years to answer it well.",
    "Sandali lamang po — a careful answer is a kind answer.",
    "Let me marshal the relevant memories; they are many.",
    "Ah, you test my recollection — pleasantly so. One moment.",
    "Every good ruling begins with quiet thought. Grant me a little.",
    "I am consulting my own precedents, so to speak.",
    "Bear with me po; I would rather be right than quick.",
    "Yes — I know just where to look for this. A brief moment.",
]

FILLER_DIR = os.path.expanduser("~/fillers")
BAIL_DIR = os.path.expanduser("~/fillers_bail")
BAIL_TEXTS_JSON = ("/tmp/claude-1000/-home-pollen-Supervaise-Reachy-Mini-Project-develop/"
                   "a0e8e511-d3f1-4d4d-8e7e-945d10b2e583/scratchpad/bail_texts.json")
STAMP = time.strftime("%Y%m%d")


def synth_wav(text: str, wav_path: str, rate: int | None = None) -> None:
    """Cloned voice + the SAME EQ chain live answers get (voice.audio.process)."""
    norm = v_cache.normalize_text(text)
    pcm = v_audio.process(synthesize(norm), v_audio.SYNTH_SAMPLE_RATE)
    sr = v_audio.SYNTH_SAMPLE_RATE
    if rate and rate != sr:
        pcm = v_audio.resample(pcm, sr, rate)
        sr = rate
    sf.write(wav_path, pcm, sr, subtype="PCM_16")


def main() -> int:
    bail_texts = json.load(open(BAIL_TEXTS_JSON, encoding="utf-8"))

    for d in (FILLER_DIR + ".new", BAIL_DIR + ".new"):
        shutil.rmtree(d, ignore_errors=True)
        os.makedirs(d)

    try:
        for i, text in enumerate(FILLER_TEXTS, 1):
            synth_wav(text, f"{FILLER_DIR}.new/{i:02d}.wav")  # 24 kHz like the old pool
            print(f"  filler {i:02d} ok")
            time.sleep(0.15)  # gentle on the API
        for name, text in bail_texts.items():
            synth_wav(text, f"{BAIL_DIR}.new/{name}", rate=16000)  # bail wavs are 16 kHz mono
            print(f"  bail {name} ok")
    except SynthError as e:
        print(f"FATAL: synthesis failed ({e.reason}: {e}) — nothing swapped, "
              f"live pools untouched")
        return 1

    # --- swap in (current accent pools kept as .bak) ---
    for live in (FILLER_DIR, BAIL_DIR):
        bak = f"{live}.bak-accent-{STAMP}"
        shutil.rmtree(bak, ignore_errors=True)
        os.rename(live, bak)
        os.rename(live + ".new", live)
        print(f"[swap] {live}  (old -> {bak})")
    print("done — all pre-recorded clips are now the cloned voice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
