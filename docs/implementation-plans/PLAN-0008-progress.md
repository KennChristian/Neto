# PLAN-0008 — Wake-Word Milestone 1 — Progress Tracker

Updated: 2026-06-08 (Phase 2 retrain locked; v2 "Hey CJ" model committed)

Maintained per PLAN-0008 §8 so a fresh Claude Code session can resume.

---

## Status board

| Task | Status | Owner check-in required? |
|---|---|---|
| Task 0 — Plumbing / de-risk (stock model, no pipeline) | ✅ **done · operator-verified 2026-06-03** | done |
| Task 1 — Rung 1 custom "Hey CJ" model | ✅ **done · v2 retrain locked 2026-06-08** | done |
| Task 2 — State machine + Python capture | pending | |
| Task 3 — Wire to existing pipeline funnel | pending | ✅ YES |
| Task 4 — Portability seam + docs + ADR | pending | |

**Trigger scope (locked 2026-06-08):** single wake phrase **"Hey CJ"**.
CJP / Hey CJP were dropped as wake-word targets — the on-screen
prompt handles that affordance instead. The voice classifier only
needs to recognise one phrase, which is what v2 is trained on.

---

## Decisions taken so far (Task 0)

- **Engine choice:** openWakeWord (PLAN §2). Picovoice Porcupine remains the contingency
  per PLAN §2 — not built.
- **Inference backend:** `inference_framework="onnx"` rather than the default `"tflite"`.
  Reason: tflite_runtime wheels on Windows + Python 3.10/3.11 are fragile;
  onnxruntime is a reliable wheel. Confirmed from `openwakeword/model.py` source
  that "onnx" is a valid string.
- **Audio capture (laptop):** `sounddevice` `InputStream` with `dtype="int16"`,
  `samplerate=16000`, `channels=1`, `blocksize=1280` (= 80 ms — the openWakeWord
  per-call ideal chunk size confirmed from source).
- **Threading model — three threads, single Streamlit-state writer:**
  - Audio thread (sounddevice-owned, audio priority): InputStream callback receives a
    `(1280, 1)` int16 array; flattens to 1-D and pushes onto a bounded
    `queue.Queue(maxsize=100)`. Drop-oldest on overflow.
  - Worker thread (engine-owned, daemon): pulls frames, calls `model.predict(frame)`,
    writes to lock-protected member fields on engine. **Does not touch
    `st.session_state`** — not thread-safe.
  - Main Streamlit thread: on each rerun, calls `engine.poll_detection()` which reads
    & consumes the latest detection under the engine's lock. Single writer to
    `st.session_state`.
- **Rerun strategy:** `streamlit-autorefresh` at 500 ms while engine is running.
  When engine is stopped, no polling — zero idle CPU.
- **Engine persistence across reruns:** stored as `st.session_state.wake_engine`
  singleton. Idempotent `engine.start()` so reruns can't spawn duplicates.
- **Stock test model:** `hey_jarvis` (less common in incidental speech than
  `alexa`; easier to test deliberately). Switchable in the test UI.
- **UI surface for Task 0:** a **standalone** `app/wake_test.py` Streamlit page.
  `app/app.py` is NOT modified in Task 0 — guarded per PLAN §5
  ("do not break the existing browser-record path while developing").

---

## Files added/modified (Task 0)

NEW:
- `app/wake/__init__.py` — package marker
- `app/wake/sources.py` — `AudioSource` ABC + `SoundDeviceSource` concrete impl
- `app/wake/engine.py` — `WakeWordEngine` class
- `app/wake_test.py` — standalone Streamlit dev page

MODIFIED:
- `app/requirements.txt` — added `openwakeword`, `sounddevice`,
  `streamlit-autorefresh`. No other changes.

GUARDED — NOT touched (PLAN §5):
- `app/app.py`
- `app/cj_chat.py`
- `app/voice_io.py`
- `corpus/voice/*`

---

## Acceptance criteria for Task 0 — ✅ ALL PASSED (operator 2026-06-03)

