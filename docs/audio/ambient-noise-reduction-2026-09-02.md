# Ambient noise reduction & replacing the ElevenLabs isolator

**Date:** 2026-09-02 · **Host:** Reachy Mini (CM4) · **Status:** analysis complete, Tier 0 not yet applied

Goal: cut ambient noise reaching the wake engine and Whisper, and replace
the paid ElevenLabs Voice Isolator with something that runs in real time,
locally, at no per-minute cost.

Companion file: [`xvf3800_baseline_20260902.json`](xvf3800_baseline_20260902.json)
— all 59 writable XVF3800 parameters as read before any change. This is the
revert baseline.

---

## 1. Signal topology (measured, not assumed)

There is exactly **one** USB audio card, and it is the DSP:

```
card 0: Audio [Reachy Mini Audio], device 0: USB Audio   ← playback AND capture
```

### Capture path (what CJ hears)

```
4 × MEMS mics ──> XVF3800 DSP ──USB 2ch 16 kHz──> ALSA dsnoop ──> ch L ──> _MicTap
   AEC_NUM_MICS=4              (AUDIO_MGR_OP_L/R = 8,0:      hw:CARD=Audio    16 kHz mono int16
   AEC_MIC_ARRAY_TYPE=1         both = processed beam)       ipc_key 4242     1280-frame (80 ms)
                                                                              main_voice_robot.py:1107
                                                                                  ├──> openWakeWord
                                                                                  └──> recorder → WAV → cloud Whisper
```

Channel **L** is what the voice app reads (`~/.asoundrc` →
`reachymini_audio_src_left`). Channel **R** is free and is repointed on
demand by `/maintain`'s mic meter (`pi_dashboard/mic_meter.py:40`) to a raw
mic `(3, 0..3)` or the AEC reference `(12, 0)`.

### Playback path (what CJ says) — and why the AEC is blind

The XVF3800 is built to be *both* ends of the loop. Its AEC reference is
whatever the host plays **into the chip over USB**:

```
INTENDED (internal speaker):
  host ──USB playback──> XVF3800 ──I2S DAC──> internal speaker
                            └── same signal is the AEC far-end reference ✅

ACTUAL TODAY (Bluetooth):
  host ──BlueALSA──> Sony/C41 Bluetooth speaker  ← audio never enters the chip
       XVF3800 far-end reference = silence               ❌
```

`~/.asoundrc.route` currently reads `type bluealsa`, device
`66:EA:C5:C3:E5:6B` (C41). So **the robot's own voice is, to the chip,
indistinguishable from ambient noise** — it arrives only through the mics,
with nothing to subtract it against. `pi_dashboard/mic_meter.py:44` already
names this exactly: the AEC reference is *"silent when a Bluetooth speaker
plays, which is the self-hearing problem in one picture."*

The existing workaround is `_RefFeed` (`main_voice_robot.py:1240`): play a
delayed copy of the outgoing audio into the chip over USB (`pcm.cj_ref_feed`
→ PipeWire → XMOS sink) while attenuating the internal speaker to −55 dB so
nobody hears the copy, and raising `AUDIO_MGR_REF_GAIN` 8 → 1000 to restore
the reference level the AEC sees.

**It is not running in production.** See §3.1.

---

## 2. How configurable is the DSP?

Very. It is a full software-defined DSP addressed over USB control transfers.

