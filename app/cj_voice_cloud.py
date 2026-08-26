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
import argparse, contextlib, glob, json, math, os, queue, random, re, socket, subprocess, sys, tempfile, threading, time
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
# Stop-word (barge-in) scores get their OWN meter on /maintain (2026-08-26,
# user: "add stop meter beside wake meter") — they used to be pushed into the
# wake meter, which muddled both.
STOP_LIVE = "/dev/shm/cj_stop_live.json"
STOP_EVENTS = "/dev/shm/cj_stop_events.jsonl"
# Touched by the dashboard's "Activate listening" button — fires the wake
# state machine without the phrase. Ignored when older than 10 s (stale).
WAKE_TRIGGER = "/dev/shm/cj_wake_trigger"
# Touched by the dashboard's "Enroll voice" button — next wake-loop iteration
# records ~10 s and enrolls it as the reference speaker (speaker_id.py).
ENROLL_TRIGGER = "/dev/shm/cj_enroll_trigger"
# Written by the /event page's question buttons (JSON {"q","a","id"}): the
# next wake-loop iteration speaks the scripted answer as if the question had
# been asked aloud — no mic, no STT, no composer. 30 s freshness so a tap
# while an answer is still playing queues the next question instead of dying.
ASK_TRIGGER = "/dev/shm/cj_ask_trigger"
_net_probe = {}   # wake-time reachability probe, filled by a daemon thread
_pending_ask = {"ask": None}   # handoff from _wake_stream to wake_loop

# Voice lock (see speaker_id.VoiceLock): one instance for the process.
_voice_lock = {"lock": None}
FAREWELL_TEXT = "Thank you for the conversation. Goodbye, and God bless."
APOLOGY_TEXT = ("I am sorry. I cannot reach my notes at the moment. "
                "Please ask me again in a little while.")


def _say_apology(err):
    """Composer/API failure while ONLINE (e.g. Anthropic credit exhausted,
    auth error): say so in his voice and carry on — never crash the service
    (2026-08-24: a 400 'credit balance too low' killed the process on every
    follow-up, and systemd's 30 s restart read as 'slow')."""
    msg = str(err)
    short = msg[:160]
    print(f"[compose] API error — apologising and continuing: {type(err).__name__}: {short}")
    _publish_transcript("note", f"(API error during compose — {type(err).__name__}: {short})")
    try:
        speak(APOLOGY_TEXT, None)
    except Exception:
        try:
            subprocess.run(["aplay", "-q", NO_NET_WAV], stderr=subprocess.DEVNULL)
        except Exception:
            pass
_FAREWELL_RE = re.compile(
    r"^(?:ok(?:ay)?|alright|well|so)?[\s,.!]*"
    r"(?:thank(?:s| you)(?: so much| very much| sir| po)?[\s,.!]*)?"
    r"(?:(?:good)?bye(?: bye)?(?: now)?|see you(?: later| soon)?|"
    r"that(?:'s| is| was) all|i(?:'m| am) done|paalam|salamat(?: po)?|"
    r"good ?night|good day|take care)"
    r"(?:[\s,.!]*(?:sir|po|chief|justice|cjap|cee-jap|for now))*[\s,.!]*$",
    re.I)
_THANKS_RE = re.compile(
    r"^(?:ok(?:ay)?[\s,.!]*)?(?:thank(?:s| you)(?: so much| very much| sir| po)?)[\s,.!]*$",
    re.I)


def _is_farewell(text):
    """True when the (locked) speaker is closing the conversation."""
    t = (text or "").strip()
    return bool(_FAREWELL_RE.match(t) or _THANKS_RE.match(t))


def _lock_enabled():
    try:
        import speaker_id
        return speaker_id.lock_enabled()
    except Exception:
        return False


def _voice_lock_obj():
    if _voice_lock["lock"] is None:
        import speaker_id
        _voice_lock["lock"] = speaker_id.VoiceLock()
    return _voice_lock["lock"]


def _warm_voice_lock():
    """Load the speaker-embedding model while the visitor is still speaking
    (first load ~1 s) so the lock costs nothing on the turn itself."""
    try:
        if _lock_enabled():
            import speaker_id
            speaker_id._load()
    except Exception as e:
        print(f"[lock] model warm-up failed ({type(e).__name__}: {e})")
ENROLL_PROMPT_WAV = os.path.expanduser("~/fillers_bail/enroll_prompt.wav")
ENROLL_DONE_WAV = os.path.expanduser("~/fillers_bail/enroll_done.wav")
TRANSCRIPT = "/dev/shm/cj_transcript.jsonl"


def _stage(step=None, state=None, detail=None, reset=False, extra=None):
    """Audience-page pipeline tracker (stream_speak.publish_stage; fails open)."""
    try:
        from stream_speak import publish_stage
        publish_stage(step, state, detail, reset=reset, extra=extra)
    except Exception:
        pass


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
# Persistent mute (2026-08-25, /maintain Mute/Unmute): while this flag exists
# the robot cuts any playback, ignores the wake word and event buttons, and
# leaves a voice-locked conversation. Unmute = the dashboard removes the flag.
MUTED_FLAG = "/dev/shm/cj_muted"


def _muted():
    return os.path.exists(MUTED_FLAG)
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


def _wpm_meta(words, audio_s):
    """Speaking-rate fields (2026-08-25, user: "word per minute in the
    maintain UI"): words actually voiced / seconds of answer audio."""
    try:
        if words and audio_s and audio_s > 0:
            return {"words": int(words), "audio_s": round(float(audio_s), 2),
                    "wpm": int(round(60.0 * words / audio_s))}
    except (TypeError, ValueError):
        pass
    return {"words": words or None, "audio_s": audio_s or None, "wpm": None}


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


_stop_pub = {"hist": [], "fired_ts": 0.0, "fired_score": 0.0}


def _publish_stop(score, fired=False):
    """Same shape as _publish_wake, for the barge-in listener while the answer
    plays: /dev/shm/cj_stop_live.json (300 ms meter) + cj_stop_events.jsonl."""
    st = _stop_pub
    st["hist"].append(score)
    del st["hist"][:-13]
    now = time.time()
    if fired:
        st["fired_ts"], st["fired_score"] = now, score
        try:
            with open(STOP_EVENTS, "a") as f:
                f.write(json.dumps({"ts": now, "score": round(score, 4)}) + "\n")
            if os.path.getsize(STOP_EVENTS) > 20_000:
                lines = open(STOP_EVENTS).read().splitlines()[-50:]
                open(STOP_EVENTS, "w").write("\n".join(lines) + "\n")
        except OSError:
            pass
    try:
        with open(STOP_LIVE + ".tmp", "w") as f:
            json.dump({"ts": now, "score": round(score, 4),
                       "peak1s": round(max(st["hist"]), 4),
                       "fired_ts": st["fired_ts"],
                       "fired_score": st["fired_score"]}, f)
        os.replace(STOP_LIVE + ".tmp", STOP_LIVE)
    except OSError:
        pass

