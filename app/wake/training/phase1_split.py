"""Phase 1 Task 1 — silence-based splitting of real-voice "Hey CJ" raws.

Per-file thresholds (selected from phase1_probe.py output):

  heycj_male1_clean.wav    silence_thresh = -50 dBFS
                            (noise floor -76, peak speech RMS -32 →
                             midpoint -54; use slightly higher to
                             ensure mouth-noise/breaths don't trigger)

  heycj_male2_clean.wav    silence_thresh = -52 dBFS
                            (noise floor -80, peak speech RMS -35)

  heycj_female1_cafe.wav   SKIPPED — file fails the structural check.
                            Noise floor is -106 dBFS (pure-silence
                            artefact, probably edit-point digital
                            silence) but median is -26 dBFS (cafe
                            babble is essentially as loud as speech).
                            The ~80 dB gap means split_on_silence will
                            only fire on edit points, NOT on
                            utterance boundaries. Flagged for manual
                            splitting per operator's instruction.

Common to all:
  min_silence_len = 300 ms
  keep_silence    = 100 ms
  Output: 16 kHz mono 16-bit PCM WAV, one utterance per file, written
  to app/wake/data/real_split/<file_stem>/<file_stem>_NN.wav.

QA at the end: per-file count, duration histogram, flags for clips
  < 0.5 s (likely half-word) or > 2.5 s (likely two utterances
  merged).
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from pydub import AudioSegment
from pydub.silence import split_on_silence


RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "real_raw"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "real_split"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# Per-file params chosen from phase1_probe.py output. silence_thresh
# is in dBFS (negative numbers; higher = stricter silence requirement).
CLEAN_FILES = [
    {
        "name": "heycj_male1_clean.wav",
        "silence_thresh": -50,
        "min_silence_len": 300,
        "keep_silence": 100,
    },
    {
        "name": "heycj_male2_clean.wav",
        "silence_thresh": -52,
        "min_silence_len": 300,
        "keep_silence": 100,
    },
]

SKIPPED_FILES = [
    {
        "name": "heycj_female1_cafe.wav",
        "reason": (
            "Noise floor -106 dBFS (artefact) but median -26 dBFS "
            "(cafe babble ≈ speech level). split_on_silence fires "
            "only on edit-point digital silences, not real utterance "
            "boundaries. Needs manual splitting."
        ),
    },
]


def split_file(cfg: dict) -> dict:
    src = RAW_DIR / cfg["name"]
    stem = src.stem
    dst_dir = OUT_DIR / stem
    dst_dir.mkdir(exist_ok=True, parents=True)

    print(f"\n── {cfg['name']} "
          f"(silence_thresh={cfg['silence_thresh']} dBFS, "
          f"min_silence_len={cfg['min_silence_len']} ms, "
          f"keep_silence={cfg['keep_silence']} ms) ──")

    seg = AudioSegment.from_wav(str(src))
    print(f"  loaded: {len(seg) / 1000:.1f} s, "
          f"{seg.frame_rate} Hz, {seg.channels} ch, "
          f"{seg.sample_width * 8}-bit")

    # Normalise to 16 kHz mono 16-bit BEFORE splitting so the
    # silence_thresh refers to the target format. pydub's split_on_silence
    # operates on AudioSegment frames, so the resampling needs to
    # happen first.
    seg = seg.set_channels(1).set_frame_rate(16000).set_sample_width(2)
    print(f"  normalised: 16000 Hz · 1 ch · 16-bit")

    chunks = split_on_silence(
        seg,
        min_silence_len=cfg["min_silence_len"],
        silence_thresh=cfg["silence_thresh"],
        keep_silence=cfg["keep_silence"],
    )

    durations_ms = []
    for i, chunk in enumerate(chunks):
        out_path = dst_dir / f"{stem}_{i:02d}.wav"
        chunk.export(str(out_path), format="wav")
        durations_ms.append(len(chunk))

    print(f"  chunks written: {len(chunks)} → {dst_dir.relative_to(RAW_DIR.parent)}")

    return {
        "name": cfg["name"],
        "n_chunks": len(chunks),
        "durations_ms": durations_ms,
        "out_dir": dst_dir,
    }


# ── Run ──
print("=" * 70)
print("Phase 1 Task 1 — silence-based splitting")
print("=" * 70)

results = []
for cfg in CLEAN_FILES:
    try:
        results.append(split_file(cfg))
    except Exception as e:
        print(f"  FAIL on {cfg['name']}: {type(e).__name__}: {e}")

for skipped in SKIPPED_FILES:
    print(f"\n── {skipped['name']} — SKIPPED ──")
    print(f"  Reason: {skipped['reason']}")


# ── QA Task 2: per-file counts, duration distribution, flagged clips ──
print()
print("=" * 70)
print("Task 2 — QA summary")
print("=" * 70)

LOW_DURATION_MS = 500    # < 0.5 s → likely half-word
HIGH_DURATION_MS = 2500  # > 2.5 s → likely two utterances merged

grand_total = 0
for r in results:
    durs = sorted(r["durations_ms"])
    if not durs:
        print(f"\n{r['name']}: 0 chunks (split failed). Skipped.")
        continue
    n = len(durs)
    grand_total += n
    mean = sum(durs) / n
    median = durs[n // 2]
    too_short = [d for d in durs if d < LOW_DURATION_MS]
    too_long = [d for d in durs if d > HIGH_DURATION_MS]

    print(f"\n{r['name']}: {n} chunks")
    print(f"  duration ms — min={durs[0]}  "
          f"p25={durs[n // 4]}  "
          f"median={median}  "
          f"p75={durs[(3 * n) // 4]}  "
          f"max={durs[-1]}")
    print(f"  duration s  — mean={mean / 1000:.2f}  "
          f"median={median / 1000:.2f}")
    print(f"  flags:")
    print(f"    < {LOW_DURATION_MS} ms (likely half-word):  "
          f"{len(too_short)}  {too_short[:5]}")
    print(f"    > {HIGH_DURATION_MS} ms (likely merged):    "
          f"{len(too_long)}  {too_long[:5]}")
    healthy = n - len(too_short) - len(too_long)
    print(f"  healthy (between {LOW_DURATION_MS}-{HIGH_DURATION_MS} ms): "
          f"{healthy} / {n}")

print()
print(f"Grand total chunks across all split files: {grand_total}")
print()
print("Operator listening recommendation:")
print("  Pick 2-3 random chunks per file, play them via Windows Media")
print("  Player / VLC, confirm each contains exactly one clean 'Hey CJ'")
print("  utterance with no overlap from another speaker.")
