> **2026-08-29:** this package now only does synthesis (`voice.speak.synthesize`, `effective_settings`, `SynthError`, `voice.cache`, `voice.audio`). Playback / espeak / fallback clips were removed; the robot app plays audio itself.

# voice/ — Reachy Mini cloned-voice output

Speaks through an ElevenLabs cloned voice, post-EQ'd for the robot's
5W @ 4Ω driver, with a local clip cache and an offline fallback ladder so a
TTS failure never leaves the robot silent (and never raises into your
control loop).

```python
import voice

voice.init(mini=my_reachy_mini)      # share your already-open handle
ok = voice.speak("Magandang umaga!") # True = cloned voice played
```

> **SDK note:** `reachy_mini` 1.9.0 has no `mini.speaker.play_audio()`.
> Playback goes through `mini.media` (`start_playing()` +
> `push_audio_sample()` at the robot's output rate — 16 kHz stereo on
> current firmware). `speak.py` handles the resample/interleave.

## Setup order

1. **Dependencies** (Python ≥ 3.11):
   ```bash
   pip install requests numpy scipy soundfile
   pip install sounddevice        # only needed for HARDWARE = "lite" / host playback
   sudo apt install espeak-ng     # last-resort offline voice
   ```
2. **Config** — copy the template and fill in the two credentials at the top:
   ```bash
   cp voice/config.example.py voice/config.py
   ```
   `voice/config.py` is gitignored; the API key must never be committed,
   logged, or embedded in an exception message. `ELEVEN_API_KEY` is read
   from the environment first, the file value is only a fallback.
3. **Sanity check** — importing `voice` raises immediately, with a pointer
   to where each credential comes from, if either is still empty.
4. **Fallback clips** (once, online):
   ```bash
   python -m voice.fallback.generate_fallback_clips
   ```
5. **Warm the cache** with your demo's stock lines:
   ```python
   import voice
   voice.prerender([
       "Welcome! Ask me anything.",
       "Thank you for coming today.",
   ])
   ```

## How it works

- `speak(text, blocking=True)` normalizes the text, hashes
  `text + voice_id + model_id + voice_settings` (SHA256) and checks
  `~/.voice_cache/`. Misses go to the ElevenLabs API (`pcm_24000`), through
  the EQ chain (high-pass 180 Hz → +3 dB presence at 3 kHz → −16 LUFS
  loudness normalization, all in-process scipy), into the cache, then out
  the speaker. Changing any voice setting invalidates cleanly.
- Cache is LRU-evicted above `CACHE_MAX_MB` (500 MB default).
- **Failure ladder:** network/timeout/5xx retries `MAX_RETRIES`× with
  exponential backoff → 401 logs "key invalid or lacks text_to_speech
  scope" (no retry) → 429 logs remaining-quota headers (no retry) → plays a
  matching clip from `voice/fallback/` → espeak-ng → logs and stays silent.
  `speak()` returns `False` on any fallback, `True` when the cloned voice
  actually played.
- `voice.rms_envelope(pcm, sr, hop_ms=20)` returns a 0–1 envelope for
  driving antenna motion later (no motor wiring here).

## Moving the key out of config.py (systemd)

Put the key in an environment file readable only by the service user:

```ini
# /etc/reachy/voice.env        (chmod 600, chown pollen:)
ELEVEN_API_KEY=sk_...
```

```ini
# /etc/systemd/system/my-robot-app.service
[Unit]
Description=Robot conversation app with cloned voice
After=network-online.target sound.target

[Service]
User=pollen
EnvironmentFile=/etc/reachy/voice.env
Environment=XDG_RUNTIME_DIR=/run/user/1000
WorkingDirectory=/home/pollen/my-robot-app
ExecStart=/home/pollen/my-robot-app/.venv/bin/python main.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then blank `ELEVEN_API_KEY` in `voice/config.py` — the environment value
wins, no code change needed.