try:
    sd.check_input_settings(device="reachymini_audio_src_plug", samplerate=RATE, channels=1)
    sd.default.device = ("reachymini_audio_src_plug", None)
    print("[mic] using ReSpeaker array")
except Exception as e:
    print(f"[mic] using system default input ({e})")


class _SpeakerDoA:
    """Where the person speaking is, from the XVF3800 mic array's direction-of-
    arrival (2026-08-25, user: "turn to the person speaking"). A daemon thread
    polls the ReSpeaker USB control endpoint at 10 Hz (safe alongside the
    daemon's own handle — measured) and keeps a smoothed angle of the latest
    SPEECH-flagged readings. SDK convention: 0 rad = left, pi/2 = front,
    pi = right -> head yaw = 90 - angle (CJ_DOA_FLIP=1 mirrors it if the
    head turns the wrong way). Off with CJ_FACE_SPEAKER=0."""

    def __init__(self):
        self.on = os.environ.get("CJ_FACE_SPEAKER", "1").strip().lower() not in {
            "0", "false", "no", "off"}
        self.flip = os.environ.get("CJ_DOA_FLIP", "0").strip() == "1"
        try:
            self.max_yaw = float(os.environ.get("CJ_FACE_MAX_YAW", "").strip() or 45)
        except ValueError:
            self.max_yaw = 45.0
        self.angle, self.ts = None, 0.0
        self._doa, self._started = None, False

    def start(self):
        if not self.on or self._started:
            return
        self._started = True
        try:
            from reachy_mini.media.audio_doa import AudioDoA
            self._doa = AudioDoA()
            if self._doa._respeaker is None:
                raise RuntimeError("no ReSpeaker USB device")
        except Exception as e:
            print(f"[doa] speaker tracking disabled ({e})")
            self.on = False
            return
        threading.Thread(target=self._run, daemon=True).start()
        print(f"[doa] speaker tracking on (max yaw ±{self.max_yaw:.0f}°"
              f"{', mirrored' if self.flip else ''})")

    def _run(self):
        while True:
            try:
                r = self._doa.get_DoA()
                if r is not None and r[1]:            # speech-flagged reading
                    deg = math.degrees(r[0])
                    if self.angle is None or abs(deg - self.angle) > 40:
                        self.angle = deg               # new speaker: jump
                    else:
                        self.angle = 0.7 * self.angle + 0.3 * deg
                    self.ts = time.monotonic()
            except Exception:
                pass
            time.sleep(0.1)

    def yaw(self, max_age=1.5):
        """Head yaw (deg, + = left) toward the latest speech, or None."""
        if not self.on or self.angle is None or time.monotonic() - self.ts > max_age:
            return None
        y = 90.0 - self.angle
        if self.flip:
            y = -y
        return max(-self.max_yaw, min(self.max_yaw, y))


_speaker_doa = _SpeakerDoA()


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
        if self.mini:
            _speaker_doa.start()

    def face_speaker(self, max_age=1.5, min_change=8.0):
        """Point gaze_yaw at the latest speech direction; True if it moved."""
        y = _speaker_doa.yaw(max_age)
        if y is None or abs(y - self.gaze_yaw) < min_change:
            return False
        self.gaze_yaw = y
        return True

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

    def _run(self, mode, gen=None):
        # goto_target blocks for its duration (up to ~1.8 s) while stop() joins
        # for 1.5 s: a previous loop can still be inside _move when the next
        # start() clears _stop. The generation token ends it (2026-08-25 review).
        while not self._stop.is_set() and (gen is None or gen == getattr(self, "_gen", gen)):
            if mode == "listen":      # attentive, head turned to whoever is speaking
                moved = self.face_speaker(max_age=1.0)
                self._move(self.gaze_yaw + random.uniform(-4, 4), random.uniform(-12, -4),
                           random.uniform(-3, 3), 0.5 if moved else 0.9)
                self._stop.wait(random.uniform(0.5, 0.9) if moved else random.uniform(1.0, 1.8))
            elif mode == "think":     # slow pondering sway around the speaker, gaze up
                self._move(self.gaze_yaw + random.uniform(-20, 20), random.uniform(-18, -6),
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
        self._gen = getattr(self, "_gen", 0) + 1   # orphaned loops see a stale gen and exit
        self._thread = threading.Thread(target=self._run, args=(mode, self._gen), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.5)
            self._thread = None

    def neutral(self):
        self.stop()
        self.gaze_yaw = 0.0
        self._move(0, 0, 0, 1.0, antennas=[0.15, -0.15])

    def perk(self):
        """Instant wake acknowledgment: antennas up + head raise, ~250ms —
        visible feedback well before the STT confirmation lands. Turns toward
        the voice that woke it when the mic array knows where it came from."""
        self.stop()
        if self.face_speaker(max_age=2.5, min_change=5.0):
            print(f"[doa] speaker at {_speaker_doa.angle:.0f}° -> facing yaw {self.gaze_yaw:+.0f}°")
        self._move(self.gaze_yaw, -12, 0, 0.3, antennas=[0.5, -0.5])

    def scan(self):
        """Boot/arm behavior: a deliberate look-around so bystanders see the
        robot come alive and start listening."""
        self.stop()
        self._move(-30, -8, 0, 0.7); time.sleep(0.8)
        self._move(30, -8, 0, 0.9); time.sleep(1.0)
        self._move(0, -5, 0, 0.6, antennas=[0.3, -0.3])


class _MicTap:
    """One always-open capture stream shared by the wake detector and the
    question recorder (2026-08-25, user: "a bit late in listening"). Frames
    land in a queue from the audio callback, so the ~0.3 s between the wake
    word firing and the recorder starting is buffered as pre-roll instead of
    lost — the question's first syllable used to fall in that gap. The mic is
    a dsnoop device, so the stop-word listeners still open their own streams.
    Also tracks the idle noise floor (30th percentile of recent frame RMS) so
    the recorder can set its speech threshold without probing the pre-roll."""
    FRAME = 1280   # 80 ms at 16 kHz

    MAXQ = 7500    # ~10 min of frames; older audio is dropped rather than hoarded

    def __init__(self):
        self.q = queue.Queue()
        self._rem = None
        self.rms_hist = deque(maxlen=60)   # ~4.8 s
        self.stream = sd.InputStream(samplerate=RATE, channels=1, dtype="int16",
                                     blocksize=self.FRAME, callback=self._cb)
        self.stream.start()

    def _cb(self, indata, frames, t, status):
        if self.q.qsize() > self.MAXQ:
            try:
                self.q.get_nowait()
            except queue.Empty:
                pass
        self.q.put(indata[:, 0].copy())

    def read(self, n):
        parts, have = [], 0
        if self._rem is not None and len(self._rem):
            parts.append(self._rem); have = len(self._rem)
        self._rem = None
        while have < n:
            try:
                a = self.q.get(timeout=2.0)
            except queue.Empty:
                # No frames for 2 s: the USB mic went away / PortAudio stopped
                # the callback. Raise (as the per-open stream.read() used to)
                # so the caller's error path and systemd restart take over
                # instead of hanging silently (2026-08-25 review).
                if not self.stream.active:
                    raise sd.PortAudioError("mic stream stopped")
                continue
            parts.append(a); have += len(a)
        buf = np.concatenate(parts)
        self._rem = buf[n:]
        return buf[:n].reshape(-1, 1), False

    def note_rms(self, frame):
        self.rms_hist.append(float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)) or 0.0))

    def noise_rms(self):
        return int(np.percentile(self.rms_hist, 30)) if len(self.rms_hist) >= 12 else None

    def buffered_s(self):
        return (self.q.qsize() * self.FRAME +
                (len(self._rem) if self._rem is not None else 0)) / RATE

    def flush(self):
        self._rem = None
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                return


