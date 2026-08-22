"""Voice loop: cloud STT/TTS + fillers + mic meter + storytelling gestures.

Modes:
  (default)  push-to-talk — Enter to speak
  --auto     hands-free, no wake word — answers any speech it hears
  --wake     hands-free with wake word — SLEEP until "Cee-Jap" (WW-5 matcher
             from app/wake_word.py), perk, capture one question, answer,
             back to SLEEP. Wake STT runs on OpenAI whisper-1 (the "local"
             faster-whisper backend is NOT installed on the Pi); windows are
             RMS-gated so silence never triggers an API call.
             STOP WORD (openwakeword backend only): the same phrase spoken
             WHILE the answer plays cuts playback and goes straight back to
             listening — see StopWord / config.STOP_OWW_THRESHOLD.
"""
import argparse, glob, json, os, random, socket, subprocess, sys, tempfile, threading, time
from collections import deque
import numpy as np
import sounddevice as sd
from scipy.io import wavfile
from cj_chat import CorpusArtifacts, cache_savings_summary, make_client, run_turn
import voice_io
from voice_io import transcribe_openai, tts_concatenate_parallel

FILLER_DIR = os.path.expanduser("~/fillers")
# Spoken when CJ_FILLER_MAX fillers play with no composed answer (see FillerLoop).
BAIL_WAV = os.path.expanduser("~/fillers_bail/please_be_specific.wav")
# Spoken (pre-recorded — cloud TTS is unreachable exactly when this fires)
# when the wake word triggers or an API call fails while offline.
NO_NET_WAV = os.path.expanduser("~/fillers_bail/not_connected.wav")
RATE = 16000


def internet_up(timeout=3.0):
    """Cheap reachability probe against the API host the whole pipeline needs."""
    try:
        socket.create_connection(("api.openai.com", 443), timeout=timeout).close()
        return True
    except OSError:
        return False


def say_offline():
    if os.path.exists(NO_NET_WAV):
        subprocess.run(["aplay", "-q", NO_NET_WAV], stderr=subprocess.DEVNULL)
    else:
        print(f"[net] (missing {NO_NET_WAV} — cannot voice the offline notice)")


# Live wake-score feed for the troubleshooting dashboard. tmpfs only — 12.5
# writes/s would wear the SD card anywhere else.
WAKE_LIVE = "/dev/shm/cj_wake_live.json"
WAKE_EVENTS = "/dev/shm/cj_wake_events.jsonl"
# Touched by the dashboard's "Activate listening" button — fires the wake
# state machine without the phrase. Ignored when older than 10 s (stale).
WAKE_TRIGGER = "/dev/shm/cj_wake_trigger"
# Touched by the dashboard's "Enroll voice" button — next wake-loop iteration
# records ~10 s and enrolls it as the reference speaker (speaker_id.py).
ENROLL_TRIGGER = "/dev/shm/cj_enroll_trigger"
ENROLL_PROMPT_WAV = os.path.expanduser("~/fillers_bail/enroll_prompt.wav")
ENROLL_DONE_WAV = os.path.expanduser("~/fillers_bail/enroll_done.wav")
TRANSCRIPT = "/dev/shm/cj_transcript.jsonl"


def _publish_transcript(role, text):
    """Turn-by-turn feed for the dashboard: role is 'user', 'cj', or 'note'."""
    try:
        with open(TRANSCRIPT, "a") as f:
            f.write(json.dumps({"ts": time.time(), "role": role, "text": text}) + "\n")
        if os.path.getsize(TRANSCRIPT) > 40_000:
            lines = open(TRANSCRIPT).read().splitlines()[-40:]
            open(TRANSCRIPT, "w").write("\n".join(lines) + "\n")
    except OSError:
        pass
TURN_META = "/dev/shm/cj_turn_meta.jsonl"
LAST_ANSWER_MP3 = "/dev/shm/cj_last_answer.mp3"
MUTE_TRIGGER = "/dev/shm/cj_mute_trigger"
_speak_timing = {}  # populated by speak(): synth_s, play_s


def prewarm_connections(client):
    """Fire tiny no-token requests at every remote service the turn will hit,
    in daemon threads, the moment the wake word fires. The user is still
    SPEAKING their question, so TLS/HTTP setup happens during the question
    instead of after it — cold-start spikes measured 5-7s to OpenAI on the
    CM4 (STT), and similar first-call costs on Anthropic and ElevenLabs.
    Every branch fails silently; a prewarm must never break a turn.
    Disable with CJ_PREWARM=0."""
    if os.environ.get("CJ_PREWARM", "1").strip().lower() in {"0", "false", "no", "off"}:
        return

    def _openai():
        try:  # STT path uses voice_io._sync_client(); any request warms its pool
            voice_io._sync_client().models.retrieve("whisper-1")
        except Exception as e:
            print(f"[prewarm] openai skipped: {type(e).__name__}")

    def _anthropic():
        try:  # gate/route/composer share this client; GET /v1/models = 0 tokens
            client.models.list(limit=1)
        except Exception as e:
            print(f"[prewarm] anthropic skipped: {type(e).__name__}")

    def _eleven():
        try:
            if getattr(voice_io, "TTS_BACKEND", "openai") != "elevenlabs":
                return
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if root not in sys.path:              # voice/ pkg lives at repo root
                sys.path.insert(0, root)
            import requests                       # dep of voice.speak, present
            import voice.speak                    # noqa: F401 — register module
            mod = sys.modules["voice.speak"]      # voice.speak attr is the FUNCTION
            for attempt in (0, 1):
                try:
                    mod._session.get("https://api.elevenlabs.io/v1/user",
                                     headers={"xi-api-key": mod.config.ELEVEN_API_KEY},
                                     timeout=6)
                    break
                except requests.exceptions.ConnectionError:
                    # After a long idle the pooled keep-alive socket is dead
                    # (server closed it); the retry opens a fresh TLS
                    # connection — which is the warm-up we came for.
                    if attempt:
                        raise
        except Exception as e:
            print(f"[prewarm] elevenlabs skipped: {type(e).__name__}")

    for fn in (_openai, _anthropic, _eleven):
        threading.Thread(target=fn, daemon=True).start()


def _api_cost_snapshot():
    """Cumulative Anthropic $ this service run (cj_chat.api_cost_usd);
    None if unavailable — cost display is best-effort, never turn-breaking."""
    try:
        from cj_chat import api_cost_usd
        return api_cost_usd()
    except Exception:
        return None


def _cost_meta(cost0):
    """Maintenance-feed cost fields: this turn's Anthropic spend (delta from
    the start-of-turn snapshot) + the running session total."""
    now = _api_cost_snapshot()
    if now is None:
        return {}
    return {"cost_usd": (round(now - cost0, 5) if cost0 is not None else None),
            "cost_total_usd": round(now, 4)}


def _fidelity_meta(fid):
    """Maintenance-feed fields from the async fidelity audit (stream_speak);
    empty when the audit didn't run or hadn't landed by turn end."""
    if not fid:
        return {}
    flags = [k for k in ("hallucination", "voice_drift", "guardrail_violation")
             if fid.get(k)]
    return {"fidelity_flags": flags,
            "fidelity_reasoning": fid.get("reasoning", "")[:300]}


def _publish_turn_meta(rec):
    """Per-turn internals feed for the maintenance UI (P2.5). Fail-open."""
    try:
        rec["ts"] = time.time()
        with open(TURN_META, "a") as f:
            f.write(json.dumps(rec) + "\n")
        if os.path.getsize(TURN_META) > 60_000:
            lines = open(TURN_META).read().splitlines()[-40:]
            open(TURN_META, "w").write("\n".join(lines) + "\n")
    except OSError:
        pass