Verbatim from PLAN-0008 §6 plus the regression guard.

1. [x] `pip install -r app/requirements.txt` succeeds in the existing venv.
2. [x] `streamlit run app/wake_test.py` launches without import errors.
3. [x] Pressing **Start** loads the openWakeWord model and shows the
       "😴 SLEEPING …" banner. First load downloaded the four shared
       feature/VAD models + the hey_jarvis classifier in both
       formats — surfaced as visible phases in the `st.status` block
       after the post-fix on 2026-06-03 (see "Surprise + fix" below).
4. [x] Saying "hey jarvis" produces a **🎯 WAKE DETECTED** banner + new row
       in the detection log within ~500 ms. **Operator observed scores
       ~0.99.**
5. [x] Pressing **Stop** terminates the engine cleanly.
       `engine.stats()["thread_alive"]` returns `False` after stop.
6. [x] Restart/Stop cycle 5×: `start_count` increments by exactly 1 per
       full cycle. **Operator confirmed no leaked engines.**
7. [x] **Regression**: `streamlit run app/app.py` still works exactly as
       before. **Operator confirmed kiosk unchanged.**
8. [x] `git diff app/app.py app/cj_chat.py app/voice_io.py corpus/voice/`
       returns empty.

---

## Open questions / risks

- **Pretrained-model files are NOT bundled in the pip package.** (Corrected
  2026-06-03 after Task 0 verification surfaced this — see "Surprise + fix"
  below.) The `openWakeWord` pip distribution ships with no `.onnx` /
  `.tflite` files; they must be downloaded after install via
  `openwakeword.utils.download_models()`. The `Model(...)` constructor does
  NOT auto-download. Engine now handles this in two ways: (a) the test page
  calls `WakeWordEngine.ensure_models_downloaded([name])` explicitly before
  `start()` so the download phase is visible in the UI, and (b) `start()`
  catches `NO_SUCHFILE` / `FileNotFoundError` defensively, downloads, and
  retries once — so even a caller who forgets the explicit ensure step
  recovers cleanly.
- **`sounddevice` device override.** Engine logs the active device name on
  start. If the visitor's default input is wrong, a `device=N` kwarg can be
  added to `SoundDeviceSource` later — not needed for Task 0.
- **Predict() input shape.** Source comment is ambiguous between 1-D and 2-D.
  Engine passes a 1-D int16 numpy array (which matches the `np.frombuffer(...,
  dtype=np.int16)` usage elsewhere in openwakeword/model.py).
- **`predict()` is synchronous.** Confirmed from source. Runs in the worker
  thread, so blocking is fine; audio thread is not affected.

---

## Surprise + fix (2026-06-03 · still in Task 0)

**Operator hit:**
```
RuntimeError: openWakeWord.Model() failed to load 'hey_jarvis'.
Underlying error: NoSuchFile: [ONNXRuntimeError] : 3 : NO_SUCHFILE :
Load model from .../site-packages/openwakeword/resources/models/
hey_jarvis_v0.1.onnx failed. File doesn't exist
```

**Bad assumption (now corrected above):** my original risk note said
*"First Model() instantiation may auto-download the ONNX model from
openWakeWord's GitHub release"*. That's wrong. Verified from
`openwakeword/utils.py` source (WebFetch 2026-06-03):

  * `Model(...)` does not call `download_models()` anywhere.
  * `openwakeword.utils.download_models(model_names=[...])` is the only
    download path. Skips already-present files. Idempotent.
  * For each wake-word name passed in, downloads BOTH `.tflite` and
    `.onnx` (one branch only — the `download_file(url[0].replace(
    ".tflite", ".onnx"), ...)` line). So choosing `inference_framework=
    "onnx"` is fine — the `.onnx` variant lands on disk.
  * Also downloads the shared `FEATURE_MODELS` (`melspectrogram`,
    `embedding_model`) in both formats, and the VAD model
    (`silero_vad.onnx`). The mel-spec + embedding files are required
    EVEN for ONNX inference — they're the preprocessor stage every wake
    word shares. Their absence was the actual NoSuchFile that bubbled
    up via the wake-word file path.

