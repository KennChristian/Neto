"""Quantitative audit of G2 clips — reports duration + format per voice
so we can correlate clip length with audible quality.

The "rushed / one-syllable" symptom should correlate with very short
duration. Mean duration per model tier tells us whether the issue
sits on tts-1 voices, gpt-4o-mini-tts voices, or is unrelated.
"""
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import statistics
import wave
from pathlib import Path

D = Path(__file__).resolve().parent / "g2_clips"
TTS1  = {"alloy", "echo", "fable", "onyx", "nova", "shimmer"}
GPT4O = {"ash", "ballad", "coral", "sage", "verse"}

rows = []
for w in sorted(D.glob("*.wav")):
    # OpenAI's streaming WAV response writes a 32-bit max-int into the
    # data-chunk size field (because the size isn't known when streaming),
    # so wave.getnframes() returns ~2 billion. Compute duration directly
    # from the file size instead.
    with wave.open(str(w), "rb") as f:
        rate = f.getframerate()
        ch   = f.getnchannels()
        sw   = f.getsampwidth()
    size_bytes = w.stat().st_size
    audio_bytes = max(0, size_bytes - 44)          # subtract WAV header
    dur = audio_bytes / (rate * ch * sw)
    voice = w.stem
    tier  = "tts-1" if voice in TTS1 else ("gpt-4o-mini-tts" if voice in GPT4O else "?")
    rows.append((voice, tier, dur, rate, ch, sw, size_bytes))

print(f"{'voice':10s} {'tier':18s} {'dur(s)':>7s} {'rate':>6s} {'ch':>3s} {'bytes':>7s}")
print("-" * 60)
for v, tier, dur, rate, ch, sw, size in rows:
    flag = "  RUSHED" if dur < 0.7 else ("  CLEAN" if dur > 1.0 else "")
    print(f"{v:10s} {tier:18s} {dur:7.3f} {rate:6d} {ch:3d} {size:7d}{flag}")

print()
t1 = [r[2] for r in rows if r[1] == "tts-1"]
g4 = [r[2] for r in rows if r[1] == "gpt-4o-mini-tts"]
print(f"tts-1            mean={statistics.mean(t1):.3f}s  "
      f"n={len(t1)}  range=[{min(t1):.3f}, {max(t1):.3f}]")
print(f"gpt-4o-mini-tts  mean={statistics.mean(g4):.3f}s  "
      f"n={len(g4)}  range=[{min(g4):.3f}, {max(g4):.3f}]")

print()
print("Flag thresholds: dur < 0.7 s = RUSHED (likely fragmented),")
print("                 dur > 1.0 s = CLEAN (room for full 'Hey C-J').")