_wake_pub = {"hist": [], "fired_ts": 0.0, "fired_score": 0.0}


def _publish_wake(score, fired=False):
    st = _wake_pub
    st["hist"].append(score)
    del st["hist"][:-13]        # rolling ~1 s of 80 ms frames
    now = time.time()
    if fired:
        st["fired_ts"], st["fired_score"] = now, score
        try:
            with open(WAKE_EVENTS, "a") as f:
                f.write(json.dumps({"ts": now, "score": round(score, 4)}) + "\n")
            if os.path.getsize(WAKE_EVENTS) > 20_000:
                lines = open(WAKE_EVENTS).read().splitlines()[-50:]
                open(WAKE_EVENTS, "w").write("\n".join(lines) + "\n")
        except OSError:
            pass
    try:
        with open(WAKE_LIVE + ".tmp", "w") as f:
            json.dump({"ts": now, "score": round(score, 4),
                       "peak1s": round(max(st["hist"]), 4),
                       "fired_ts": st["fired_ts"],
                       "fired_score": st["fired_score"]}, f)
        os.replace(WAKE_LIVE + ".tmp", WAKE_LIVE)
    except OSError:
        pass

try:
    sd.check_input_settings(device="reachymini_audio_src_plug", samplerate=RATE, channels=1)
    sd.default.device = ("reachymini_audio_src_plug", None)
    print("[mic] using ReSpeaker array")
except Exception as e:
    print(f"[mic] using system default input ({e})")