**Fix (engine.py + wake_test.py):**

1. `WakeWordEngine.ensure_models_downloaded(model_names, progress_cb=None)`
   — new static method that wraps `openwakeword.utils.download_models()`,
   surfaces clear error messages, and emits phase strings via
   `progress_cb` for the UI.
2. `WakeWordEngine.start(progress_cb=None)` — now accepts the same
   callback, calls `ensure_models_downloaded([self.model_name])`
   defensively if the first `Model(...)` raises a missing-file error,
   then retries once. So a caller who skips the explicit ensure still
   recovers; the engine self-heals from the first-run state.
3. `app/wake_test.py` — replaces the single `st.spinner` with an
   `st.status` block that calls `ensure_models_downloaded` explicitly
   before `start()`, then writes each phase as its own `st.write` row.
   The download phase becomes a clearly-labelled step (`⏳ Checking
   openWakeWord model files for hey_jarvis (downloads on first run,
   ~10-30 MB)…`) so a 20-second download is never mistaken for a hang.

**Files changed in this fix:**
- `app/wake/engine.py` (added `ensure_models_downloaded`,
  `_looks_like_missing_model_file`, `progress_cb` plumbing on `start`)
- `app/wake_test.py` (st.spinner → st.status block with phase log)
- `docs/implementation-plans/PLAN-0008-progress.md` (this file)

**Guarded files still untouched** — `git diff app/app.py app/cj_chat.py
app/voice_io.py corpus/voice/` returns empty.

---

## Task 1 — execution log (post-Gate-2c, 2026-06-06)

### Phrase pool — final for G4 (locked after G2 + G2b + G2c listening)

| Trigger | Variants in positive class | Reason |
|---|---|---|
| **CJ** | `"Hey CJ."` (period) AND `"Hey see jay"` (phonetic) | Both verified clean on ash + ballad at G2b. Mix gives acoustic diversity for visitors who pronounce CJ as "see-jay" vs as "cee-jay". |
| **CJP** | `"Hey see jay pee"` (phonetic only) | G2c proved this is the ONLY formulation that reliably keeps the trailing "P". Period and spaced each ate the P on one of the two test voices (duration-delta heuristic confirmed). |
| **CJP-bare** ⚠️ | `"see jay pee"` (phonetic only) — the third trigger added by operator at G3 prep | Allows visitors to skip "Hey" entirely. **Acknowledged tradeoff:** bare "CJP" is shorter/lower-information than "Hey CJP" so it is more prone to false positives against unrelated speech (any "see jay pee"-shaped phoneme sequence in conversation could fire). **Gatekeeper: G6 false-positive test.** If bare-CJP misfires materially during the normal-speech FP corpus (>1 trigger per minute), it gets dropped back to just the two "Hey"-prefixed variants. Operator decision recorded here so the choice survives any context loss. |

### Negatives corpus — locked at G3 with explicit tradeoffs

The full ACAV100M features file is 16.48 GB. Operator bandwidth is 4-25 Mbps,
making the full download a 1.5-9 hr proposition with material drop-out risk.
Operator chose a 1.5 GB sliced download (~9.3 % of the data, ~1.8 hrs of
feature time) as the Rung 1 accepted trade. Recovery ladder if G6 false-
positive rate is too high:

  1. **Threshold tuning first** — raise `WAKE_THRESHOLD` in
     `app/wake/engine.py` from 0.5 → 0.6 → 0.65. Cheap, no retrain.
  2. **Drop the bare "CJP" trigger and retrain on the same 1.5 GB slice** —
     keeps the two "Hey CJ" / "Hey CJP" phrases (which carry more
     discriminating phonetic content) and removes the most-FP-prone trigger.
  3. **Pull more negatives** (3 GB or full 16.5 GB) and retrain.

This ladder is the FP gatekeeper for G6.

### Voices — locked