| Aspect | Detail |
|---|---|
| Transport | USB control transfer via `pyusb`; `~/bin/xvf-ctl read/write NAME [vals]` |
| Cost of a read | One control transfer, ~0.3 s wall (mostly module import) |
| Live? | **Yes** — writes take effect immediately, no restart, no audio dropout |
| Parameter count | 59 writable (`rw`) excluding LED/GPO/TEST/SPECIAL blocks |
| Safe to run live | Yes — reads are explicitly safe while the app polls DoA on the same endpoint (`xvf-ctl` docstring) |
| Persistence | `SAVE_CONFIGURATION` (48, 9) writes to flash; `CLEAR_CONFIGURATION` (48, 10) resets. **Unwritten changes are lost on power cycle.** |
| Overwritten at boot? | **No.** The SDK ships no defaults — `audio_base.py:186`: *"The SDK does not provide default values for these parameters; callers should pass the values tuned for their own app."* `apply_audio_config()` is only called on demand via the daemon's REST router. |
| Verification | `apply_audio_config(verify=True)` reads every parameter back after writing |
| Vendor reference | [XMOS XVF3800 control command appendix](https://www.xmos.com/documentation/XM-014888-PC/html/modules/fwk_xvf/doc/user_guide/AA_control_command_appendix.html) |

Functional blocks exposed:

- **AEC** (resid 33) — echo canceller, fixed beams, high-pass, silence level
- **AUDIO_MGR** (resid 35) — mic/reference gain, USB output channel routing, system delay
- **PP** (resid 17) — post-processing: noise suppression, AGC, limiter, non-linear echo attenuation
- **GPO/LED** (resid 20) — LED ring + DoA readback
- **APPLICATION** (resid 48) — version, bit depth, save/clear configuration

Because writes are live and instantly reversible from the baseline JSON,
Tier 0 tuning can be done interactively against a running robot with no
service restart.

---

## 3. Tier 0 — free, no new dependencies

### 3.1 The AEC reference feed is off in production ⚠ highest impact

`CJ_AEC_REF_FEED` is **not set** in `supervaise.service`, so
`_RefFeed.enabled()` (`main_voice_robot.py:1267`) defaults to `"0"` and no
reference audio is ever pushed.

The state is worse than simply "off" — it is **inconsistent**:

| Signal | Value | Means |
|---|---|---|
| `~/.cj_ref_feed_on` | present (04:38 today) | `audio-volume` thinks the feed is on |
| XMOS PipeWire sink | `5 [8%] [-55.00dB] [off]` | internal speaker attenuated **and muted** for a feed that never runs |
| `AUDIO_MGR_REF_GAIN` | `8.0` | the *feed-off* value (feed-on writes 1000) |
| `AEC_AECCONVERGED` | `0` | AEC has never locked |
| `AEC_RT60` | `1.4e-45` (denormal) | no reverb estimate — consistent with an idle AEC |

So the attenuation half of the trick is applied while the audio half is not.
Note this also means **switching `audio-out` back to the internal speaker
would currently produce silence** until the level is restored.

**Status: DONE 2026-09-02 07:35.** Calibrated against the route target (C41)
after unmuting the XMOS sink (§3.4), then enabled:

```
lag_ref   123 ms   (112 / 123 / 126, peak/rms 109-114, -12 dBFS)
lag_echo  647 ms   (638 / 647 / 653, peak/rms  14-16,  -33 dBFS)
echo - ref = 524 ms                       (chip AEC tail = 192 ms)
=> CJ_AEC_REF_DELAY_MS=444                (echo lands ~80 ms after the reference)
```

The clean `lag_ref` at −12 dBFS is itself the proof that §3.4 was the
blocker: a muted sink cannot produce a reference-tap measurement at all.

Drop-in now carries `CJ_AEC_REF_FEED=1`, `CJ_AEC_REF_DELAY_MS=444`,
`CJ_AEC_REF_GAIN=1000`; backup at
`wakeword.conf.bak-aecfeed-20260902-073524`.

**C41's 647 ms echo latency is high** for a Bluetooth speaker (150-250 ms is
typical). It fits inside the design — the host delays the reference so the
echo lands 80 ms into the chip's 192 ms tail — but it means the delay is
tightly coupled to this speaker. Re-run `calibrate` after any speaker change.

### 3.1a Verification result — CONVERGED ✅

Verified 2026-09-02 07:43-07:57 by injecting scripted answers through
`/dev/shm/cj_ask_trigger` (`{"q","a","id"}`), which drives the real playback
path with no mic or STT involved — the cleanest way to exercise `_RefFeed`.

**Outcome: `AEC_AECCONVERGED = 1`, stable across repeated reads.** After
weeks reading `0`, the chip's echo canceller is locked.

Chain of evidence:

| Step | Observation |
|---|---|
| `_RefFeed.sync()` fires on first playback | `[aec] reference feed ON — XMOS mixer -55 dB, REF_GAIN 1000, delay 444 ms` |
| Feed engages the chip | `AUDIO_MGR_REF_GAIN` 8 → 1000 |
| Reference actually arrives | channel R tapped to `OP_R = 12,0` during a 28 s answer: **−10 to −20 dBFS**, matching the −16 dBFS the 09-01 notes expected |
| There is echo to cancel | mic beam (L) ~−28 dBFS during playback vs −51 dBFS idle — ~23 dB of echo |
| AEC locks | `AEC_AECCONVERGED` 0 → **1**, stable |