class Gestures:
    """Background head/antenna motion. Safe no-op if the SDK/daemon is absent."""

    def __init__(self):
        self.mini, self._thread = None, None
        self._stop = threading.Event()
        # Yaw the speaker is at (deg; 0 = straight ahead). Talk-mode motion is
        # anchored here so the robot keeps FACING the person while gesturing.
        self.gaze_yaw = 0.0
        # Emotion of the sentence being spoken (set per sentence by the
        # streaming path): neutral | warm | solemn | emphatic | question.
        # The distinctive accent gesture (nod/bow/tilt) fires ONCE when a new
        # sentence's style arrives, then rate-limited by a cooldown — repeating
        # it every loop cycle read as constant redundant nodding (2026-08-13).
        self._style_new = threading.Event()
        self._last_accent = 0.0
        self.accent_cooldown_s = float(
            os.environ.get("CJ_GESTURE_NOD_COOLDOWN_S", "6"))
        # Idle ("sleep") mode: a distinct "alive" gesture every this many
        # seconds, subtle sway in between (2026-08-13 user request).
        self.idle_gesture_s = float(os.environ.get("CJ_IDLE_GESTURE_S", "10"))
        self._last_idle = 0.0
        self.talk_style = "neutral"
        try:
            from reachy_mini import ReachyMini
            from reachy_mini.utils import create_head_pose
            self._pose = create_head_pose
            self.mini = ReachyMini(media_backend="no_media")
            self.mini.enable_motors(); print("[gestures] connected, motors on")
        except Exception as e:
            print(f"[gestures] disabled ({e})")

    @property
    def talk_style(self):
        return self._talk_style

    @talk_style.setter
    def talk_style(self, value):
        self._talk_style = value
        self._style_new.set()   # new sentence style → one accent gesture allowed

    def _move(self, yaw=0.0, pitch=0.0, roll=0.0, duration=0.6, antennas=None):
        if not self.mini:
            return
        try:
            kw = {"head": self._pose(yaw=yaw, pitch=pitch, roll=roll)}
            if antennas is not None:
                kw["antennas"] = antennas
            try:
                self.mini.goto_target(duration=duration, **kw)
            except TypeError:
                self.mini.goto_target(**kw)
        except Exception:
            pass

    def _run(self, mode):
        while not self._stop.is_set():
            if mode == "listen":      # attentive, nearly still, head slightly raised
                self._move(random.uniform(-6, 6), random.uniform(-12, -4),
                           random.uniform(-3, 3), 0.9)
                self._stop.wait(random.uniform(1.2, 2.2))
            elif mode == "think":     # slow pondering sway, gaze wandering up
                self._move(random.uniform(-25, 25), random.uniform(-18, -6),
                           random.uniform(-8, 8), 1.3)
                self._stop.wait(random.uniform(1.3, 2.4))
            elif mode == "sleep":     # armed idle: sway + periodic "alive" gesture
                if time.monotonic() - self._last_idle >= self.idle_gesture_s:
                    self._last_idle = time.monotonic()
                    pick = random.randrange(4)
                    if pick == 0:      # slow look-around, then back to center
                        self._move(random.uniform(18, 30), random.uniform(-6, 0),
                                   0, 1.4)
                        self._stop.wait(1.0)
                        self._move(random.uniform(-30, -18), random.uniform(-6, 0),
                                   0, 1.8)
                        self._stop.wait(1.0)
                        self._move(0, 0, 0, 1.2)
                    elif pick == 1:    # curious glance up + antenna perk
                        self._move(random.uniform(-8, 8), random.uniform(-16, -10),
                                   random.uniform(-4, 4), 1.0,
                                   antennas=[0.45, -0.45])
                        self._stop.wait(1.2)
                        self._move(0, 0, 0, 1.0, antennas=[0.15, -0.15])
                    elif pick == 2:    # slow stretch up, settle down
                        self._move(0, -14, 0, 1.2, antennas=[0.3, -0.3])
                        self._stop.wait(0.8)
                        self._move(0, 4, 0, 1.4)
                        self._stop.wait(0.5)
                        self._move(0, 0, 0, 0.9)
                    else:              # antenna wiggle, head still
                        for a in (0.4, -0.3, 0.25):
                            self._move(0, 0, 0, 0.25, antennas=[a, -a])
                            self._stop.wait(0.2)
                        self._move(0, 0, 0, 0.4, antennas=[0.15, -0.15])
                    self._stop.wait(random.uniform(1.0, 2.0))
                else:                  # barely-there sway between alive gestures
                    self._move(random.uniform(-4, 4), random.uniform(-2, 3),
                               random.uniform(-2, 2), 1.6)
                    self._stop.wait(random.uniform(2.5, 4.5))
            else:                     # talk: nods + emphasis tilts, gaze LOCKED on the person
                # (2026-08-12) yaw pins to gaze_yaw so the head keeps facing the
                # speaker; expressiveness comes from pitch nods, roll tilts and
                # antenna flicks, shaped by the emotion of the CURRENT sentence
                # (self.talk_style, set per sentence by the streaming path).
                # (2026-08-13) the styled ACCENT plays once per new sentence
                # style and then at most every accent_cooldown_s; in between,
                # only the gentle speaking bob — no more back-to-back nods.
                yaw = self.gaze_yaw + random.uniform(-3.5, 3.5)
                style = self.talk_style
                accent = (self._style_new.is_set()
                          or time.monotonic() - self._last_accent
                          >= self.accent_cooldown_s)
                if accent:
                    self._style_new.clear()
                    self._last_accent = time.monotonic()
                if accent and style == "solemn":  # slow bow, still antennas, long dwell
                    self._move(yaw, random.uniform(8, 14), random.uniform(-2, 2),
                               1.1, antennas=[-0.1, 0.1])
                    self._stop.wait(random.uniform(1.0, 1.6))
                    self._move(self.gaze_yaw, random.uniform(2, 6), 0, 0.9)
                    self._stop.wait(random.uniform(0.6, 1.0))
                elif accent and style == "warm":  # brighter: raised antennas, light bob
                    self._move(yaw, random.uniform(-8, -2), random.uniform(-5, 5),
                               0.45, antennas=[random.uniform(0.15, 0.45),
                                               random.uniform(-0.45, -0.15)])
                    self._stop.wait(random.uniform(0.35, 0.7))
                elif accent and style == "emphatic":  # one firm, deeper nod stroke
                    self._move(yaw, random.uniform(8, 14), random.uniform(-6, 6),
                               0.3, antennas=[random.uniform(-0.35, 0.0),
                                              random.uniform(0.0, 0.35)])
                    self._stop.wait(0.2)
                    self._move(self.gaze_yaw, random.uniform(-5, -1),
                               random.uniform(-3, 3), 0.35)
                    self._stop.wait(random.uniform(0.3, 0.6))
                elif accent and style == "question":  # curious tilt, held
                    self._move(yaw, random.uniform(-8, -3), random.uniform(9, 14),
                               0.6, antennas=[0.35, 0.1])
                    self._stop.wait(random.uniform(0.9, 1.4))
                elif accent and style == "amused":  # playful roll wiggle + antenna flicks
                    self._move(yaw, random.uniform(-6, -2), random.uniform(8, 12),
                               0.3, antennas=[0.4, -0.1])
                    self._stop.wait(0.2)
                    self._move(yaw, random.uniform(-6, -2), random.uniform(-12, -8),
                               0.3, antennas=[-0.1, 0.4])
                    self._stop.wait(0.2)
                    self._move(self.gaze_yaw, random.uniform(-4, 0),
                               random.uniform(-2, 2), 0.4, antennas=[0.25, -0.25])
                    self._stop.wait(random.uniform(0.4, 0.8))
                elif accent and style == "neutral" and random.random() < 0.3:
                    self._move(yaw, random.uniform(6, 12), random.uniform(-4, 4),
                               0.35, antennas=[random.uniform(-0.3, 0.05),
                                               random.uniform(-0.05, 0.3)])
                    self._stop.wait(0.25)
                    self._move(self.gaze_yaw + random.uniform(-2, 2),
                               random.uniform(-4, 0), random.uniform(-3, 3), 0.4)
                    self._stop.wait(random.uniform(0.35, 0.8))
                else:                       # between accents: gentle speaking bob
                    self._move(yaw, random.uniform(-4, 6), random.uniform(-6, 6),
                               0.5, antennas=[random.uniform(-0.2, 0.2),
                                              random.uniform(-0.2, 0.2)])
                    self._stop.wait(random.uniform(0.35, 0.8))

    def start(self, mode):
        self.stop()
        if mode == "talk":
            self.talk_style = "neutral"   # style is per-sentence; reset per answer
        elif mode == "sleep":
            self._last_idle = time.monotonic()   # first alive gesture after N s
        if not self.mini:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, args=(mode,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None

    def neutral(self):
        self.stop()
        self._move(0, 0, 0, 1.0, antennas=[0.15, -0.15])

    def perk(self):
        """Instant wake acknowledgment: antennas up + head raise, ~250ms —
        visible feedback well before the STT confirmation lands."""
        self.stop()
        self._move(0, -12, 0, 0.25, antennas=[0.5, -0.5])

    def scan(self):
        """Boot/arm behavior: a deliberate look-around so bystanders see the
        robot come alive and start listening."""
        self.stop()
        self._move(-30, -8, 0, 0.7); time.sleep(0.8)
        self._move(30, -8, 0, 0.9); time.sleep(1.0)
        self._move(0, -5, 0, 0.6, antennas=[0.3, -0.3])


def record_with_meter(max_s=30, trailing_silence_ms=None, no_speech_timeout_s=12):
    # Silence needed after speech before the mic stops (CJ_MIC_TRAILING_SILENCE_S,
    # default 4s). Longer = tolerant of mid-question pauses, but every answer
    # starts that much later — this wait is part of the response latency.
    if trailing_silence_ms is None:
        trailing_silence_ms = int(float(os.environ.get("CJ_MIC_TRAILING_SILENCE_S", "4")) * 1000)
    frame_ms = 30
    n = int(RATE * frame_ms / 1000)
    frames, speech_seen, silence_run = [], False, 0
    trailing = trailing_silence_ms // frame_ms
    max_frames = int(max_s * 1000 / frame_ms)
    no_speech_frames = int(no_speech_timeout_s * 1000 / frame_ms)
    threshold, probe = None, []
    with sd.InputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=n) as stream:
        print("SPEAK NOW  (auto-stops after you pause)")
        for i in range(max_frames):
            data, _ = stream.read(n)
            mono = data[:, 0]
            frames.append(mono.copy())
            rms = int(np.sqrt(np.mean(mono.astype(np.float64) ** 2)) or 0)
            if threshold is None:
                probe.append(rms)
                if len(probe) >= 8:
                    threshold = min(max(int(np.median(probe) * 3.5), 350), 2000)
                continue
            bars = "#" * min(rms // 100, 40)
            tag = "SPEECH " if rms > threshold else "quiet  "
            print(f"\r  {tag} rms={rms:5d} {bars:<40}", end="", flush=True)
            if rms > threshold:
                speech_seen, silence_run = True, 0
            else:
                silence_run += 1
                if speech_seen and silence_run >= trailing:
                    print("\n[mic] end of speech")
                    break
                if not speech_seen and i > no_speech_frames:
                    print("\n[mic] no speech heard")
                    return None
        else:
            print("\n[mic] 30s cap reached")
    audio = np.concatenate(frames)
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wavfile.write(tmp.name, RATE, audio)
    return tmp.name


# Filler clips played recently — shared ACROSS turns so the same clip does not
# come back within a few questions (user request 2026-08-13). Size = how many
# recent plays to exclude; 12 covers ~3 questions at 4 clips each.
_RECENT_FILLERS = deque(maxlen=int(os.environ.get("CJ_FILLER_NO_REPEAT", "12")))


class FillerLoop:
    """Keep the robot talking while the response composes: play filler clips
    with natural pauses until stop(). stop() never cuts a clip mid-word — it
    waits for the current one to finish, so the answer never talks over it.
    After max_clips plays (CJ_FILLER_MAX, default 4) it stops playing and sets
    `exhausted` — handle_turn treats that as "taking too long, bail out"."""

    def __init__(self, gap_range=(2.5, 5.0), max_clips=None):
        # CJ_FILLERS_ENABLED=0 silences the "let me think" clips so a turn is
        # just question -> answer (A/B: does the pause pass as direct
        # speech?). No clips -> the thread below never starts, so callers'
        # stop()/inject()/exhausted plumbing works unchanged. Note that
        # `exhausted` then never fires — the taking-too-long bail-out is
        # off while fillers are disabled.
        disabled = os.environ.get("CJ_FILLERS_ENABLED", "1").strip().lower() in {
            "0", "false", "no", "off"}
        self._clips = [] if disabled else glob.glob(FILLER_DIR + "/*.wav")
        self._gap_range = gap_range
        self._stop = threading.Event()
        self.max_clips = (max_clips if max_clips is not None
                          else int(os.environ.get("CJ_FILLER_MAX", "4")))
        self.exhausted = threading.Event()
        self._next = None        # P3: one-shot injected clip (dynamic filler)
        self._next_is_tmp = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        if self._clips:
            self._thread.start()

    @staticmethod
    def _duration(path):
        try:
            import wave
            with wave.open(path) as w:
                return w.getnframes() / (w.getframerate() or 1)
        except Exception:
            return 5.0

    def inject(self, wav_path):
        """Queue `wav_path` as the NEXT clip instead of a random canned one
        (P3 dynamic filler). Returns False if the loop is already done —
        caller keeps ownership of the file in that case."""
        if self._stop.is_set() or self.exhausted.is_set():
            return False
        self._next, self._next_is_tmp = wav_path, True
        return True

    def _run(self):
        pool, played = [], 0
        # Dynamic-filler priority, v2 (2026-08-21 — v1's 4s silent hold read
        # as a "big pause", user report): hold only a short natural beat
        # (CJ_FILLER_FIRST_WAIT_S, default 1.2s) for the question-relevant
        # clip, then play the SHORTEST canned clip so there is sound on the
        # air quickly; the dynamic clip injects as the very next slot with a
        # shortened gap after the first clip. Answer landing during the beat
        # still plays nothing at all.
        try:
            first_wait = float(os.environ.get("CJ_FILLER_FIRST_WAIT_S", "1.2"))
        except ValueError:
            first_wait = 1.2
        deadline = time.monotonic() + max(0.0, first_wait)
        while (self._next is None and time.monotonic() < deadline
               and not self._stop.is_set()):
            time.sleep(0.1)
        first = True
        while not self._stop.is_set():
            nxt, self._next = self._next, None
            if nxt is None and not pool:
                # skip clips heard in the last few questions; if that empties
                # the pool (small clip set), fall back to the full set
                pool = ([c for c in self._clips if c not in _RECENT_FILLERS]
                        or self._clips[:])
                random.shuffle(pool)
                if first:   # pop() takes the LAST element -> shortest clip first
                    pool.sort(key=self._duration, reverse=True)
            clip = nxt or pool.pop()
            if not nxt:
                _RECENT_FILLERS.append(clip)
            subprocess.run(["aplay", "-q", clip],
                           stderr=subprocess.DEVNULL)
            if nxt:
                try:
                    os.unlink(nxt)   # injected clips are /dev/shm temps
                except OSError:
                    pass
            played += 1
            if self.max_clips and played >= self.max_clips:
                self.exhausted.set()
                return
            # short gap after the FIRST clip so an injected dynamic clip gets
            # on the air before the answer arrives; normal pacing afterwards
            gap = (0.7, 1.4) if first else self._gap_range
            first = False
            if self._stop.wait(random.uniform(*gap)):
                break

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()
        if self._next:               # injected but never played
            try:
                os.unlink(self._next)
            except OSError:
                pass
            self._next = None


def play_filler():
    return FillerLoop()


class StopWord:
    """The wake detector reused as a barge-in 'stop word': saying the wake
    phrase while the answer plays kills playback. Shares the resident
    openWakeWord model (no second load) but fires on its own, HIGHER threshold
    (config.STOP_OWW_THRESHOLD) — a false stop mid-answer is worse than a
    missed wake, and self-hearing pressure peaks while the speaker plays."""

    def __init__(self, detector, threshold):
        self.detector, self.threshold = detector, float(threshold)


def _play_wav_interruptible(wav_path, stop):
    """aplay `wav_path`; while it plays, score mic frames against the wake
    model and kill playback if the phrase clears stop.threshold. Returns True
    if playback was cut short by the stop word, False if it played out.
    Any listener failure degrades to normal (uninterruptible) playback."""
    proc = subprocess.Popen(["aplay", "-q", wav_path])
    fired = peak = 0.0
    try:
        model = stop.detector._load()
        model.reset()
        frame_len = 1280  # 80 ms at 16 kHz, openWakeWord's expected frame
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                            blocksize=frame_len) as stream:
            while proc.poll() is None:
                if os.path.exists(MUTE_TRIGGER):   # P2.5 operator mute button
                    os.unlink(MUTE_TRIGGER)
                    print("[stop] muted from the maintenance dashboard — answer cut")
                    proc.terminate()
                    fired = -1.0
                    break
                frame, _ = stream.read(frame_len)
                score = float(max(model.predict(frame[:, 0]).values()))
                peak = max(peak, score)
                _publish_wake(score, fired=score >= stop.threshold)
                if score >= stop.threshold:
                    fired = score
                    proc.terminate()
                    break
        model.reset()   # don't leak playback audio into the next arming
        if not fired:   # tuning evidence: what did the mic actually score?
            print(f"[stop] answer played out — peak mid-answer score "
                  f"{peak:.3f} (threshold {stop.threshold})")
    except Exception as e:
        print(f"[stop] barge-in listener failed ({type(e).__name__}: {e}) "
              "— playback continues uninterruptible")
    r = proc.wait()
    if fired:
        print(f"[stop] wake phrase during playback (score {fired:.3f}) — answer cut")
        return True
    if r != 0:
        print("[audio] PLAYBACK FAILED — Bluetooth speaker connected?")
    return False