`gpt-4o-mini-tts` only: **5 voices** (ash, ballad, coral, sage, verse).
- `tts-1` tier (alloy, echo, fable, nova, onyx, shimmer) DROPPED — verified at G2/G2b that this model truncates short phrases to ~0.46s regardless of formulation; even phonetic spelling on echo only reached 0.66s.
- `spruce` not available via OpenAI API (HTTP 400).

### Audio pipeline per clip (locked)

1. OpenAI `gpt-4o-mini-tts` → 24 kHz mono 16-bit WAV via streaming response
2. `librosa.load(..., sr=16000)` → resample to openWakeWord's expected rate
3. `librosa.effects.trim(...)` → strip leading/trailing silence
4. Small safety pad (~50 ms zeros) added at start + end so the final "p" plosive isn't clipped
5. `soundfile.write(..., 16000, subtype='PCM_16')` → final WAV ready for `positive_train/`

Pre-G4: 3 pre-trim samples generated for operator listening confirmation before the full ~135-clip run, to verify the trim doesn't chop the final "P".

### Recomputed G4 matrix

```
voices        5  (ash, ballad, coral, sage, verse)
speeds        3  (0.85, 1.0, 1.15)
phrases       4  ("Hey CJ.", "Hey see jay", "Hey see jay pee", "see jay pee")
raw outputs   5 × 3 × 4 = 60  raw tts-1 clips (train)
val raw       additional 60 clips for positive_test/ (val)
post-trim     each clip resampled to 16 kHz + silence-trimmed + 50ms pad
augmentation  audiomentations: PitchShift × TimeStretch × AddGaussianNoise
              ~7× expansion → 60 × 7 = 420 + 60 raw = 480 augmented for train
              60 × 1 = 60 for val (lighter augmentation)
n_samples     500 (skip-Piper threshold = ≥ 95% × 500 = 475)
n_samples_val 100
```

### Cost — updated estimate

```
G4 raw (train):     60 calls × ~14 chars = 840 chars
G4 raw (val):       60 calls × ~14 chars = 840 chars
Pre-trim samples:    3 calls × ~14 chars =  42 chars
─────────────────────────────────────────────────────
Total chars:                              1 722 chars
Rate:                                    $0.060 / 1k
Estimated G4 spend:                          ~$0.103

Cumulative Task 1 (G2 + G2b + G2c + G4):    ~$0.115
                                             vs $0.50 budget = 23%
```

---

## G5 — ✅ trained classifier produced (2026-06-06)

After many Windows-specific patches, training succeeded. The trained
model is at:

  app/wake/models/hey_cj.onnx           (15 kB, copied from
  app/wake/training/oww_output/hey_cj.onnx)

ONNX validation via onnxruntime:
  input : x       shape=[1, 16, 96]  tensor(float)
  output: sigmoid shape=[1, 1]       tensor(float)

Shape matches the openWakeWord embedding pipeline (16 embedding frames
× 96 features), which is what the Task-0 WakeWordEngine's
mel-spec → embedding stack already feeds.

### Training pipeline patches required for Windows + Python 3.11

Every one of these is a Windows incompatibility upstream openWakeWord
does not catch. Recorded so a fresh session can reapply:

1. **sitecustomize.py** in `app/.venv-training/Lib/site-packages/`:
   - UTF-8 reconfigure on stdout/stderr (`✅` emoji in torch.onnx
     verbose print crashed cp1252 console).
   - `scipy.special.sph_harm` shim (removed in SciPy 1.15+; acoustics
     0.2.6 still imports it).
   - `torch.load(weights_only=False)` default (PyTorch 2.6 flipped it;
     deep_phonemizer's pickled tokeniser needs the old behaviour).
   - `speechbrain.LazyModule.__getattr__` ImportError → AttributeError
     (so `hasattr()` skip-on-missing works; otherwise
     `torch.library.custom_op`'s `inspect.getmodule` chain crashes
     when torch.optim.Adam imports torch._dynamo → torch.distributed).
   - `torchaudio.load` → soundfile shim (torchaudio 2.11 routes through
     torchcodec, whose Windows wheel needs system FFmpeg DLLs).
   - `generate_samples` stub module (openwakeword/train.py imports it
     unconditionally; only called if positives aren't pre-populated).

2. **`openwakeword/utils.py compute_features_from_generator`** —
   explicit close + GC of `fp` memmap before calling `trim_mmap` so
   Windows can delete the file (POSIX delete-while-mapped works,
   Windows raises PermissionError WinError 32).

3. **`openwakeword/data.py trim_mmap`** — explicit close + GC of both
   mmap_file1 and mmap_file2 before `os.remove`/`os.rename`.

4. **`openwakeword/train.py`** — three patches:
   - DataLoader `num_workers=0` (spawn-pickle fails on lambdas).
   - Lock `config["total_length"] = 32000` (= 2.0 s) so the feature
     sequence length is 16, matching the ACAV slice. The auto-
     calculation computed 44000 (= 2.75 s, seq_len=22) from our
     median 2.0 s clips and broke vstack alignment with ACAV.
   - Save `best_model` state_dict to `<output_dir>/<name>.pt` BEFORE
     `export_model` so 22 min of CPU training survives any ONNX-
     export crash.

5. **`g5_train.py`** — `subprocess.Popen(..., encoding="utf-8",
   errors="replace")` so the subprocess's UTF-8 stdout doesn't crash
   the parent's cp1252 default decoder while the subprocess is still
   running.

6. **Pip-installed deps that aren't in openwakeword's wheel metadata
   but are needed by `train.py` at module load:**
   - pronouncing, acoustics, mutagen, speechbrain, deep-phonemizer,
     torch-audiomentations, datasets<3, torchcodec, onnxscript

### Training stats (final successful run)

  steps run     : 10 000  (config) — multiple auto_train rounds
  positives     : 480 train, 60 val   (post-G4)
  negatives     : 455 train, 50 val   (post-G4b, adversarial)
  ACAV slice    : 524 287 rows × 16 × 96  (1.5 GB, post-G3)
  validation    : 481 345 × 96         (176 MB, post-G3)
  total_length  : 32 000 samples (2.0 s @ 16 kHz)
  layer_size    : 32 (dnn)
  trained model : 15 kB sigmoid classifier on 16×96 embeddings
  wall-clock    : ~22 min CPU per training round, ~25 min total

### Cumulative Task 1 spend

  G2  (11 voice probe):     $0.00153
  G2b (9 phrasing probe):   $0.00338
  G2c (6 CJP probe):        $0.00384
  G3 pre-trim (3 clips):    $0.00198
  G4 (120 positive calls):  $0.06600
  G4b (505 negative calls): $0.33930
  G5 (training):            $0 (CPU-only)
  ─────────────────────────────────
  Total Task 1 spend:       $0.41603  (~83% of $0.50 budget)

---

## Phase 2 — recall fix retrain (2026-06-08)

### Why a retrain was needed

G6 live-mic verification of v1 surfaced a recall gap. Per-utterance
score logging in `wake_test.py` (added 2026-06-07) showed the v1
classifier scored "Hey CJ" near the 0.5 threshold but "CJP" / "Hey
CJP" landed well below it — under 0.1 in most attempts. Diagnosis:
the entire v1 positive set was synthetic (OpenAI tts-1 voices) so
the classifier had never heard a real human voice on the trigger.

Decision: ship **single-trigger "Hey CJ"** and drop CJP / Hey CJP as
wake-word targets (the museum kiosk's on-screen prompt handles that
affordance). Then add real human voices to the training set.

### Phase 1 — positives prep (no retrain)

Operator supplied three raw WAVs in `app/wake/data/real_raw/`:

| File | Length | Outcome |
|---|---|---|
| `heycj_male1_clean.wav` | 55.8 s | Auto-split → 28 clips |
| `heycj_male2_clean.wav` | 54.2 s | Auto-split → 29 clips |
| `heycj_female1_cafe.wav` | 57.4 s | **Skipped** — 80 dB noise-floor/median gap from cafe babble; `split_on_silence` would only fire on edit-point silences. Deferred for manual splitting. |

Splitter: `app/wake/training/phase1_split.py` — per-file
`silence_thresh` chosen from a noise-floor probe
(`phase1_probe.py`), `min_silence_len=300 ms`, `keep_silence=100 ms`,
normalised to 16 kHz mono 16-bit before splitting. All 57 clean
clips landed in 581–925 ms with **zero** outliers flagged.

### Phase 2 — retrain with real voices added

Prep script: `app/wake/training/phase2_prep.py`.

- **Held-out val:** 4 clips per speaker (indices 03, 10, 17, 24) →
  `positive_test/real_*.wav`, no augmentation. 8 clips total.
- **Train:** remaining 24 + 25 = 49 raw clips, each augmented 7×
  with the SAME `audiomentations` stack used in G4
  (PitchShift ±2 st, TimeStretch 0.90–1.10×, AddGaussianSNR 15–40 dB)
  → 49 raw + 343 aug = **392 new train clips**.
- The existing 480 TTS positives stayed unchanged (one variable change
  per pass: real voices added).
- Stale `positive_features_*.npy` caches deleted to force re-encoding.

Final counts:

|  | v1 | v2 |
|---|---|---|
| `positive_train` | 480 | **872** (+392) |
| `positive_test` | 60 | **68** (+8 real-voice held-out) |
| Negatives | 455 train / 50 val | unchanged (recall fix — negatives untouched) |

Training: `g5_train.py` re-invoked. ~25 min CPU; converged through
the same DNN(32) recipe. Output ONNX (split-external-data) saved at
`oww_output/hey_cj.onnx + .onnx.data`, then consolidated to
`app/wake/models/hey_cj.onnx` (210.6 kB, `x[1,16,96]` → `sigmoid[1,1]`).

### Hygiene patch applied to upstream train.py

`app/.venv-training/.../openwakeword/train.py` lines 932-933:
the cosmetic post-export `convert_onnx_to_tflite` step is now wrapped
in `try/except (ModuleNotFoundError, ImportError, Exception)`. The
kiosk runs ONNX-only, so the tflite conversion (which requires
`onnx_tf` + a TF1 toolchain that won't install on Windows + Py 3.11)
was never used. Without the patch, training returned exit 1 even
though all artefacts were on disk. With the patch, runs return 0
cleanly once the ONNX is written.

### v1 → v2 head-to-head on the 8 held-out real-voice clips

Eval script: `app/wake/training/phase2_eval.py`.

|  | v1 (TTS-only) | v2 (TTS + real) | Δ |
|---|---|---|---|
| mean peak | 0.286 | **0.921** | +0.635 |
| median peak | 0.013 | **0.921** | +0.909 |
| fires @ 0.50 | 2 / 8 (25 %) | **8 / 8 (100 %)** | — |
| fires @ 0.35 | 3 / 8 (38 %) | **8 / 8 (100 %)** | — |

Live-mic verification (operator, 2026-06-08): **80–90 % recall** on
"Hey CJ" at threshold 0.40, no false fires on background speech in
the operator's test session.

**Threshold initially locked at 0.40** then **retuned to 0.35 on
2026-06-11** after the D:→C: venv consolidation surfaced quieter
live-mic peaks in the C:-venv test room. `wake_test.py` fired
~15/20 at 0.35 there; the kiosk runtime constructor + the slider
default in `wake_test.py` were both moved to 0.35 to match. Three
sites kept consistent:
- `app/wake/engine.py` — `WakeWordEngine.__init__` default
- `app/wake_test.py` — slider default
- `app/app.py` — `_build_wake_engine_cached()` construction

Higher (0.50) over-rejects on quieter / further-away utterances;
lower (0.30) starts catching mild background speech.

### Generalisation caveat — record this

The 8 held-out clips are all from the **same two male speakers**
whose voices appear (held-out only) in the val set. The model has
**never seen the cafe-skipped female speaker, nor any new voice**.
v2's 80-90 % live result is on the operator's own voice. Female /
new-voice generalisation will only be measured when more speakers
are added. Cafe file manual-split + female positives are deferred
work; the museum demo on May 30 is fine with the operator-class
voice profile, but a single-voice failure mode under public-floor
visitors should be planned for.

### Artefacts on disk after Phase 2

- `app/wake/models/hey_cj.onnx` — v2 (210.6 kB) — **the production model**
- `app/wake/models/hey_cj.v1.onnx` — v1 rollback (215.7 kB)
- `oww_output/hey_cj.{onnx,onnx.data,pt}` — v2 split + torch checkpoint (gitignored)
- `oww_output/hey_cj.v1.{onnx,onnx.data,pt}` — v1 split + checkpoint (gitignored)
- `app/wake/data/real_split/` — 57 split clips (gitignored)
- `app/wake/training/phase1_*.py`, `phase2_*.py` — retrain pipeline (committed)

Guarded files (`app/app.py`, `app/cj_chat.py`, `app/voice_io.py`,
`corpus/voice/*`) **untouched** in Phase 2.

---

## Task 2 — kiosk integration complete (2026-06-12)

### Hands-free state machine

`app/app.py` was reworked into a five-state machine:

```
OFF → SLEEPING → LISTENING → PROCESSING → RESPONDING → SLEEPING
```

START is a single power-toggle (OFF ↔ SLEEPING). Every new question
requires "Hey CJ" — no follow-up window, no replay button.
`record_until_silence` (cj_chat.py) replaces the prior browser
`st.audio_input` as the capture mechanism. `_run_pipeline`
end-state set to `RESPONDING`; TTS-done timer drives the return
to `SLEEPING`.

### Singleton wake engine + turn lock

Wake engine lifted from `st.session_state` to a process-wide
`@st.cache_resource` singleton — Streamlit re-executes the script
body on every rerun, so a naive module-level global gets reset on
every poll tick and rebuilds the engine ~12 times per second
(regression caught 2026-06-12). The `@st.cache_resource` pattern
truly survives reruns and is shared across all sessions. The same
treatment applied to the `_TURN_LOCK` and `_ENGINE_LOCK`
`threading.Lock` instances.

Turn lock gates the LISTENING → PROCESSING → RESPONDING cycle so
two concurrent browser sessions can't both run the pipeline on a
single wake fire (the second session's detection is discarded with
a log line; that session stays in SLEEPING).

### Capture path

`cj_chat.record_until_silence` gained two opt-in parameters
(CLI defaults unchanged):

- `no_speech_timeout_s` — walkaway guard (kiosk passes 7 s).
- `silence_rms_threshold` — opt-in fixed threshold. When `None`
  (kiosk default), the function **auto-calibrates** from a ~240 ms
  noise-floor probe at the start of capture: `silence_threshold =
  clamp(noise_floor × 4, [350, 2500])`. Fixes the 30-second-capture
  regression where ambient hum > 350 RMS made every frame count as
  speech, `silence_run` never incremented, and EOS never triggered.

Capture stops ~1.2 s after speech ends (`trailing_silence_ms = 1200`,
unchanged from CLI).

### TTS playback (RESPONDING)

`_autoplay_audio` is re-rendered on every autorefresh tick while in
RESPONDING. The previous design rendered once (gated on
`autoplay_pending`), then Streamlit removed the `<audio>` DOM node
on the next rerun — playback cut at ~5 s regardless of measured
duration. Identical bytes across rerenders let Streamlit's diff
preserve the same DOM element; playback continues uninterrupted.

`tts_duration_s` measured via `voice_io.measure_mp3_duration_ms`
(mutagen-based — pure Python, no ffprobe binary needed). 1.5-s
grace pad on the wake-restart timer.

### voice_io toolchain

- `static-ffmpeg` adds both `ffmpeg.exe` AND `ffprobe.exe` to PATH
  on import (imageio-ffmpeg only ships ffmpeg, breaking pydub's
  `AudioSegment.from_file` which shells out to ffprobe).
- `measure_mp3_duration_ms` uses mutagen (pure Python, no shell
  dependency), wrapped in `try/except` so a measurement failure
  never crashes a turn — caller falls back to a chars-per-second
  estimate.

### Instrumentation

Per-poll log in SLEEPING (`[wake-poll #NNNN dt=…s] alive=… frames=…
preds=… last=… peak2s=… peak5s=… thr=… det=…`). Pipeline timing
logs around each stage (`[capture]`, `[capture-eos] noise probe …`,
`[pipeline] transcribe`, `[pipeline] route`, `[pipeline] compose`,
`[pipeline] tts+concat`, `[pipeline] TOTAL`). Speech-start and
speech-end logs in `record_until_silence`.

### Runtime venv consolidation (2026-06-11)

Active kiosk venv moved from `D:\Reachy Mini Project\App 2\app\.venv`
to `C:\Users\ASUS\Projects\Supervaise-Reachy-Mini-Project\app\.venv`
so code + venv co-locate. Frozen requirements at
`requirements-kiosk.txt` (128 packages). Old D: venv kept as
fallback during verification; legacy `app/.venv.old/` copy of the
D: venv kept as a second fallback. Both git-ignored.

### Status board update

| Task | Status |
|---|---|
| Task 0 — Plumbing | ✅ done · 2026-06-03 |
| Task 1 — Custom "Hey CJ" model | ✅ done · v2 retrain locked 2026-06-08, threshold retuned to 0.35 on 2026-06-11 |
| Task 2 — State machine + capture + integration | ✅ done · 2026-06-12 |
| Task 3 — Pipeline wiring | merged into Task 2 |
| Task 4 — Portability seam + ADR | deferred (Reachy Mini out of scope for May 30) |

---

## Task 1 spec (locked in by operator before kick-off)

When operator gives the go for Task 1, build a custom **"Hey CJ"**
wake-word model via openWakeWord's synthetic Piper-TTS training
pipeline. Per the operator's note when closing out Task 0:

  > "Task 1 is the custom 'Hey CJ' model — trained to also fire on
  > 'Hey CJP' (include 'Hey CJP' utterances in the synthetic
  > training set), per PLAN-0008 §6."

**One model, two trigger phrases.** Training set must include
both "Hey CJ" and "Hey CJP" synthesized utterances so a single
`.onnx` file fires on either. (This matches the cost case from
the earlier Picovoice exploration — visitors say either the full
title or just the initials.)

Practical training-data variants we already worked through (carry
forward — Piper TTS is known to mispronounce abbreviations):

  * `"Hey CJ"`, `"Hey see jay"` (phonetic spelling)
  * `"Hey CJP"`, `"Hey see jay pee"`, `"Hey C J P"` (spaced letters)

The exact list is a Task 1 implementation decision; the rule is
"include enough phonetic variants that Piper's abbreviation
resolution doesn't sink recall."

Deliverable: one `.onnx` classifier dropped at
`app/wake/models/hey_cj.onnx`. Engine constructor accepts a path
to a custom model (not just a stock name) — already designed for
this; the path branch is the non-stock case in `WakeWordEngine.__init__`.

Detection threshold to be tuned during Task 1 acceptance — start at
0.5, iterate.

**NO state-machine or pipeline-funnel work in Task 1.** Those are
Task 2 and Task 3. Task 1 is pure model-training + drop-in.

---

## Next session resumption notes

If you (a fresh Claude Code session) are resuming:

1. Read `docs/implementation-plans/PLAN-0008-wakeword-milestone-1.md` in full.
2. Read this file.
3. Read `app/wake/engine.py`, `app/wake/sources.py`, `app/wake_test.py` to
   see what is actually implemented.
4. Run `git log --oneline -10` to see recent commits.
5. Check the status board above. Task currently in flight is at the top of
   any "in_progress" row; do not proceed past a "✅ YES" check-in row
   without operator approval.
