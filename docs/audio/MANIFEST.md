# docs/audio/ — MANIFEST

Audio-path analysis for the Reachy Mini: the XVF3800 DSP, the capture
and playback topology, ambient-noise reduction, and the plan to replace
the paid ElevenLabs Voice Isolator with a local real-time denoiser.

| ID | File | Description |
|---|---|---|
| 0001 | [ambient-noise-reduction-2026-09-02.md](ambient-noise-reduction-2026-09-02.md) | Measured signal topology, XVF3800 configurability, Tier 0 chip tuning (AEC reference feed, AGC, noise suppression) and Tier 1 real-time denoiser candidates. |
| 0002 | [xvf3800_baseline_20260902.json](xvf3800_baseline_20260902.json) | All 59 writable XVF3800 parameters as read on 2026-09-02, before any change. The revert baseline for Tier 0 work. |
| 0003 | `snapshots/<ts>-<tag>/` | Revert points written by `scripts/aec_feed_ctl.sh`. Each holds `chip.json` (all writable params), `wakeword.conf` (the systemd drop-in), `asoundrc.route`, and `state.json` (feed flag, volume, sink mute, service state). Accumulates one directory per mutating command — prune freely, they are independent. |

## Tooling

| Script | Purpose |
|---|---|
| [`scripts/xvf_snapshot.py`](../../scripts/xvf_snapshot.py) | `save` / `diff` / `restore` every writable chip parameter. Restores only what drifted. |
| [`scripts/aec_feed_ctl.sh`](../../scripts/aec_feed_ctl.sh) | Reversible AEC reference-feed bring-up: `status`, `snapshot`, `reconcile`, `calibrate`, `enable`, `disable`, `verify`, `list`, `restore`. |

## Key facts

- The Reachy Mini Audio card **is** the XVF3800 DSP: one USB card carrying
  both playback and capture.
- The chip's AEC far-end reference is whatever the host plays into it over
  USB. Playback currently goes to a **Bluetooth** speaker via BlueALSA, so
  the chip has no reference and cannot cancel the robot's own voice.
- All 59 writable parameters are live-tunable over USB via `~/bin/xvf-ctl`,
  take effect without a restart, and are volatile unless
  `SAVE_CONFIGURATION` is issued.
- The SDK pushes **no** default config at boot, so app-level tuning is not
  overwritten by the daemon.
- The XMOS PipeWire sink is **muted**, and nothing in the project ever unmutes
  it. The reference feed and its calibration both write into that sink, so
  both fail silently until it is unmuted.
- Two Bluetooth speakers are connected simultaneously (C41 = route target,
  Sony ULT FIELD 1 = kept alive by `speaker-watchdog`). The AEC delay is
  per-speaker; calibrate against the route target.