class StopListener:
    """Answer-spanning barge-in listener for the STREAMING path. The old
    per-sentence `_play_wav_interruptible` re-opened the mic and reset the
    openWakeWord model for EVERY sentence — the model needs ~1-2 s of audio
    context after a reset before scores mean anything, and the gaps between
    sentences were deaf, so a "Cee-Jap" said there was simply missed. This
    holds ONE mic stream + ONE warmed-up model across the whole answer and
    keeps scoring through the inter-sentence gaps."""

    def __init__(self, stop):
        self._stop = stop
        self.fired = 0.0     # score on fire; -1.0 = dashboard mute
        self.peak = 0.0
        self.failed = False
        self._closing = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            model = self._stop.detector._load()
            model.reset()
            try:
                frame_len = 1280  # 80 ms at 16 kHz, openWakeWord's frame
                with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                                    blocksize=frame_len) as stream:
                    while not self._closing.is_set():
                        if os.path.exists(MUTE_TRIGGER):  # P2.5 operator mute
                            os.unlink(MUTE_TRIGGER)
                            print("[stop] muted from the maintenance dashboard "
                                  "— answer cut")
                            self.fired = -1.0
                            return
                        frame, _ = stream.read(frame_len)
                        score = float(max(model.predict(frame[:, 0]).values()))
                        self.peak = max(self.peak, score)
                        _publish_wake(score, fired=score >= self._stop.threshold)
                        if score >= self._stop.threshold:
                            self.fired = score
                            print(f"[stop] wake phrase during playback "
                                  f"(score {score:.3f}) — answer cut")
                            return
            finally:
                model.reset()  # don't leak playback audio into the next arming
        except Exception as e:
            self.failed = True
            print(f"[stop] barge-in listener failed ({type(e).__name__}: {e}) "
                  "— playback continues uninterruptible")

    def close(self):
        self._closing.set()
        self._thread.join(timeout=2.0)
        if not self.fired and not self.failed:
            print(f"[stop] answer played out — peak mid-answer score "
                  f"{self.peak:.3f} (threshold {self._stop.threshold})")


