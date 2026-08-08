"""Voice loop: cloud STT/TTS + fillers + mic meter + storytelling gestures.

Modes:
  (default)  push-to-talk — Enter to speak
  --auto     hands-free, no wake word — answers any speech it hears
  --wake     hands-free with wake word — SLEEP until "Cee-Jap" (WW-5 matcher
             from app/wake_word.py), perk, capture one question, answer,
             back to SLEEP. Wake STT runs on OpenAI whisper-1 (the "local"
             faster-whisper backend is NOT installed on the Pi); windows are
             RMS-gated so silence never triggers an API call.
"""
import argparse, glob, json, os, random, socket, subprocess, tempfile, threading, time
import numpy as np
import sounddevice as sd
from scipy.io import wavfile
from cj_chat import CorpusArtifacts, cache_savings_summary, make_client, run_turn
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
        try:
            from reachy_mini import ReachyMini
            from reachy_mini.utils import create_head_pose
            self._pose = create_head_pose
            self.mini = ReachyMini(media_backend="no_media")
            self.mini.enable_motors(); print("[gestures] connected, motors on")
        except Exception as e:
            print(f"[gestures] disabled ({e})")

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
            elif mode == "sleep":     # armed idle: barely-there sway, long pauses
                self._move(random.uniform(-4, 4), random.uniform(-2, 3),
                           random.uniform(-2, 2), 1.6)
                self._stop.wait(random.uniform(2.5, 4.5))
            else:                     # talk: lively nods + emphasis tilts + antenna flicks
                self._move(random.uniform(-12, 12), random.uniform(-6, 10),
                           random.uniform(-7, 7), 0.5,
                           antennas=[random.uniform(-0.25, 0.25),
                                     random.uniform(-0.25, 0.25)])
                self._stop.wait(random.uniform(0.35, 0.9))

    def start(self, mode):
        self.stop()
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


class FillerLoop:
    """Keep the robot talking while the response composes: play filler clips
    with natural pauses until stop(). stop() never cuts a clip mid-word — it
    waits for the current one to finish, so the answer never talks over it.
    After max_clips plays (CJ_FILLER_MAX, default 4) it stops playing and sets
    `exhausted` — handle_turn treats that as "taking too long, bail out"."""

    def __init__(self, gap_range=(2.5, 5.0), max_clips=None):
        self._clips = glob.glob(FILLER_DIR + "/*.wav")
        self._gap_range = gap_range
        self._stop = threading.Event()
        self.max_clips = (max_clips if max_clips is not None
                          else int(os.environ.get("CJ_FILLER_MAX", "4")))
        self.exhausted = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        if self._clips:
            self._thread.start()

    def _run(self):
        pool, played = [], 0
        while not self._stop.is_set():
            if not pool:
                pool = self._clips[:]
                random.shuffle(pool)
            subprocess.run(["aplay", "-q", pool.pop()],
                           stderr=subprocess.DEVNULL)
            played += 1
            if self.max_clips and played >= self.max_clips:
                self.exhausted.set()
                return
            if self._stop.wait(random.uniform(*self._gap_range)):
                break

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join()


def play_filler():
    return FillerLoop()


def speak(text, filler=None):
    mp3 = tts_concatenate_parallel(text)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(mp3)
        mp3_path = f.name
    wav_path = mp3_path.replace(".mp3", ".wav")
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", mp3_path, wav_path], check=True)
        if filler is not None:
            filler.stop()  # let the current clip finish, then start the answer
        r = subprocess.run(["aplay", "-q", wav_path])
        if r.returncode != 0:
            print("[audio] PLAYBACK FAILED — Bluetooth speaker connected?")
    finally:
        for p in (mp3_path, wav_path):
            if os.path.exists(p):
                os.unlink(p)


def handle_turn(client, artifacts, gestures, history):
    """Capture ONE question from the mic and answer it. Mutates `history` in
    place. Returns True if a full turn ran, False on mic timeout / empty STT."""
    gestures.start("listen")
    path = record_with_meter()
    if not path:
        _publish_transcript("note", "(mic timeout — no speech captured)")
        return False
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
    print(f"[stt] heard: \"{question}\"  ({time.monotonic() - t0:.1f}s)")
    _publish_transcript("user", question)
    t0 = time.monotonic()
    filler = play_filler()
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
        q, response, _ = result["turn"]
        if q and response:
            gestures.start("talk")
            print(f"[tts] speaking...  (compose {time.monotonic() - t0:.1f}s)")
            _publish_transcript("cj", response)
            speak(response, filler)  # filler talks through TTS synth too
            history += [{"role": "user", "content": q},
                        {"role": "assistant", "content": response}]
            del history[:-20]
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
    speaker tail before the mic re-arms (kiosk state-machine behavior)."""
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
        gestures.perk()
        if not internet_up():
            # Say so instead of recording a question no cloud call can answer.
            print("[net] offline at wake — voicing the offline notice")
            gestures.start("talk")
            say_offline()
            gestures.neutral()
            time.sleep(grace)
            print(f"[wake] re-armed — say \"{phrase}\"")
            continue
        handle_turn(client, artifacts, gestures, history)
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