_mic_tap_box = {}


def _mic_tap():
    tap = _mic_tap_box.get("tap")
    if tap is None or not tap.stream.active:
        if tap is not None:
            try:
                tap.stream.close()
            except Exception:
                pass
        tap = _MicTap()
        _mic_tap_box["tap"] = tap
    return tap


def _env_num(name, default):
    """Numeric env knob; a blank or malformed value falls back to the default
    instead of taking down every turn (2026-08-25 review)."""
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        print(f"[mic] ignoring bad {name}={os.environ.get(name)!r}, using {default}")
        return float(default)


def _speech_threshold(noise_rms):
    """RMS above which a 30 ms frame counts as speech (CJ_MIC_RMS_* knobs;
    lower floor/multiplier = more sensitive mic)."""
    floor_ = int(_env_num("CJ_MIC_RMS_FLOOR", 350))
    mult = _env_num("CJ_MIC_RMS_MULT", 3.5)
    cap = int(_env_num("CJ_MIC_RMS_CAP", 2000))
    return min(max(int(noise_rms * mult), floor_), cap)


def _min_speech_frames(frame_ms):
    """Frames above threshold needed before a recording counts as 'speech
    started' (CJ_MIC_MIN_SPEECH_MS, default 240). Added 2026-08-26: half of
    the 'did not hear me' turns that day were false starts — a knock, the
    perk motor or a speaker tail tripped ONE frame, the 1 s trailing-silence
    rule then closed the mic and STT got a silent clip (4-5 s wasted, prompt
    echo discarded). 0 restores the single-frame trigger."""
    return max(0, int(_env_num("CJ_MIC_MIN_SPEECH_MS", 240) // frame_ms))


_bt_route_cache = {"mtime": None, "bt": False}


def _bt_route():
    """True when ~/bin/audio-out has playback on a Bluetooth speaker (route
    file says bluealsa). Cached by mtime — read per turn, not per frame."""
    path = os.path.expanduser("~/.asoundrc.route")
    try:
        m = os.path.getmtime(path)
        if m != _bt_route_cache["mtime"]:
            with open(path) as f:
                _bt_route_cache["bt"] = "bluealsa" in f.read()
            _bt_route_cache["mtime"] = m
    except OSError:
        _bt_route_cache["bt"] = False
    return _bt_route_cache["bt"]


class _StopTrace:
    """Stop-word diagnostics (2026-08-25, user: "it does not stop when saying
    cjap"): keeps the mic audio the listener scored (<= 40 s) and the top
    scores with offsets; written to /dev/shm/cj_stop_last.wav + the journal
    when the answer ends. Off unless CJ_STOP_DEBUG_WAV=1."""
    PATH = "/dev/shm/cj_stop_last.wav"

    def __init__(self):
        self.on = os.environ.get("CJ_STOP_DEBUG_WAV", "0").strip().lower() in {
            "1", "true", "yes", "on"}
        self.frames, self.scores, self.n = [], [], 0

    def add(self, frame, score):
        if not self.on:
            return
        if self.n < 40 * RATE:
            self.frames.append(np.asarray(frame, dtype=np.int16).copy())
        self.scores.append((score, self.n / RATE))
        self.n += len(frame)

    def dump(self):
        if not self.on or not self.frames:
            return
        try:
            wavfile.write(self.PATH, RATE, np.concatenate(self.frames))
            top = sorted(self.scores, reverse=True)[:3]
            print("[stop] trace: top scores " +
                  " ".join(f"{sc:.3f}@{t:.1f}s" for sc, t in top) +
                  f" — mic audio saved to {self.PATH}")
        except Exception as e:
            print(f"[stop] trace failed ({type(e).__name__})")


def record_with_meter(max_s=30, trailing_silence_ms=None, no_speech_timeout_s=12,
                      keep_buffer=False):
    # Silence needed after speech before the mic stops (CJ_MIC_TRAILING_SILENCE_S,
    # default 4s). Longer = tolerant of mid-question pauses, but every answer
    # starts that much later — this wait is part of the response latency.
    if trailing_silence_ms is None:
        trailing_silence_ms = int(float(os.environ.get("CJ_MIC_TRAILING_SILENCE_S", "4")) * 1000)
    frame_ms = 30
    n = int(RATE * frame_ms / 1000)
    frames, speech_seen, silence_run = [], False, 0
    trailing = trailing_silence_ms // frame_ms
    min_speech, speech_run = _min_speech_frames(frame_ms), 0
    max_frames = int(max_s * 1000 / frame_ms)
    no_speech_frames = int(no_speech_timeout_s * 1000 / frame_ms)
    threshold, probe = None, []
    stream = _mic_tap()
    kept = 0.0
    if keep_buffer and stream.buffered_s() > 3.0:
        # Nobody drained the tap for seconds (press-Enter / --auto / stop-
        # relisten callers, or a stalled turn): that is not a wake gap but
        # the robot's own answer — drop it (2026-08-25 review).
        stream.flush()
    if keep_buffer:                      # right after a wake: the gap audio is the question's start
        kept = stream.buffered_s()
        noise = stream.noise_rms()       # idle floor from BEFORE the wake phrase
        if noise is not None:
            threshold = _speech_threshold(noise)
            print(f"[mic] noise floor rms={noise} -> speech threshold {threshold}")
    else:
        stream.flush()                   # follow-up / enrollment: drop stale audio
        # Bluetooth speakers lag 200-400 ms behind aplay: right after an answer
        # the noise-floor probe would otherwise sample the speaker's tail and
        # set the speech threshold too high for the first words (2026-08-26).
        # No echo cancellation on BT either, so let it ring out. CJ_BT_SETTLE_S.
        settle = _env_num("CJ_BT_SETTLE_S", 0.4)
        if settle > 0 and _bt_route():
            time.sleep(settle)
            stream.flush()
    # The pre-roll holds the wake phrase's tail (and the perk motor) followed
    # by the user's pause: keep that audio, but only start speech/silence
    # detection in its last 300 ms — otherwise the phrase counts as speech and
    # the pause ends the recording before the question begins (seen 12:08).
    # ...but never skip more than ~1 s: pre-rolls of 2 s were measured, and a
    # short question spoken entirely inside a long pre-roll must still be
    # seen as speech (2026-08-25 review).
    skip_detect = min(max(0, int(kept * RATE / n) - 10), int(1.0 * RATE / n))
    with contextlib.nullcontext(stream):
        print("SPEAK NOW  (auto-stops after you pause)" +
              (f"  [+{kept:.2f}s pre-roll]" if kept else ""))
        for i in range(max_frames):
            data, _ = stream.read(n)
            mono = data[:, 0]
            frames.append(mono.copy())
            if i < skip_detect:
                continue
            rms = int(np.sqrt(np.mean(mono.astype(np.float64) ** 2)) or 0)
            if threshold is None:
                probe.append(rms)
                if len(probe) >= 8:
                    threshold = _speech_threshold(int(np.median(probe)))
                    print(f"[mic] noise floor rms={int(np.median(probe))} -> speech threshold {threshold}")
                continue
            bars = "#" * min(rms // 100, 40)
            tag = "SPEECH " if rms > threshold else "quiet  "
            print(f"\r  {tag} rms={rms:5d} {bars:<40}", end="", flush=True)
            if rms > threshold:
                speech_run += 1
                if speech_run >= min_speech:   # sustained, not a one-frame blip
                    speech_seen = True
                silence_run = 0
            else:
                silence_run += 1
                if not speech_seen:
                    speech_run = 0
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
            # once announced to the avatar the clip is "current": play it
            # even if stop() lands during the head-start hold (stop() never
            # cuts a current clip — same rule, applied from the announce)
            _play_aside(clip)
            if nxt:
                for p in (nxt, nxt + ".align.json"):   # injected clips are /dev/shm temps
                    try:
                        os.unlink(p)
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
            for p in (self._next, self._next + ".align.json"):
                try:
                    os.unlink(p)
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
    trace = _StopTrace()
    try:
        model = stop.detector._load()
        model.reset()
        frame_len = 1280  # 80 ms at 16 kHz, openWakeWord's expected frame
        with sd.InputStream(samplerate=16000, channels=1, dtype="int16",
                            blocksize=frame_len) as stream:
            while proc.poll() is None:
                if os.path.exists(MUTE_TRIGGER) or _muted():   # P2.5 operator mute button
                    if os.path.exists(MUTE_TRIGGER):
                        os.unlink(MUTE_TRIGGER)
                    print("[stop] muted from the maintenance dashboard — answer cut")
                    proc.terminate()
                    fired = -1.0
                    break
                frame, _ = stream.read(frame_len)
                score = float(max(model.predict(frame[:, 0]).values()))
                trace.add(frame[:, 0], score)
                peak = max(peak, score)
                _publish_stop(score, fired=score >= stop.threshold)
                if score >= stop.threshold:
                    fired = score
                    proc.terminate()
                    break
        model.reset()   # don't leak playback audio into the next arming
        trace.dump()
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
        self._trace = _StopTrace()
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
                        if os.path.exists(MUTE_TRIGGER) or _muted():  # P2.5 operator mute
                            if os.path.exists(MUTE_TRIGGER):
                                os.unlink(MUTE_TRIGGER)
                            print("[stop] muted from the maintenance dashboard "
                                  "— answer cut")
                            self.fired = -1.0
                            return
                        frame, _ = stream.read(frame_len)
                        score = float(max(model.predict(frame[:, 0]).values()))
                        self._trace.add(frame[:, 0], score)
                        self.peak = max(self.peak, score)
                        _publish_stop(score, fired=score >= self._stop.threshold)
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
        self._trace.dump()
        if not self.fired and not self.failed:
            print(f"[stop] answer played out — peak mid-answer score "
                  f"{self.peak:.3f} (threshold {self._stop.threshold})")


AVATAR_AUDIO_FLAG = "/dev/shm/cj_avatar_audio"
AVATAR_LAG_FILE = "/dev/shm/cj_avatar_lag"


def _avatar_mode():
    """None (robot voice), "solo" (avatar only), or "sync" (both voices,
    robot delayed to coincide with the avatar's measured start lag)."""
    try:
        if time.time() - os.path.getmtime(AVATAR_AUDIO_FLAG) > 15:
            return None   # page stopped heart-beating: it is gone
        with open(AVATAR_AUDIO_FLAG) as f:
            return f.read().strip() or "solo"
    except OSError:
        return None


def _avatar_lag():
    """Avatar start lag in seconds: the /face-avatar page measures the real
    publish→speak_started delay and reports it here; env default fallback."""
    try:
        return max(0.0, min(4.0, float(open(AVATAR_LAG_FILE).read())))
    except (OSError, ValueError):
        return float(os.environ.get("CJ_AVATAR_LAG_S", "0.8"))


def _avatar_head_start(prefed_age=None):
    """Seconds the robot holds before a sentence so the avatar's mouth and
    the robot's audio coincide. A sentence the page has NOT seen yet needs
    the full measured idle-start lag (fetch + upload + HeyGen start). One the
    page already queued `prefed_age` s ago (see SentenceSpeaker._prefeed)
    only needs the remainder of the much shorter queued-start latency."""
    if prefed_age is None:
        return _avatar_lag()
    try:
        q = float(os.environ.get("CJ_AVATAR_QUEUE_LAG_S", "0.4"))
    except ValueError:
        q = 0.4
    return max(0.0, min(_avatar_lag(), q) - prefed_age)


def _mark_play_start():
    try:
        from stream_speak import mark_play_start
        mark_play_start()
    except Exception:
        pass


def _asides_enabled():
    return os.environ.get("CJ_AVATAR_ASIDES", "1").strip().lower() not in {
        "0", "false", "no", "off"}


def _play_aside(clip, stop=None):
    """Play a non-answer clip (ack / filler). With the avatar page live the
    clip is mirrored to it (cj_aside.json) and, in "sync" mode, the robot
    holds the measured lag so both mouths move together; in "solo" mode the
    robot stays silent for the clip's length. `stop` (Event) cuts the hold."""
    mode = _avatar_mode()
    if mode and _asides_enabled():
        try:
            from stream_speak import publish_aside, wav_duration
            publish_aside(clip)
        except Exception:
            mode = None
    if mode and _asides_enabled():
        hold = _avatar_lag()
        if mode == "solo":
            hold += wav_duration(clip) or 1.0
        end = time.monotonic() + hold
        while time.monotonic() < end:
            if stop is not None and stop.is_set():
                return
            time.sleep(0.05)
        if mode == "solo":
            return
    subprocess.run(["aplay", "-q", clip], stderr=subprocess.DEVNULL)


def _load_wav_mono_int16(path):
    rate, a = wavfile.read(path)
    if a.dtype != np.int16:
        raise ValueError(f"unsupported wav dtype {a.dtype}")
    if a.ndim > 1:
        a = a.mean(axis=1).astype(np.int16)
    return int(rate), np.ascontiguousarray(a)


def _trim_edges(a, rate, thr_dbfs=-42.0):
    """Strip the TTS clip's baked-in leading silence and normalise its trailing
    silence to CJ_SENT_GAP_MS (default 150) so every sentence boundary is the
    same short pause; 5 ms fades keep the cut click-free. Clips measured
    2026-08-26: lead 0-80 ms, trail 180-290 ms."""
    gap = int(rate * _env_num("CJ_SENT_GAP_MS", 150) / 1000)
    if len(a) < rate // 10:
        return a
    win = max(1, int(rate * 0.01))
    x = a.astype(np.float32)
    env = np.sqrt(np.convolve(x * x, np.ones(win, dtype=np.float32) / win, mode="same"))
    idx = np.flatnonzero(env > 32768 * 10 ** (thr_dbfs / 20))
    if not len(idx):
        return a
    start = max(0, int(idx[0]) - int(rate * 0.02))
    end = int(idx[-1]) + gap
    out = a[start:min(len(a), end)]
    if end > len(a):
        out = np.concatenate([out, np.zeros(end - len(a), dtype=np.int16)])
    else:
        out = out.copy()
    f = min(len(out) // 2, int(rate * 0.005))
    if f > 0:
        ramp = np.linspace(0.0, 1.0, f, dtype=np.float32)
        out[:f] = (out[:f] * ramp).astype(np.int16)
        out[-f:] = (out[-f:] * ramp[::-1]).astype(np.int16)
    return out


class _SentenceOut:
    """Streamed-sentence player (2026-08-26, user: "make the transition between
    sentences smoother"). ONE PortAudio output stream stays open for the whole
    answer and each sentence's samples are written into it, so a sentence
    boundary no longer pays an aplay spawn + ALSA/PipeWire re-open (150-400 ms,
    worse on Bluetooth) on top of the clip's own trailing silence. A keep-alive
    thread feeds silence whenever no sentence is being written (next sentence
    still synthesising) so the device never underruns. Device: ALSA
    "audio_out_route" — the same pcm aplay's default resolves to, so it follows
    ~/bin/audio-out (internal / Sony / Marshall). Measured gapless on the Pi
    through both PipeWire and BlueALSA. Any failure falls back to aplay for
    that sentence; CJ_SENTENCE_PLAYER=aplay restores the old path outright."""
    CHUNK_S = 0.05

    def __init__(self):
        self.stream, self.rate = None, None
        self.lock = threading.Lock()
        self._alive = None
        self._last_write = 0.0

    @staticmethod
    def enabled():
        return os.environ.get("CJ_SENTENCE_PLAYER", "stream").strip().lower() != "aplay"

    def _open(self, rate):
        if self.stream is not None and self.rate == rate:
            return self.stream
        self.close()
        st = sd.OutputStream(device="audio_out_route", samplerate=rate, channels=1,
                             dtype="int16", blocksize=int(rate * self.CHUNK_S),
                             latency=_env_num("CJ_SENT_OUT_LATENCY_S", 0.15))
        st.start()
        self.stream, self.rate = st, rate
        self._last_write = time.monotonic()
        self._alive = threading.Thread(target=self._keepalive, args=(st,), daemon=True)
        self._alive.start()
        return st

    def _keepalive(self, st):
        zeros = np.zeros(int(self.rate * self.CHUNK_S), dtype=np.int16)
        while self.stream is st:
            with self.lock:
                if self.stream is st and time.monotonic() - self._last_write > self.CHUNK_S:
                    try:
                        st.write(zeros)
                        self._last_write = time.monotonic()
                    except Exception:
                        pass
            time.sleep(self.CHUNK_S / 2)

    def _release(self, abort):
        with self.lock:
            st, self.stream = self.stream, None
        if st is not None:
            try:
                (st.abort if abort else st.stop)()
                st.close()
            except Exception:
                pass

    def close(self):    # answer finished: let the tail drain, then release
        self._release(abort=False)

    def abort(self):    # stop word / mute: drop what is buffered now
        self._release(abort=True)

    def play(self, wav_path, listener, trim=True):
        """True if the listener cut it, False when written out. Raises on
        device trouble — the caller then falls back to aplay."""
        rate, a = _load_wav_mono_int16(wav_path)
        if trim:
            a = _trim_edges(a, rate)
        st = self._open(rate)
        n = int(rate * self.CHUNK_S)
        for k in range(0, len(a), n):
            if listener.fired:
                self.abort()
                return True
            with self.lock:
                st.write(a[k:k + n])
                self._last_write = time.monotonic()
        return False


_SENT_OUT = _SentenceOut()


def _play_wav_listener(wav_path, listener, prefed_age=None):
    """aplay one streamed sentence while the answer-spanning StopListener
    watches the mic. Returns True if the stop word (or dashboard mute) cut
    the answer — including a fire in the gap BEFORE this sentence started."""
    if listener.fired:
        return True
    mode = _avatar_mode()
    if mode:
        # The avatar speaks this audio too: hold so its mouth and our audio
        # start together (every sentence — the old first-sentence-only hold
        # let the avatar slip a full lag further behind on each boundary).
        end = time.monotonic() + _avatar_head_start(prefed_age)
        while time.monotonic() < end:
            if listener.fired:
                return True
            time.sleep(0.05)
    _mark_play_start()
    if mode == "solo":
        # avatar is the only voice: silent hold for the sentence's duration
        from stream_speak import wav_duration
        end = time.monotonic() + (wav_duration(wav_path) or 2.0)
        while time.monotonic() < end:
            if listener.fired:
                return True
            time.sleep(0.1)
        return False
    if _SENT_OUT.enabled():
        try:
            # avatar "sync" mode plays the untrimmed wav on the page too: keep
            # our timing identical to it, so no edge trim there
            return _SENT_OUT.play(wav_path, listener, trim=not mode)
        except Exception as e:
            _SENT_OUT.abort()
            print(f"[audio] stream player failed ({type(e).__name__}: {e}) "
                  "— aplay for this sentence")
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


def speak(text, filler=None, stop=None, voice_settings=None):
    """TTS + play. With a StopWord, playback is interruptible by the wake
    phrase; returns True if it was cut short that way.
    voice_settings: ElevenLabs voice_settings override for expressive
    deliveries (voice_io.farewell_settings()); None = default voice."""
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
            wav_from_eleven = voice_io.tts_elevenlabs_wav(
                text, voice_settings=voice_settings)
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
        try:  # speaking-rate fields for the maintenance page
            from stream_speak import wav_duration as _wd
            _speak_timing["audio_s"] = _wd(wav_path)
            _speak_timing["words"] = len(text.split())
        except Exception:
            _speak_timing["audio_s"] = None
        _t_play = time.monotonic()
        if filler is not None:
            filler.stop()  # let the current clip finish, then start the answer
        try:  # live caption feed (audience page); whole answer on this path
            from stream_speak import (publish_speaking, publish_sentence_wav,
                                      wav_duration)
        except Exception:
            publish_speaking = None
        if publish_speaking:
            publish_speaking([text], text, done=False,
                             wav=publish_sentence_wav(wav_path),
                             dur=wav_duration(wav_path))
        _amode = _avatar_mode()
        if _amode in ("sync", "lips"):
            time.sleep(_avatar_lag())   # let the avatar catch up, then BOTH speak
        _mark_play_start()
        if _amode == "solo":
            from stream_speak import wav_duration
            end = time.monotonic() + (wav_duration(wav_path) or 2.0) \
                + _avatar_lag()
            while time.monotonic() < end:  # avatar page is the only voice
                time.sleep(0.1)
        elif stop is not None:
            interrupted = _play_wav_interruptible(wav_path, stop)
        else:
            r = subprocess.run(["aplay", "-q", wav_path])
            if r.returncode != 0:
                print("[audio] PLAYBACK FAILED — Bluetooth speaker connected?")
        if publish_speaking:
            publish_speaking([text], None, done=True, interrupted=interrupted)
        _speak_timing["play_s"] = round(time.monotonic() - _t_play, 2)
    finally:
        for p in (mp3_path, wav_path, wav_path + ".align.json"):
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

    def _play(wav, prefed_age=None):
        listener = listener_box.get("l")
        if listener is not None:
            return _play_wav_listener(wav, listener, prefed_age)
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
            filler.stop()
            gestures.start("talk")
            _say_apology(result["err"])
            return True
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
                **_wpm_meta(out.get("spoken_words"), out.get("audio_s")),
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
        _SENT_OUT.close()   # drain the last sentence's tail, free the device


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
        clip = random.choice(clips)
        if _avatar_mode() and _asides_enabled():
            # avatar mirrors the ack too; the hold makes it non-instant, so
            # do it off-thread to keep the STT call moving
            threading.Thread(target=_play_aside, args=(clip,),
                             daemon=True).start()
        else:
            subprocess.Popen(["aplay", "-q", clip],
                             stderr=subprocess.DEVNULL)


def _followup_window():
    """Seconds the mic stays open for a follow-up question after a completed
    answer (no fresh wake needed). 0 disables the conversational window."""
    try:
        return max(0.0, float(os.environ.get("CJ_FOLLOWUP_WINDOW_S", "6")))
    except ValueError:
        return 6.0


# "CJAP… CJAP?" (2026-08-25, user): when the robot does not react fast enough
# the visitor repeats the wake phrase, and the repeat lands INSIDE the
# recording. STT then returns "Cee-Jap, what is…" or just "CJAP?". The
# leading wake phrase(s) are stripped from the question; a transcript that
# was ONLY the wake phrase re-opens the mic ("rewake") instead of being
# answered or ending the turn.
_WAKE_TOKEN = (r"(?:(?:hi|hello|hey|okay|ok|oh)[\s,]+)?"
               r"(?:(?:cee|see|si|sea|ci|ce|cj)[\s\-]*(?:jap|jab|yap|jep|app|ap)"
               r"|c[\s\-]+(?:jap|jab|yap|jep|app|ap)|cjap|cejap|siyap|cj)\b")
_WAKE_PREFIX_RE = re.compile(r"^(?:\s*" + _WAKE_TOKEN + r"[\s,.!?;:\-]*)+", re.I)


def _strip_wake_phrase(text):
    """(question without leading wake phrases, how many were stripped)."""
    m = _WAKE_PREFIX_RE.match(text or "")
    if not m:
        return text, 0
    n = len(re.findall(_WAKE_TOKEN, m.group(0), re.I))
    return text[m.end():].strip(), n


def _safe_turn(*args, **kwargs):
    """handle_turn that cannot take the service down: any unexpected error is
    logged with its traceback, apologised for, and treated as a finished
    turn (True) so a locked conversation keeps going."""
    try:
        return handle_turn(*args, **kwargs)
    except Exception as e:
        import traceback
        traceback.print_exc()
        try:
            gestures = args[2]
            gestures.start("talk")
        except Exception:
            pass
        _say_apology(e)
        return True


def handle_turn(client, artifacts, gestures, history, stop=None, followup=False,
                listen_s=None):
    """Capture ONE question from the mic and answer it. Mutates `history` in
    place. Returns True if a full turn ran, False on mic timeout / empty STT,
    or "interrupted" (truthy) when the stop word cut the answer — the caller
    should go straight back to listening without requiring a fresh wake.
    followup=True shortens the no-speech timeout to the follow-up window, so
    silence hands control back to the caller quickly."""
    gestures.start("listen")
    _stage(reset=True)
    _stage("transcribe", "active", "listening…")
    path = record_with_meter(
        no_speech_timeout_s=(listen_s if listen_s is not None else
                             (_followup_window() if followup else 12)),
        keep_buffer=not followup)
    if not path:
        _publish_transcript("note", "(mic timeout — no speech captured)")
        _stage("transcribe", "pending", "no speech captured")
        return False
    lock = _voice_lock_obj() if _lock_enabled() else None
    lock_box = {}
    if lock is not None and followup and lock.active():
        # In conversation: only the locked voice gets through. The ~1.5 s
        # embedding runs in parallel with the STT call (joined below), so a
        # follow-up costs no extra latency; a stranger gets no answer.
        try:
            import speaker_id
            _sr, _data = speaker_id.read_wav(path)

            def _chk():
                try:
                    lock_box["res"] = lock.check_samples(_sr, _data)
                except Exception as e:   # never let the lock break the robot
                    print(f"[lock] check failed ({type(e).__name__}: {e}) — letting turn through")
                    lock_box["res"] = (True, None)
            lock_box["thread"] = threading.Thread(target=_chk, daemon=True)
            lock_box["thread"].start()
        except Exception as e:
            print(f"[lock] check skipped ({type(e).__name__}: {e})")
    _stage("transcribe", "active", "transcribing (gpt-4o-mini-transcribe)…")
    _play_ack()   # sub-second "Ah."/"Hmm." NOW — sound before the STT wait
    if lock is not None and not followup:
        try:   # first question after the wake word: THIS voice owns the session
            lock.lock(path)
            print("[lock] voice locked — conversing with this speaker only")
        except Exception as e:
            print(f"[lock] could not lock ({type(e).__name__}: {e}) — no conversation mode")
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
        if _net_probe.get("up") is False and not internet_up(0.6):
            raise ConnectionError("offline at wake")   # -> offline notice below
        lang = os.environ.get("CJ_STT_LANGUAGE", "en").strip() or None
        question = transcribe_openai(path, language=lang)
    except Exception as e:
        if internet_up():
            raise
        print(f"[net] offline during STT ({type(e).__name__}) — voicing the offline notice")
        _publish_transcript("note", "(offline — spoke the no-internet notice)")
        _stage("transcribe", "pending", "offline")
        gestures.start("talk")
        say_offline()
        return True
    finally:
        os.unlink(path)
    if not question.strip():
        print("[stt] empty transcript")
        _publish_transcript("note", "(empty transcript — STT heard nothing)")
        _stage("transcribe", "pending", "heard nothing")
        return False
    question, _nwake = _strip_wake_phrase(question)
    if _nwake:
        if not question.strip():
            print(f"[wake] heard only the wake phrase again ({_nwake}x) — listening for the question")
            _publish_transcript("note", "(heard the wake phrase again — still listening)")
            _stage("transcribe", "active", "listening again…")
            if lock is not None and not followup:
                lock.release()   # don't lock onto a 1 s "CJAP" clip; the retry re-locks on the real question
            return "rewake"
        print(f"[stt] wake phrase inside the question stripped ({_nwake}x) -> {question!r}")
    non_latin = sum(ord(c) > 127 for c in question) / len(question)
    if non_latin > 0.3:   # EN/Filipino are Latin-script; this is a hallucination
        print(f"[stt] discarded non-Latin hallucination: {question!r}")
        _publish_transcript("note", f"(discarded non-Latin hallucination: {question})")
        return False
    try:  # Filipino/English only (2026-08-25, user) — lang_gate fails open
        import lang_gate
        _ok, _why = lang_gate.check(question)
    except Exception as _e:
        _ok, _why = True, f"gate unavailable ({type(_e).__name__})"
    if not _ok:
        print(f"[stt] discarded — not Filipino/English: {question!r} ({_why})")
        _publish_transcript("note", f"(discarded — not Filipino/English: {question} · {_why})")
        _stage("transcribe", "pending", "not Filipino/English — ignored")
        return False
    stt_s = round(time.monotonic() - t0, 2)
    if lock_box.get("thread") is not None:
        lock_box["thread"].join(timeout=10)
        ok, sim = lock_box.get("res", (True, None))
        if not ok:
            print(f"[lock] ignored — not the voice in conversation "
                  f"(similarity {sim:.2f}): {question!r}")
            _publish_transcript("note", f"(ignored — another voice, similarity "
                                        f"{sim:.2f}: {question})")
            _stage("transcribe", "pending", "another voice — ignored")
            return "ignored"
        if sim is not None:
            print(f"[lock] locked voice confirmed (similarity {sim:.2f})")
    print(f"[stt] heard: \"{question}\"  ({stt_s:.1f}s)")
    _stage("transcribe", "done", f"heard in {stt_s:.1f}s")
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
    if lock is not None and lock.active() and _is_farewell(question):
        print("[lock] farewell heard — closing the conversation")
        _stage("route", "done", "farewell — closing the conversation",
               extra={"scope": "farewell", "topic": "goodbye", "confidence": "curated",
                      "scope_reason": "the speaker said goodbye"})
        _stage("compose", "done", "curated farewell")
        _stage("fidelity", "done", "curated — pre-verified")
        gestures.start("talk")
        # Warm, varied goodbye from the curated pool (2026-08-25, "improve
        # the emotion in the farewells"); the flat one-liner is the fallback.
        farewell = None
        try:
            import canned_answers
            farewell = canned_answers.get("thanks_goodbye")
        except Exception as e:
            print(f"[canned] farewell pool unavailable ({e})")
        farewell = farewell or FAREWELL_TEXT
        speak(farewell, None, stop=stop,
              voice_settings=voice_io.farewell_settings())
        _publish_transcript("cj", farewell)
        return "bye"
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
        _stage("route", "done", "matched a curated answer",
               extra={"scope": "canned", "topic": hit["id"], "confidence": "curated",
                      "scope_reason": "a question he has answered before — curated reply"})
        _stage("compose", "done", "curated text — no composer")
        _stage("fidelity", "done", "curated — pre-verified")
        response = hit["answer"]
        t0 = time.monotonic()
        gestures.start("talk")
        # goodbyes get the expressive delivery (see voice_io.farewell_settings)
        vs = voice_io.farewell_settings() if hit["id"] == "thanks_goodbye" else None
        interrupted = speak(response, None, stop=stop, voice_settings=vs)
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
            **_wpm_meta(_speak_timing.get("words"), _speak_timing.get("audio_s")),
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
                    **_wpm_meta(_speak_timing.get("words"), _speak_timing.get("audio_s")),
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
    muted_logged = False
    tap = _mic_tap()
    tap.flush()   # audio that piled up while the robot was busy is not a wake
    with contextlib.nullcontext(tap) as stream:
        while True:
            if os.path.exists(ASK_TRIGGER):
                ask = None
                try:
                    fresh = (time.time() - os.path.getmtime(ASK_TRIGGER)) < 30
                    raw = open(ASK_TRIGGER).read() if fresh else ""
                    os.unlink(ASK_TRIGGER)
                    if raw:
                        ask = json.loads(raw)
                except (OSError, ValueError) as e:
                    print(f"[ask] bad trigger ignored: {e}")
                if ask and ask.get("a") and _muted():
                    print(f"[mute] question button {ask.get('id')} ignored — muted from the dashboard")
                    ask = None
                if ask and ask.get("a"):
                    _pending_ask["ask"] = ask
                    print(f"[ask] question button: {ask.get('id')}")
                    _publish_wake(1.0, fired=True)
                    model.reset()
                    return 1.0
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
            tap.note_rms(frame[:, 0])
            score = float(max(model.predict(frame[:, 0]).values()))
            if score >= det.threshold and _muted():
                if not muted_logged:
                    print(f"[mute] wake phrase ignored (score {score:.3f}) — "
                          "muted from the dashboard; press Unmute on /maintain")
                    muted_logged = True
                _publish_wake(score)
                model.reset()
                continue
            muted_logged = False if not _muted() else muted_logged
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


def _ask_turn(gestures, history, ask, stop=None):
    """Speak a scripted answer queued by an /event question button. Mirrors the
    canned fast-path block in handle_turn — same captions, avatar feed, turn
    meta, history, and stop-word interruptible playback — but with no mic, no
    STT, and no composer: the question AND answer both come from the trigger
    (sourced from canned_answers.json by the dashboard), so the delivery is
    deterministic even if STT would have misheard the emcee."""
    question, response = ask.get("q") or "(question button)", ask["a"]
    entry_id = ask.get("id", "?")
    print(f"[ask] speaking scripted answer: {entry_id}")
    _publish_transcript("user", question)
    _publish_transcript("note", f"(question button: {entry_id})")
    _stage(reset=True)
    _stage("transcribe", "done", "typed question (event button)")
    _stage("route", "done", "scripted event answer",
           extra={"scope": "event", "topic": entry_id, "confidence": "curated",
                  "scope_reason": "scripted question for today's event"})
    _stage("compose", "done", "curated text — no composer")
    _stage("fidelity", "done", "curated — pre-verified")
    t0 = time.monotonic()
    gestures.start("talk")
    interrupted = speak(response, None, stop=stop)
    _publish_transcript("cj", response)
    _publish_turn_meta({
        "phase": "composed", "raw_asr": question, "question": question,
        "answer": response, "topic": f"canned:{entry_id}", "theme": "",
        "confidence": "button", "token_budget": 0, "dynamic_tokens": False,
        "stt_s": 0.0, "compose_s": 0.0,
        "cost_usd": 0.0, "cost_total_usd": _cost_meta(None).get("cost_total_usd"),
    })
    _publish_turn_meta({
        "phase": "spoken", "question": question,
        "synth_s": round(time.monotonic() - t0, 2), "play_s": None,
        "interrupted": bool(interrupted),
        **_wpm_meta(_speak_timing.get("words"), _speak_timing.get("audio_s")),
    })
    history += [{"role": "user", "content": question},
                {"role": "assistant", "content": response}]
    del history[:-20]
    if interrupted:
        _publish_transcript("note", "(answer interrupted by wake phrase)")
        return "interrupted"
    return True


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
        ask, _pending_ask["ask"] = _pending_ask["ask"], None
        if ask:   # /event question button: cached clip, works even offline
            gestures.perk()
            r = _ask_turn(gestures, history, ask, stop=stop)
            gestures.neutral()
            time.sleep(grace)
            print(f"[wake] re-armed — say \"{phrase}\"")
            continue
        prewarm_connections(client)   # warm OpenAI/Anthropic/ElevenLabs while the user speaks
        threading.Thread(target=_warm_voice_lock, daemon=True).start()
        gestures.perk()
        # Listen IMMEDIATELY after the wake word (2026-08-25, user): the
        # reachability probe used to block here for up to 1.2s (measured
        # 0.9-1.8s fire->mic on a slow LAN). It now runs in a thread while
        # the question is being recorded; handle_turn consults it before STT
        # and voices the offline notice if the network was down.
        _net_probe.clear()
        threading.Thread(target=lambda: _net_probe.update(up=internet_up(1.2)),
                         daemon=True).start()
        r = _safe_turn(client, artifacts, gestures, history, stop=stop)
        for _ in range(2):   # "CJAP… CJAP?": the wake phrase alone re-opens the mic
            if r != "rewake":
                break
            gestures.perk()
            r = _safe_turn(client, artifacts, gestures, history, stop=stop)
        lock = _voice_lock_obj() if _lock_enabled() else None
        if r is True and _net_probe.get("up") is False:
            # the turn voiced the offline notice; a lock conversation would
            # just repeat it for every utterance (2026-08-25 review)
            r = "offline"
        if lock is not None and lock.active() and r is True:
            # Voice-locked conversation (2026-08-24): keep the mic open for the
            # speaker who woke us. Other voices are ignored and cannot take
            # the lock (the wake detector is not even running in here). Ends
            # on "bye", the stop word, or CJ_VOICE_LOCK_IDLE_S of silence
            # from the locked voice after an answer.
            import speaker_id
            idle_s = speaker_id.lock_idle_s()
            print(f"[lock] in conversation — no wake word needed "
                  f"(ends on 'bye' or {idle_s:.0f}s of silence)")
            _publish_transcript("note", "(in conversation — no wake word needed; "
                                        "say goodbye or pause to end)")
            time.sleep(grace)
            deadline = time.monotonic() + idle_s
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0.3:
                    print("[lock] quiet — conversation closed")
                    break
                if _muted():
                    print("[lock] muted from the dashboard — conversation closed")
                    break
                gestures.perk()
                r = _safe_turn(client, artifacts, gestures, history, stop=stop,
                               followup=True, listen_s=remaining)
                if r is True:                      # answered: idle clock restarts
                    time.sleep(grace)
                    deadline = time.monotonic() + idle_s
                    continue
                if r in ("bye", "interrupted"):
                    break
                # "ignored" (another voice), empty STT, mic timeout: keep
                # listening until the deadline
            lock.release()
            _publish_transcript("note", "(conversation closed — say the wake word to start again)")
        elif lock is not None:
            lock.release()
        while lock is None:   # legacy follow-up / stop-relisten loop (lock off)
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
            if r in (True, "rewake") and _followup_window() > 0:
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