def _play_wav_listener(wav_path, listener):
    """aplay one streamed sentence while the answer-spanning StopListener
    watches the mic. Returns True if the stop word (or dashboard mute) cut
    the answer — including a fire in the gap BEFORE this sentence started."""
    if listener.fired:
        return True
    proc = subprocess.Popen(["aplay", "-q", wav_path])
    while proc.poll() is None:
        if listener.fired:
            proc.terminate()
            break
        time.sleep(0.05)
    r = proc.wait()
    if listener.fired:
        return True
    if r != 0:
        print("[audio] PLAYBACK FAILED — Bluetooth speaker connected?")
    return False


def speak(text, filler=None, stop=None):
    """TTS + play. With a StopWord, playback is interruptible by the wake
    phrase; returns True if it was cut short that way."""
    interrupted = False
    try:  # P0 entity pass on the spoken text (citation exactness); fails open
        from postprocess import process_tts_sentence
        text = process_tts_sentence(text)
    except Exception as e:
        print(f"[postproc] tts pass skipped: {e}")
    _t_synth = time.monotonic()
    mp3_path = wav_from_eleven = None
    if getattr(voice_io, "TTS_BACKEND", "openai") == "elevenlabs":
        try:  # cloned voice; mp3 kept for the dashboard replay button
            wav_from_eleven = voice_io.tts_elevenlabs_wav(text)
            mp3_path = wav_from_eleven.replace(".wav", ".mp3")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet",
                            "-i", wav_from_eleven, mp3_path], check=True)
            with open(mp3_path, "rb") as f:
                mp3 = f.read()
        except Exception as e:
            print(f"[tts] elevenlabs failed ({type(e).__name__}) — openai fallback")
            mp3_path = wav_from_eleven = None
    if mp3_path is None:
        mp3 = tts_concatenate_parallel(text)
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(mp3)
            mp3_path = f.name
    try:  # P2.5: keep the last answer for the dashboard "replay" button
        with open(LAST_ANSWER_MP3, "wb") as f:
            f.write(mp3)
    except OSError:
        pass
    wav_path = mp3_path.replace(".mp3", ".wav")
    try:
        if wav_from_eleven is None:  # elevenlabs path already produced the wav
            subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", mp3_path, wav_path], check=True)
        _speak_timing["synth_s"] = round(time.monotonic() - _t_synth, 2)
        _t_play = time.monotonic()
        if filler is not None:
            filler.stop()  # let the current clip finish, then start the answer
        try:  # live caption feed (audience page); whole answer on this path
            from stream_speak import publish_speaking, publish_sentence_wav
        except Exception:
            publish_speaking = None
        if publish_speaking:
            publish_speaking([text], text, done=False,
                             wav=publish_sentence_wav(wav_path))
        if stop is not None:
            interrupted = _play_wav_interruptible(wav_path, stop)
        else:
            r = subprocess.run(["aplay", "-q", wav_path])
            if r.returncode != 0:
                print("[audio] PLAYBACK FAILED — Bluetooth speaker connected?")
        if publish_speaking:
            publish_speaking([text], None, done=True, interrupted=interrupted)
        _speak_timing["play_s"] = round(time.monotonic() - _t_play, 2)
    finally:
        for p in (mp3_path, wav_path):
            if os.path.exists(p):
                os.unlink(p)
    return interrupted


def _handle_turn_streaming(client, artifacts, gestures, history, stop,
                           question, raw_asr, stt_s):
    """Streaming variant of the compose+speak half of handle_turn: speech
    starts at the FIRST composed sentence (stream_speak.py). Same filler,
    bail-out, offline, history, and stop-word semantics as the classic path."""
    t0 = time.monotonic()
    cost0 = _api_cost_snapshot()
    filler = play_filler()
    try:  # P3: question-relevant filler generated in parallel (fails open)
        import dynamic_filler
        dynamic_filler.start(client, question, filler, note=_publish_transcript)
    except Exception as e:
        print(f"[dynfiller] unavailable ({e})")
    abort, first_audio = threading.Event(), threading.Event()
    result, done = {}, threading.Event()
    listener_box = {}   # holds the answer-spanning StopListener once armed

    def _play(wav):
        listener = listener_box.get("l")
        if listener is not None:
            return _play_wav_listener(wav, listener)
        r = subprocess.run(["aplay", "-q", wav])
        if r.returncode != 0:
            print("[audio] PLAYBACK FAILED — Bluetooth speaker connected?")
        return False

    def _on_first():
        if stop is not None:    # arm BEFORE filler.stop(): the model's ~1-2 s
            listener_box["l"] = StopListener(stop)  # warm-up overlaps the tail
        filler.stop()          # waits for the current clip, then we speak
        gestures.start("talk")
        first_audio.set()
        print(f"[stream] first audio {time.monotonic() - t0:.1f}s after transcript")

    def _style(sentence, emotion):
        gestures.talk_style = emotion
        if emotion != "neutral":
            print(f"[gesture] {emotion}: {sentence[:48]!r}")

    def _worker():
        try:
            import stream_speak
            result["out"] = stream_speak.stream_turn(
                client, artifacts, question, history, play_fn=_play,
                on_first_audio=_on_first, abort=abort, style_fn=_style)
        except Exception as e:
            result["err"] = e
        finally:
            done.set()

    try:    # canned/aborted turns never call build_context — don't show the
        import cj_chat as _cjc     # previous turn's grounding docs for them
        _cjc.LAST_CONTEXT_DOCS[:] = []
    except Exception:
        pass
    threading.Thread(target=_worker, daemon=True).start()
    try:
        while not done.wait(0.25):
            if filler.exhausted.is_set() and not first_audio.is_set():
                abort.set()
                print(f"[filler] {filler.max_clips} fillers played, no speech yet — bailing out")
                _publish_transcript("note", "(no answer in time — asked for a more specific question)")
                gestures.start("talk")
                if os.path.exists(BAIL_WAV):
                    subprocess.run(["aplay", "-q", BAIL_WAV], stderr=subprocess.DEVNULL)
                return True
        if "err" in result:
            if not internet_up():
                print(f"[net] offline during compose ({type(result['err']).__name__}) "
                      "— voicing the offline notice")
                _publish_transcript("note", "(offline during compose — spoke the no-internet notice)")
                filler.stop()
                gestures.start("talk")
                say_offline()
                return True
            raise result["err"]
        out = result.get("out")
        if not out or not out.get("response"):
            return True
        response, routing = out["response"], out["routing"]
        _publish_transcript("cj", response)
        # P0 answer gate notes (streaming): blocked sentences + full-answer audit
        for b in out.get("gate_blocked_sentences") or []:
            _publish_transcript(
                "note", f"(answer gate blocked a sentence pre-TTS: "
                f"{', '.join(t['detail'] for t in b['tripped'])})")
        gf = out.get("gate_full")
        if gf and not gf["ok"]:
            _publish_transcript(
                "note", f"(answer gate full-answer audit tripped: "
                f"{', '.join(t['rule'] for t in gf['tripped'])})")
        fid_flags = _fidelity_meta(out.get("fidelity")).get("fidelity_flags")
        if fid_flags:
            _publish_transcript(
                "note", f"(fidelity audit flagged: {', '.join(fid_flags)} — "
                f"{(out.get('fidelity') or {}).get('reasoning', '')[:120]})")
        try:  # P2.5 maintenance feed
            from cj_chat import (TOKEN_BUDGET_BY_DIM, TOKEN_BUDGET_DIM_DEFAULT,
                                 DYNAMIC_TOKENS_ENABLED, COMPOSER_MAX_TOKENS,
                                 LAST_CONTEXT_DOCS, _scale_budget)
            topic = (routing or {}).get("primary_topic")
            theme = artifacts.topics.get(topic, {}).get("theme_anchor", "")
            # keys are TOPICS since the 2026-08-20 refactor (theme was stale here)
            budget = _scale_budget(
                int(TOKEN_BUDGET_BY_DIM.get(topic, TOKEN_BUDGET_DIM_DEFAULT))
                if DYNAMIC_TOKENS_ENABLED else int(COMPOSER_MAX_TOKENS))
            _publish_turn_meta({
                "phase": "composed", "raw_asr": raw_asr, "question": question,
                "answer": response, "topic": topic, "theme": theme,
                "confidence": (routing or {}).get("confidence"),
                "token_budget": budget, "dynamic_tokens": DYNAMIC_TOKENS_ENABLED,
                "stt_s": stt_s, "compose_s": out.get("compose_s"),
                "docs": list(LAST_CONTEXT_DOCS),
                "streamed": True, "first_audio_s": out.get("first_audio_s"),
                **_cost_meta(cost0), **_fidelity_meta(out.get("fidelity")),
            })
            _publish_turn_meta({
                "phase": "spoken", "question": question,
                "synth_s": out.get("first_audio_s"), "play_s": None,
                "interrupted": bool(out.get("interrupted")),
            })
        except Exception as e:
            print(f"[meta] publish skipped: {e}")
        history += [{"role": "user", "content": question},
                    {"role": "assistant", "content": response}]
        del history[:-20]
        if out.get("interrupted"):
            _publish_transcript("note", "(answer interrupted by wake phrase — listening)")
            return "interrupted"
        return True
    finally:
        filler.stop()
        listener = listener_box.get("l")
        if listener is not None:
            listener.close()