**Convergence is not instant.** It did not assert during the first answer
(28 s) or the second. It was first observed after the **third** playback —
roughly 90 s of cumulative far-end audio. Any verification window shorter
than that will report a false negative, which is what my first three polling
runs did.

Hypotheses eliminated on the way:

| Hypothesis | Test | Result |
|---|---|---|
| Muted XMOS sink | unmute, re-measure | **real blocker** — fixed; reference only arrives once unmuted |
| Reference not reaching the chip | tap `OP_R = 12,0` during playback | disproved — −10 to −20 dBFS present |
| Feed not engaging | watch `REF_GAIN` | disproved — 8 → 1000 on first playback |
| `AEC_FAR_EXTGAIN = −55` double-counting the feed's −55 dB | set to `0`, replay | no immediate change; see caveat below |

**Caveat, untested.** Convergence was first seen during the run that had
`AEC_FAR_EXTGAIN = 0`. I restored it to `−55` afterwards and convergence
**persisted** — but the filter had already adapted by then. Whether `0` was
necessary to converge, or whether it simply needed more cumulative far-end
audio, is **not established**. To settle it: reset the chip (power cycle, or
`CLEAR_CONFIGURATION`) and retry with `−55` held throughout.

`AEC_RT60` still reads denormal (`1.4e-45`) even while converged, so it is
not a useful health signal on this firmware — use `AEC_AECCONVERGED`.

### 3.1b Firmware couples `PP_MGSCALE` to `AUDIO_MGR_REF_GAIN`

After `REF_GAIN` 8 → 1000, `PP_MGSCALE` changed `[1000, 1, 1]` →
`[1000, 1, 1000]` on its own. Nothing in the repo, `~/bin`, `~/tools` or
`~/pi_dashboard` writes it, and the new value is stable across reads. Treat it
like `PP_AGCGAIN`: firmware-derived, so `restore` may fight it.

**Remaining:** `_RefFeed.sync()` is called only from the playback paths
(`main_voice_robot.py` 1573 / 2161 / 2227), so the chip is not configured
until CJ speaks once after a restart. Confirm `AEC_AECCONVERGED` → `1`
*while audio is actually playing* — it reads `0` at idle regardless, so an
idle read proves nothing. Use `./scripts/aec_feed_ctl.sh verify`.

### 3.2 AGC amplifies the room during silence

| Parameter | Current | Problem |
|---|---|---|
| `PP_AGCONOFF` | `1` | on |
| `PP_AGCMAXGAIN` | `64.0` | up to **64×** gain |
| `PP_AGCGAIN` | `7.79` | already sitting at ~7.8× right now |
| `PP_AGCDESIREDLEVEL` | `0.0045` | target level |

With no one speaking, AGC hunts toward the desired level and lifts the room
noise floor into the wake engine. At `CJ_WAKE_OWW_THRESHOLD=0.01` — an
extremely permissive threshold — that is a direct false-wake driver.

**Action:** cap `PP_AGCMAXGAIN` (try `8`–`16`), or disable AGC entirely and
let Whisper handle level. Measure false wakes before/after.

### 3.3 Noise suppression is at its weakest setting

| Parameter | Current | Meaning | Suggested |
|---|---|---|---|
| `PP_MIN_NS` | `0.15` | NS gain floor ≈ **−16 dB** max attenuation | `0.05` (−26 dB) → `0.02` (−34 dB) |
| `PP_MIN_NN` | `0.51` | ≈ **−6 dB** only | lower |
| `PP_ATTNS_MODE` | `0` | speech-absence extra attenuation **disabled** | `1`/`2` |
| `PP_ATTNS_NOMINAL` / `SLOPE` | `1.0` / `1.0` | unshaped | tune after mode is on |
| `AUDIO_MGR_MIC_GAIN` | `90.0` | high | reduce if clipping |

Trade-off: aggressive NS floors can introduce musical noise and eat quiet
speech onsets. Change one parameter at a time and listen via `/maintain`.

### 3.4 The XMOS sink is MUTED — silently defeats the feed ⚠ blocker

`pactl get-sink-mute` on the XMOS sink returns **`yes`**.

`_RefFeed` writes the reference into `pcm cj_ref_feed` → PipeWire → this sink.
A muted sink swallows it: the chip receives nothing, the AEC cannot converge,
and the feed fails **silently** — there is no error path, because `_RefFeed`
is documented to fail open.

Nothing unmutes it. `~/bin/audio-volume` sets *volume* only (`pactl
set-sink-volume`), `~/bin/audio-out` does not touch mute, and
`main_voice_robot.py` has no mute handling — the only mute logic in the
project is the dashboard's **mic** mute, which is unrelated.

This also breaks calibration: `aec_ref_calib.py` measures `lag_ref` by writing
a chirp to `cj_ref_feed`, so a muted sink yields no clean measurement and the
tool exits with *"not enough clean measurements"*. **This is the most likely
reason the 2026-09-01 attempt was parked as "never calibrated."**

`scripts/aec_feed_ctl.sh` now unmutes as a precondition of both `calibrate`
and `enable`, records the mute state in every snapshot, and restores it on
`restore`.

Unmuted 2026-09-02 07:34. WirePlumber persists `"mute":false` for this route
in `~/.local/state/wireplumber/default-routes`, so the fix survives a reboot.

### 3.5 `AEC_FAR_EXTGAIN` — unresolved

Reads `−55.0`, numerically identical to the ALSA PCM attenuation the feed
trick uses. Observed once dropping to `0.0` immediately after
`audio-volume feed-off`, but the transition **could not be reproduced** by
changing the sink volume or by writing `AUDIO_MGR_REF_GAIN`, and no code in
the repo, `~/bin` or `~/tools` writes the parameter. Mechanism unknown.

It currently reads `−55.0` (restored to baseline) while the DAC sits at
0 dB. If this parameter tells the AEC how much external gain is applied to
the far end, a stale value would mis-scale the reference and could block
convergence. **Check it during calibration** — it is the first thing to
suspect if `lag_ref` measures cleanly but the AEC still refuses to converge.

### 3.6 Free wins outside the chip

`openWakeWord` exposes two unused arguments (`openwakeword/model.py:42-43`);
the engine passes neither (`app/wake/engine.py:328`):

- `vad_threshold` — Silero VAD gate. The model is **already downloaded** with
  the feature models (`engine.py:199`), so this costs one argument and cuts
  noise-triggered wakes directly.
- `enable_speex_noise_suppression` — needs `pip install speexdsp-ns`
  (not currently installed). Cheap classic DSP; weaker than §4.1.

---

## 4. Tier 1 — real-time streaming denoisers

**Hard constraint:** CM4, 4 cores, load average **7.40** at time of survey.
Anything above ~0.2 RTF on one core is not viable.

Insertion point for all in-process options: `_MicTap._cb`,
`main_voice_robot.py:1113` — 80 ms / 1280-sample int16 blocks at 16 kHz.

### 4.1 sherpa-onnx `OnlineSpeechDenoiser` — recommended

`sherpa_onnx 1.13.4` is **already in the venv**. It exposes
`OnlineSpeechDenoiser` / `OnlineSpeechDenoiserConfig` (streaming) and
`OfflineSpeechDenoiser`, with **GTCRN** and **DPDFNet** backends, plus
`flush` / `reset` / `frame_shift_in_samples`. Also present:
`SileroVadModelConfig`, `TenVadModelConfig`.

- GTCRN is **16 kHz native** (~24k params) — no 48 kHz resampling round-trip
- The 1280-sample block chunks cleanly to its hop
- No new dependency; only the model file is missing (nothing matching
  `*gtcrn*` on disk — one download from the sherpa-onnx model releases)
- `OfflineSpeechDenoiser` is the **direct swap** for `audio-ui.py:293`

### 4.2 PipeWire `filter-chain` + RNNoise — system-wide, no app change

PipeWire, WirePlumber and a `filter-chain.service` are all running;
`libpipewire-module-filter-chain.so` is present; and
`/usr/share/pipewire/filter-chain/source-rnnoise.conf` ships ready to use.

Blockers: `librnnoise_ladspa.so` is **not installed** and has no apt
candidate (build werman/noise-suppression-for-voice for aarch64). Bigger
blocker: the app captures via ALSA `dsnoop` straight off `hw:CARD=Audio`,
deliberately bypassing PipeWire, and channel R is reserved for the
`/maintain` meter. Adopting this means reworking that arrangement. RNNoise is
48 kHz-only.

### 4.3 PipeWire WebRTC AEC