_ACK_DIR = os.path.expanduser("~/fillers_ack")


def _play_ack():
    """Instant acknowledgment the moment the mic CLOSES — a sub-second 'Ah.'/
    'Hmm.' in the cloned voice, launched non-blocking BEFORE transcription
    starts. First sound lands ~1s after the user stops talking instead of
    after the 2.5-3.5s STT wait (user report: pause still very noticeable).
    The clip ends well before any filler or canned answer starts. Disable
    with CJ_ACK_ENABLED=0."""
    if os.environ.get("CJ_ACK_ENABLED", "1").strip().lower() in {
            "0", "false", "no", "off"}:
        return
    clips = glob.glob(_ACK_DIR + "/*.wav")
    if clips:
        subprocess.Popen(["aplay", "-q", random.choice(clips)],
                         stderr=subprocess.DEVNULL)


def _followup_window():
    """Seconds the mic stays open for a follow-up question after a completed
    answer (no fresh wake needed). 0 disables the conversational window."""
    try:
        return max(0.0, float(os.environ.get("CJ_FOLLOWUP_WINDOW_S", "6")))
    except ValueError:
        return 6.0


def handle_turn(client, artifacts, gestures, history, stop=None, followup=False):
    """Capture ONE question from the mic and answer it. Mutates `history` in
    place. Returns True if a full turn ran, False on mic timeout / empty STT,
    or "interrupted" (truthy) when the stop word cut the answer — the caller
    should go straight back to listening without requiring a fresh wake.
    followup=True shortens the no-speech timeout to the follow-up window, so
    silence hands control back to the caller quickly."""
    gestures.start("listen")
    path = record_with_meter(
        no_speech_timeout_s=(_followup_window() if followup else 12))
    if not path:
        _publish_transcript("note", "(mic timeout — no speech captured)")
        return False
    _play_ack()   # sub-second "Ah."/"Hmm." NOW — sound before the STT wait
    try:
        import speaker_id
        if speaker_id.gate_active():
            ok, sim = speaker_id.verify(path)
            if not ok:
                print(f"[speaker] ignored — similarity {sim:.2f} < "
                      f"{speaker_id.threshold():.2f}")
                _publish_transcript(
                    "note", f"(ignored — voice does not match enrolled speaker, "
                            f"similarity {sim:.2f})")
                os.unlink(path)
                return False
            print(f"[speaker] enrolled speaker confirmed (similarity {sim:.2f})")
    except Exception as e:   # never let the gate break the robot
        print(f"[speaker] check failed ({type(e).__name__}: {e}) — letting turn through")
    gestures.start("think")
    print("[stt] transcribing...")
    t0 = time.monotonic()
    try:
        # Pin the language: whisper auto-detect hallucinates random-language
        # text on quiet/unclear windows (Ukrainian "thanks for watching",
        # Portuguese fragments — journal 2026-08-03 16:10-16:12). Set
        # CJ_STT_LANGUAGE= (empty) to restore auto-detect, or "tl" for Filipino.
        lang = os.environ.get("CJ_STT_LANGUAGE", "en").strip() or None
        question = transcribe_openai(path, language=lang)
    except Exception as e:
        if internet_up():
            raise
        print(f"[net] offline during STT ({type(e).__name__}) — voicing the offline notice")
        _publish_transcript("note", "(offline — spoke the no-internet notice)")
        gestures.start("talk")
        say_offline()
        return True
    finally:
        os.unlink(path)
    if not question.strip():
        print("[stt] empty transcript")
        _publish_transcript("note", "(empty transcript — STT heard nothing)")
        return False
    non_latin = sum(ord(c) > 127 for c in question) / len(question)
    if non_latin > 0.3:   # EN/Filipino are Latin-script; this is a hallucination
        print(f"[stt] discarded non-Latin hallucination: {question!r}")
        _publish_transcript("note", f"(discarded non-Latin hallucination: {question})")
        return False
    stt_s = round(time.monotonic() - t0, 2)
    print(f"[stt] heard: \"{question}\"  ({stt_s:.1f}s)")
    raw_asr = question
    try:  # P0 entity correction on the transcript (fails open; DARK unless enabled)
        from postprocess import process_transcript
        corrected = process_transcript(question)
        if corrected != question:
            print(f"[postproc] corrected: \"{corrected}\"")
            _publish_transcript("note", f"(raw ASR: {question})")
            question = corrected
    except Exception as e:
        print(f"[postproc] transcript pass skipped: {e}")
    _publish_transcript("user", question)
    try:  # canned fast path: curated answers for common questions (fails open)
        import canned_answers
        hit = canned_answers.match(question)
    except Exception as e:
        print(f"[canned] unavailable ({e})")
        hit = None
    if hit:
        # No router, no composer, zero tokens — the clip cache makes repeats
        # play near-instantly. speak() still runs the entity TTS pass,
        # captions, and stop-word interruptible playback.
        print(f"[canned] fast path hit: {hit['id']}")
        _publish_transcript("note", f"(canned answer: {hit['id']})")
        response = hit["answer"]
        t0 = time.monotonic()
        gestures.start("talk")
        interrupted = speak(response, None, stop=stop)
        _publish_transcript("cj", response)
        _publish_turn_meta({
            "phase": "composed", "raw_asr": raw_asr, "question": question,
            "answer": response, "topic": f"canned:{hit['id']}", "theme": "",
            "confidence": "canned", "token_budget": 0, "dynamic_tokens": False,
            "stt_s": stt_s, "compose_s": 0.0,
            "cost_usd": 0.0, "cost_total_usd": _cost_meta(None).get("cost_total_usd"),
        })
        _publish_turn_meta({
            "phase": "spoken", "question": question,
            "synth_s": round(time.monotonic() - t0, 2), "play_s": None,
            "interrupted": bool(interrupted),
        })
        history += [{"role": "user", "content": question},
                    {"role": "assistant", "content": response}]
        del history[:-20]
        if interrupted:
            _publish_transcript("note", "(answer interrupted by wake phrase — listening)")
            return "interrupted"
        return True
    if os.environ.get("CJ_STREAM_SPEECH", "").strip().lower() in {"1", "true", "yes", "on"}:
        return _handle_turn_streaming(client, artifacts, gestures, history, stop,
                                      question, raw_asr, stt_s)
    t0 = time.monotonic()
    cost0 = _api_cost_snapshot()
    filler = play_filler()
    try:  # P3: question-relevant filler generated in parallel (fails open)
        import dynamic_filler
        dynamic_filler.start(client, question, filler, note=_publish_transcript)
    except Exception as e:
        print(f"[dynfiller] unavailable ({e})")
    result, done = {}, threading.Event()

    def _compose():
        try:
            result["turn"] = run_turn(client, artifacts, None, question_text=question,
                                      conversation_history=history, skip_audio=True)
        except Exception as e:
            result["err"] = e
        finally:
            done.set()

    threading.Thread(target=_compose, daemon=True).start()
    try:
        while not done.wait(0.25):
            if filler.exhausted.is_set():
                # 4 fillers played and still no answer — give up on this turn.
                # The abandoned compose thread finishes in the background; its
                # result is discarded and never enters history.
                print(f"[filler] {filler.max_clips} fillers played, no answer yet — bailing out")
                _publish_transcript("note", "(no answer in time — asked for a more specific question)")
                gestures.start("talk")
                if os.path.exists(BAIL_WAV):
                    subprocess.run(["aplay", "-q", BAIL_WAV], stderr=subprocess.DEVNULL)
                else:
                    print(f'[filler] (missing {BAIL_WAV} — cannot voice "Please be more specific")')
                return True
        if "err" in result:
            if not internet_up():
                print(f"[net] offline during compose ({type(result['err']).__name__}) "
                      "— voicing the offline notice")
                _publish_transcript("note", "(offline during compose — spoke the no-internet notice)")
                filler.stop()
                gestures.start("talk")
                say_offline()
                return True
            raise result["err"]
        q, response, routing = result["turn"]
        # P0 answer gate (classic path): the FULL answer exists before any TTS
        # here, so a tripped answer is fully blocked — the safe in-persona
        # fallback is spoken instead. Zero LLM calls, ~0.15 ms; fails open.
        try:
            import config as _cfg
            if response and getattr(_cfg, "ANSWER_GATE_ENABLED", False):
                import answer_gate
                _topics = [t for t in [(routing or {}).get("primary_topic")]
                           + list((routing or {}).get("secondary_topics") or []) if t]
                _g = answer_gate.check_answer(question, response, topic_ids=_topics)
                if not _g["ok"]:
                    print(f"[answer-gate] answer BLOCKED pre-TTS: "
                          f"{[t['rule'] for t in _g['tripped']]}")
                    _publish_transcript(
                        "note", f"(answer gate blocked the draft: "
                        f"{', '.join(t['rule'] for t in _g['tripped'])} — spoke fallback)")
                    from cj_chat import SAFE_OOC_FALLBACK
                    response = SAFE_OOC_FALLBACK
        except Exception as _e:
            print(f"[answer-gate] fail-open: {type(_e).__name__}")
        if q and response:
            gestures.start("talk")
            compose_s = round(time.monotonic() - t0, 2)
            print(f"[tts] speaking...  (compose {compose_s:.1f}s)")
            _publish_transcript("cj", response)
            try:  # P2.5 maintenance feed: routing + budget + stage latency
                from cj_chat import (TOKEN_BUDGET_BY_DIM, TOKEN_BUDGET_DIM_DEFAULT,
                                     DYNAMIC_TOKENS_ENABLED, COMPOSER_MAX_TOKENS,
                                     LAST_CONTEXT_DOCS, _scale_budget)
                topic = (routing or {}).get("primary_topic")
                theme = artifacts.topics.get(topic, {}).get("theme_anchor", "")
                budget = _scale_budget(
                    int(TOKEN_BUDGET_BY_DIM.get(topic, TOKEN_BUDGET_DIM_DEFAULT))
                    if DYNAMIC_TOKENS_ENABLED else int(COMPOSER_MAX_TOKENS))
                _publish_turn_meta({
                    "phase": "composed", "raw_asr": raw_asr, "question": question,
                    "answer": response, "topic": topic, "theme": theme,
                    "confidence": (routing or {}).get("confidence"),
                    "token_budget": budget, "dynamic_tokens": DYNAMIC_TOKENS_ENABLED,
                    "stt_s": stt_s, "compose_s": compose_s,
                    "docs": list(LAST_CONTEXT_DOCS),
                    **_cost_meta(cost0),
                })
            except Exception as e:
                print(f"[meta] publish skipped: {e}")
            interrupted = speak(response, filler, stop=stop)  # filler talks through TTS synth too
            try:
                _publish_turn_meta({
                    "phase": "spoken", "question": question,
                    "synth_s": _speak_timing.get("synth_s"),
                    "play_s": _speak_timing.get("play_s"),
                    "interrupted": bool(interrupted),
                })
            except Exception as e:
                print(f"[meta] publish skipped: {e}")
            history += [{"role": "user", "content": q},
                        {"role": "assistant", "content": response}]
            del history[:-20]
            if interrupted:
                _publish_transcript("note", "(answer interrupted by wake phrase — listening)")
                return "interrupted"
    finally:
        filler.stop()
    return True