`/usr/lib/aarch64-linux-gnu/spa-0.2/aec/libspa-aec-webrtc.so` is present.
AEC + NS + AGC at 16 kHz / 10 ms for little CPU. Same routing caveat as §4.2,
and it overlaps with what the XVF3800 should be doing — worth it only if the
chip's AEC cannot be made to converge against a Bluetooth sink.

### 4.4 `webrtc-noise-gain` (Rhasspy)

Prebuilt aarch64 wheels, 10 ms / 16 kHz frames, built for exactly this
satellite use case. Simplest pip-only path. Quality below GTCRN.

### 4.5 Not viable

**DeepFilterNet** (DF2/DF3, including the LADSPA build) — 48 kHz and far too
heavy for a CM4 at load 7.4.

---

## 5. Two insertion points are two different problems

| | Continuous | Per-utterance |
|---|---|---|
| Where | `_MicTap._cb` (`main_voice_robot.py:1113`) | before `transcribe_openai` (`speech_engines.py:534`) |
| Helps | wake accuracy, false wakes | Whisper transcript accuracy |
| Duty cycle | 24/7 — CPU-bound | ~5 s per question |
| Candidates | §4.1, §3.6, §4.4 | anything, incl. heavier models |

The per-utterance slot is the one the ElevenLabs isolator conceptually
occupies today.

---

## 6. Tooling

Two scripts, both in `scripts/`:

| Script | Purpose |
|---|---|
| `xvf_snapshot.py` | `save` / `diff` / `restore` all 59 writable chip params. `restore` writes back **only** what drifted, reports per-parameter failures instead of aborting, and skips `PP_AGCGAIN` (a live AGC meter, not a setting — observed swinging 7.8 → 2.8 between reads). |
| `aec_feed_ctl.sh` | `status`, `snapshot`, `reconcile`, `calibrate`, `enable <ms>`, `disable`, `verify`, `list`, `restore <dir>`. Every mutating command snapshots first. |

Snapshots land in `docs/audio/snapshots/<timestamp>-<tag>/` and capture the
chip params, the systemd drop-in, `~/.asoundrc.route`, the feed flag, the
volume level and the sink mute state.

Round-trip verified 2026-09-02: `PP_MIN_NS` 0.15 → 0.05 → `restore` → 0.15,
`diff` clean.

## 7. Field evidence

From the journal before the service was stopped — the problem this is meant
to fix, in the robot's own logs:

```
[wake] FIRED (streaming, score 0.020)          <- threshold is 0.01
[mic]  noise floor rms=1128 -> speech threshold 1500
[stt]  discarded — transcript echoes the STT prompt
[gate] REJECTED by VAD gate (0.4s < 0.4s)
[lock] released — locked on a noise capture
```

Noise clears the wake threshold, the recorder captures room tone, and Whisper
hallucinates the system prompt back as a transcript.

## 8. Order of work

0. **§3.4** — unmute the XMOS sink. Nothing else in this list can work while
   it is muted. Handled automatically by `aec_feed_ctl.sh calibrate|enable`.
1. **§3.1** — calibrate against the **route target speaker** (currently C41,
   not the Sony — two are connected and the delay is per-speaker), then
   `enable <delay_ms>`; verify `AEC_AECCONVERGED=1` under playback.
2. **§3.2** — cap or disable AGC.
3. **§3.3** — lower `PP_MIN_NS`, enable `PP_ATTNS_MODE`, one at a time.
4. **§3.6** — set `vad_threshold` on the openWakeWord model.
5. **§4.1** — wire sherpa-onnx GTCRN behind a `CJ_DENOISE` env flag matching
   the existing `CJ_*` convention; **measure RTF before** committing it to the
   continuous path.

Steps 1–4 cost nothing, add no dependency, and revert from
`xvf3800_baseline_20260902.json`.

## 9. Revert

```bash
./scripts/aec_feed_ctl.sh list                    # available revert points
./scripts/aec_feed_ctl.sh restore <snapshot-dir>  # chip + drop-in + flag + mute
./scripts/xvf_snapshot.py diff docs/audio/xvf3800_baseline_20260902.json
~/bin/xvf-ctl write PP_MIN_NS 0.15                # or one parameter by hand
```
Chip changes are volatile unless `SAVE_CONFIGURATION` is issued, so a power
cycle is also a full revert — **provided nothing was saved to flash**.