def _wake_windows():
    """MicAudioSource windows, RMS-gated: a window only reaches STT when its
    level clears an adaptive floor (2.5x the 25th percentile of recent windows,
    min 350) — silence costs $0 and no network round-trip. The floor is taken
    from PREVIOUS windows only, so the first shout after arming still passes."""
    from collections import deque
    import wake_word
    hist = deque(maxlen=20)
    for path in wake_word.MicAudioSource().windows():
        try:
            _, data = wavfile.read(path)
        except Exception:
            continue
        rms = int(np.sqrt(np.mean(data.astype(np.float64) ** 2)) or 0)
        floor = max(350, 2.5 * float(np.percentile(hist, 25))) if hist else 350
        hist.append(rms)
        if rms >= floor:
            yield path


def _wake_stream(det):
    """Continuous streaming wake detection for the openWakeWord backend: feed
    80 ms frames straight to the model, which keeps its own rolling audio
    buffer. No window boundaries and no dropped audio between windows — the
    chunked path could split the phrase across two windows (the "say it twice"
    failure). Blocks until the score clears det.threshold; returns the score."""
    model = det._load()
    model.reset()
    frame_len = 1280  # 80 ms at 16 kHz — openWakeWord's expected frame
    near_miss_last = 0.0
    with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                        blocksize=frame_len) as stream:
        while True:
            for trig, ret in ((WAKE_TRIGGER, 1.0), (ENROLL_TRIGGER, -1.0)):
                if os.path.exists(trig):
                    try:
                        fresh = (time.time() - os.path.getmtime(trig)) < 10
                        os.unlink(trig)
                    except OSError:
                        fresh = False
                    if fresh:
                        print(f"[wake] dashboard trigger: "
                              f"{'enroll' if ret < 0 else 'listen'}")
                        if ret > 0:
                            _publish_wake(1.0, fired=True)
                        model.reset()
                        return ret
            frame, _ = stream.read(frame_len)
            score = float(max(model.predict(frame[:, 0]).values()))
            if score >= det.threshold:
                _publish_wake(score, fired=True)
                model.reset()   # clear the rolling buffer for the next arming
                return score
            _publish_wake(score)
            if score >= 0.15 and (time.monotonic() - near_miss_last) > 2.0:
                near_miss_last = time.monotonic()
                print(f"[wake] below threshold (score {score:.3f})")


def _run_enrollment(gestures):
    """Record ~10 s from the robot mic and save it as the reference speaker."""
    import speaker_id
    gestures.perk()
    if os.path.exists(ENROLL_PROMPT_WAV):
        subprocess.run(["aplay", "-q", ENROLL_PROMPT_WAV], stderr=subprocess.DEVNULL)
    print("[speaker] enrollment: speak for ~10 s")
    gestures.start("listen")
    path = record_with_meter(max_s=15, no_speech_timeout_s=10)
    if not path:
        print("[speaker] enrollment: no speech captured")
        _publish_transcript("note", "(enrollment failed — no speech captured, try again)")
        gestures.neutral()
        return
    try:
        speaker_id.enroll(path)
        print("[speaker] enrolled — speaker gate is ON")
        _publish_transcript("note", "(voice enrolled — speaker gate is now ON)")
        if os.path.exists(ENROLL_DONE_WAV):
            gestures.start("talk")
            subprocess.run(["aplay", "-q", ENROLL_DONE_WAV], stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"[speaker] enrollment error: {e}")
        _publish_transcript("note", f"(enrollment error: {e})")
    finally:
        os.unlink(path)
        gestures.neutral()


def wake_loop(client, artifacts, gestures):
    """SLEEP -> "Cee-Jap" -> perk -> one question -> answer -> SLEEP.
    Wake windows are pulled ONLY in the sleep state, so the robot cannot wake
    on its own filler/answer audio; a grace pause after each turn covers the
    speaker tail before the mic re-arms (kiosk state-machine behavior).
    Exception: while the ANSWER plays, the mic listens for the same phrase as
    a STOP word at a stricter threshold (StopWord) — a fire cuts playback and
    loops straight back into listening, no fresh wake required."""
    import wake_word    # inserts the repo root on sys.path, where config lives
    import config
    import voice_io
    detector = wake_word.make_detector()        # config.WAKE_BACKEND picks the backend
    # Post-answer pause before re-arming. The answer has fully played by then,
    # so this only needs to cover speaker/room tail — near-zero re-arms instantly.
    grace = max(0.0, float(getattr(config, "WAKE_COOLDOWN_S", 1.0)))
    phrase = getattr(config, "WAKE_PHRASE", "Cee-Jap")
    history = []
    if isinstance(detector, wake_word.OpenWakeWordDetector):
        backend_desc = f"openwakeword ({os.path.basename(detector.model_path)}, " \
                       f"threshold {detector.threshold})"
        detector._load()    # pre-warm so "armed" means the model is resident
        print("[wake] openWakeWord model resident — idle listening is on-device, no network")

        def _on_listen(r):  # near-misses only; the model scores every gated window
            if r.score >= 0.15:
                print(f"[wake] below threshold (score {r.score})")
    else:
        backend_desc = f"stt: {detector.backend}"
        if detector.backend == "local":
            try:            # pre-warm so "armed" means the model is resident
                voice_io._local_whisper()
                print("[wake] local STT resident — idle listening is on-device, no network")
            except Exception as e:
                print(f"[wake] local model preload failed ({e}) — will fall back to whisper-1")

        def _on_listen(r):
            if r.heard.strip() and r.heard != "<stt-error>":
                print(f"[wake] not the phrase: {r.heard!r}")
    gestures.scan()         # visible look-around: the robot is awake and listening
    print(f"[wake] armed — say \"{phrase}\"  (backend: {backend_desc})")
    streaming = isinstance(detector, wake_word.OpenWakeWordDetector)
    stop = None
    if streaming and bool(getattr(config, "STOP_WORD_ENABLED", True)):
        stop = StopWord(detector, getattr(config, "STOP_OWW_THRESHOLD", 0.4))
        print(f"[stop] stop word armed — \"{phrase}\" mid-answer cuts playback "
              f"(threshold {stop.threshold})")
    while True:
        gestures.start("sleep")
        if streaming:
            score = _wake_stream(detector)
            if score < 0:
                _run_enrollment(gestures)
                continue
            print(f"[wake] FIRED (streaming, score {score:.3f})")
        else:
            res = wake_word.wait_for_wake(
                detector, windows=_wake_windows(), on_listen=_on_listen)
            print(f"[wake] FIRED on {res.variant!r} (score {res.score}, heard: {res.heard!r})")
        prewarm_connections(client)   # warm OpenAI/Anthropic/ElevenLabs while the user speaks
        gestures.perk()
        if not internet_up(1.2):   # short probe: don't hold the mic open on a slow LAN
            # Say so instead of recording a question no cloud call can answer.
            print("[net] offline at wake — voicing the offline notice")
            gestures.start("talk")
            say_offline()
            gestures.neutral()
            time.sleep(grace)
            print(f"[wake] re-armed — say \"{phrase}\"")
            continue
        r = handle_turn(client, artifacts, gestures, history, stop=stop)
        while True:
            # Stop word fired mid-answer: just stop and go back to SLEEP — the
            # next question needs a fresh wake (user decision 2026-08-20;
            # CJ_STOP_RELISTEN=1 restores the old Alexa-style instant re-listen).
            if r == "interrupted" and os.environ.get("CJ_STOP_RELISTEN", "0") == "1":
                gestures.perk()
                print("[stop] listening for the next question (no wake needed)")
                r = handle_turn(client, artifacts, gestures, history, stop=stop)
                continue
            # Conversational follow-up (2026-08-21): after a COMPLETED answer
            # the mic re-opens for CJ_FOLLOWUP_WINDOW_S so the visitor can just
            # keep talking. Silence closes the window -> back to sleep.
            if r is True and _followup_window() > 0:
                time.sleep(grace)       # speaker/room tail before the mic re-arms
                gestures.perk()
                print(f"[followup] listening {_followup_window():.0f}s for a "
                      f"follow-up (no wake needed)")
                _publish_transcript("note", "(listening for a follow-up — no wake needed)")
                r = handle_turn(client, artifacts, gestures, history, stop=stop,
                                followup=True)
                continue
            break
        if r == "interrupted":
            print(f"[stop] answer stopped — back to sleep, say \"{phrase}\" to ask again")
        gestures.neutral()
        time.sleep(grace)           # self-hearing grace before re-arming
        print(f"[wake] re-armed — say \"{phrase}\"")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--auto", action="store_true", help="hands-free, no wake word")
    ap.add_argument("--wake", action="store_true",
                    help='hands-free behind the "Cee-Jap" wake phrase')
    args = ap.parse_args()

    print("Loading artifacts...")
    artifacts = CorpusArtifacts()
    print(f"  ok: {len(artifacts.topics)} topics loaded")
    client = make_client()
    gestures = Gestures()
    gestures.neutral()
    print("Ready.\n")

    history = []
    try:
        if args.wake:
            wake_loop(client, artifacts, gestures)
        else:
            while True:
                if not args.auto:
                    input("Press Enter to speak...")
                handle_turn(client, artifacts, gestures, history)
                gestures.neutral()
    except KeyboardInterrupt:
        gestures.neutral()
        print("\n" + cache_savings_summary())
        print("Goodbye. Maraming salamat po.")


if __name__ == "__main__":
    main()
