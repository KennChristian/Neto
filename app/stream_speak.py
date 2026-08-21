"""Streaming first-sentence speech for the kiosk (2026-08-12).

Instead of compose-everything -> synth-everything -> play, this streams
Sonnet's answer, cuts it into sentences as tokens arrive, synthesizes each
sentence (one ahead), and starts PLAYING as soon as the first sentence's
audio is ready — first audio lands during composition of the rest.

Used by cj_voice_cloud.handle_turn when CJ_STREAM_SPEECH is on; the classic
whole-answer path remains the fallback. Fail behavior: any error raises to
the caller, which owns the offline/bail handling.

Sentence splitting is citation-aware: never splits after abbreviations like
"v." (Lambino v. Comelec), "Mr.", "G.R.", initials, etc.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

LAST_ANSWER_MP3 = "/dev/shm/cj_last_answer.mp3"
# Live caption feed for the audience page: updated the moment each
# sentence's audio starts playing, so the UI traces speech in real time.
SPEAKING_LIVE = "/dev/shm/cj_speaking.json"


def publish_speaking(spoken, current, done, interrupted=False):
    """Atomically publish what is being spoken right now (fails open)."""
    try:
        tmp = SPEAKING_LIVE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"ts": time.time(), "spoken": list(spoken),
                       "current": current, "done": done,
                       "interrupted": interrupted}, f)
        os.replace(tmp, SPEAKING_LIVE)
    except OSError:
        pass

# never end a sentence right after these (abbreviations, initials, citations)
_NO_BREAK = re.compile(
    r"(?:\b(?:v|vs|Mr|Mrs|Ms|Dr|Jr|Sr|St|No|Nos|Rep|Sen|Atty|Hon|Gov|Sec|"
    r"Gen|Col|Fr|Br|Prof|Ph|G\.R|R\.A|Vol|Ch|Art|Sec)|\b[A-Z])\.$")
_BOUNDARY = re.compile(r"(?<=[.!?…])[\"'”’)]*\s+")
_MIN_SENT = 25  # chars; shorter fragments merge forward to avoid choppy TTS

# ---------------------------------------------------------------------------
# per-sentence emotion -> gesture style (consumed by Gestures.talk_style)
# ---------------------------------------------------------------------------
# Weighted cue lists (2026-08-13, was a 3-pattern first-match list that left
# most sentences "neutral"). Every match adds its weight; highest total wins,
# ties broken by the order below (graver feelings first).
_EMOTION_CUES = [
    ("solemn", 2, re.compile(
        r"\b(tragic|tragedy|massacre|death|died|passed away|grie[fv]|sadly|"
        r"regret|mourn|somber|painful|suffer|unfortunate|heavy heart|lament|"
        r"martial law|dictatorship|injustice|sorrow|burden|condolence|"
        r"widow|orphan|victim|calvary|anguish|weep|wept|farewell|"
        r"final journey|eulogy|rest in peace|solemn)\w*\b", re.I)),
    ("emphatic", 2, re.compile(
        r"\b(with due respect|I dissent|I must|never|must not|unconstitutional|"
        r"I maintain|let me be clear|in my humble opinion|au contraire|firmly|"
        r"insist|rule of law|I submit|I stress|underscore|non-?negotiable|"
        r"duty|uphold|defend|accountab|liberty|justice demands|"
        r"the Constitution requires|no less than|precisely|categorically)\w*\b",
        re.I)),
    ("warm", 2, re.compile(
        r"\b(cheers|delight|joy|blessed|grateful|thank|love|family|"
        r"grandchildren|my wife|leni|faith|God|Lord|happy|proud|honou?red|"
        r"wonderful|salamat|mabuhay|kababayan|my friend|dear|fond|cherish|"
        r"blessing|prayer|apos?|anak|congratulat|welcome|celebrate|"
        r"my heart|beloved|warm)\w*\b", re.I)),
    ("amused", 2, re.compile(
        r"\b(chismoso|marites|susmaryosep|tikum|guapo|binata|abangan|"
        r"joke|jest|laugh|chuckle|tease|teasing|funny|amus|wink|"
        r"I ain'?t talking|so to speak|in both senses|forgive an old man|"
        r"if you must know|ha ha|hehe)\w*\b", re.I)),
]


def classify_emotion(sentence: str) -> str:
    """Heuristic tone tag for one sentence, driving the matching gesture:
    solemn|emphatic|warm|amused|question|neutral. Weighted: all cue hits are
    scored so a sentence 'feels' like its dominant emotion, not its first
    keyword; punctuation contributes instead of deciding alone."""
    s = sentence.strip()
    scores = {}
    for tag, w, rx in _EMOTION_CUES:
        n = len(rx.findall(s))
        if n:
            scores[tag] = scores.get(tag, 0) + w * n
    if s.endswith("?"):
        scores["question"] = scores.get("question", 0) + 3
    if s.endswith("!"):
        # an exclamation intensifies whatever is already there; alone → emphatic
        best = max(scores, key=scores.get) if scores else "emphatic"
        scores[best] = scores.get(best, 0) + 2
    if not scores:
        return "neutral"
    return max(scores, key=scores.get)


def split_ready(buf: str):
    """(complete_sentences, remainder) from a growing text buffer."""
    out, start = [], 0
    for m in _BOUNDARY.finditer(buf):
        cand = buf[start:m.start() + 1].strip()
        if not cand or _NO_BREAK.search(buf[:m.start() + 1].rstrip()):
            continue
        if out and len(cand) < _MIN_SENT:
            out[-1] = out[-1] + " " + cand
        elif len(cand) < _MIN_SENT and not out:
            continue  # too short to speak alone; wait for more
        else:
            out.append(cand)
        start = m.end()
    return out, buf[start:]


class SentenceSpeaker:
    """Synthesizes queued sentences (one ahead) and plays them in order.

    play_fn(wav_path) -> bool(interrupted) is injected by cj_voice_cloud so
    the stop-word/mute machinery is reused verbatim. on_first_audio() fires
    just before the first playback starts (filler stop + talk gesture)."""

    def __init__(self, play_fn, on_first_audio=None, abort=None, style_fn=None):
        self._play_fn = play_fn
        self._on_first = on_first_audio
        self._style_fn = style_fn      # called with (sentence, emotion) pre-play
        self._abort = abort or threading.Event()
        self._pool = ThreadPoolExecutor(max_workers=2)
        self._futures = []
        self._mp3s = []
        self._done_feeding = threading.Event()
        self._player = None
        self._lock = threading.Lock()
        self.interrupted = False
        self.first_audio_ts = None
        self.n_sentences = 0
        self._spoken_texts = []   # sentences whose audio has started (captions)

    # ---- synthesis ----
    _oai = None
    _oai_lock = threading.Lock()

    @classmethod
    def _client(cls):
        # voice_io's parallel TTS caches an ASYNC client bound to one event
        # loop — calling it from several worker threads stalls for seconds.
        # Reuse voice_io's cached SYNC client instead: it is thread-safe AND
        # its connection pool is already warm from the STT call at turn start
        # (a cold TLS setup costs ~5-7s on the CM4; warm is ~1.5-2s).
        with cls._oai_lock:
            if cls._oai is None:
                try:
                    from voice_io import _sync_client
                    cls._oai = _sync_client()
                except Exception:
                    from openai import OpenAI
                    cls._oai = OpenAI()
        return cls._oai

    def _synth(self, text):
        import voice_io
        try:
            from postprocess import process_tts_sentence
            text = process_tts_sentence(text)
        except Exception:
            pass
        if getattr(voice_io, "TTS_BACKEND", "openai") == "elevenlabs":
            try:
                # Cloned voice: wav first, then mp3 for the replay concat —
                # same one-ffmpeg-per-sentence cost as the openai path below.
                # Dynamic speed: this sentence's emotion nudges the pace
                # (solemn slower, amused quicker) — same classifier that
                # styles the gestures, so motion and delivery agree.
                spd = voice_io.emotion_speed(classify_emotion(text))
                wav = voice_io.tts_elevenlabs_wav(text, speed=spd)
                mp3_path = wav.replace(".wav", ".mp3")
                subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet",
                                "-i", wav, mp3_path], check=True)
                return mp3_path, wav
            except Exception as e:
                print(f"[stream-speak] elevenlabs synth failed "
                      f"({type(e).__name__}) — openai fallback for this sentence")
        mp3 = self._client().audio.speech.create(
            **voice_io.tts_create_kwargs(
                getattr(voice_io, "TTS_MODEL_DEFAULT", "tts-1"),
                getattr(voice_io, "TTS_VOICE_DEFAULT", "echo"),
                getattr(voice_io, "TTS_SPEED_DEFAULT", 0.98),
                text)).content
        f = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False, dir="/dev/shm")
        f.write(mp3)
        f.close()
        wav = f.name.replace(".mp3", ".wav")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", f.name, wav],
                       check=True)
        return f.name, wav

    def add(self, sentence):
        if self._abort.is_set():
            return
        self.n_sentences += 1
        with self._lock:
            self._futures.append((sentence, self._pool.submit(self._synth, sentence)))
            if self._player is None:
                self._player = threading.Thread(target=self._play_loop, daemon=True)
                self._player.start()

    # ---- playback ----
    def _play_loop(self):
        i = 0
        while True:
            with self._lock:
                row = self._futures[i] if i < len(self._futures) else None
            sentence, fut = row if row else (None, None)
            if fut is None:
                if self._done_feeding.is_set():
                    return
                if self._abort.is_set():
                    return
                time.sleep(0.05)
                continue
            try:
                mp3_path, wav = fut.result()
            except Exception as e:
                print(f"[stream-speak] sentence synth failed, skipping: {e}")
                i += 1
                continue
            self._mp3s.append(mp3_path)
            if self._abort.is_set():
                os.unlink(wav)
                return
            if self.first_audio_ts is None:
                self.first_audio_ts = time.monotonic()
                if self._on_first:
                    try:
                        self._on_first()
                    except Exception:
                        pass
            if self._style_fn:
                try:  # emotion-matched gesture for THIS sentence
                    self._style_fn(sentence, classify_emotion(sentence))
                except Exception:
                    pass
            self._spoken_texts.append(sentence)
            publish_speaking(self._spoken_texts, sentence, done=False)
            cut = self._play_fn(wav)
            try:
                os.unlink(wav)
            except OSError:
                pass
            if cut:
                self.interrupted = True
                self._abort.set()
                publish_speaking(self._spoken_texts, None, done=True,
                                 interrupted=True)
                return
            i += 1

    def finish(self, timeout=180):
        """No more sentences coming; wait for playback to drain."""
        self._done_feeding.set()
        if self._player:
            self._player.join(timeout=timeout)
        self._pool.shutdown(wait=False)
        publish_speaking(self._spoken_texts, None, done=True,
                         interrupted=self.interrupted)
        # keep the whole answer for the dashboard replay button
        try:
            if self._mp3s:
                with open(LAST_ANSWER_MP3, "wb") as out:
                    for p in self._mp3s:
                        out.write(open(p, "rb").read())
        except OSError:
            pass
        for p in self._mp3s:
            try:
                os.unlink(p)
            except OSError:
                pass
        return self.interrupted

    def cancel(self):
        self._abort.set()
        self._done_feeding.set()


def _fidelity_audit_enabled():
    # Deliberately independent of CJ_SKIP_FIDELITY: that flag exists to skip
    # the classic path's verify-before-speak retry loop (a LATENCY cost, and
    # it is set in app/.env for that reason). This audit is async during
    # playback — free — so it gets its own switch only.
    return os.environ.get("CJ_FIDELITY_AUDIT", "1").strip().lower() not in {
        "0", "false", "no", "off"}


def stream_turn(client, artifacts, question, history, *, play_fn,
                on_first_audio=None, abort=None, style_fn=None):
    """Gate -> route -> STREAMED compose, speaking sentence-by-sentence.

    Returns {response, routing, interrupted, first_audio_s, compose_s} or
    None if aborted before completion. Raises on API errors (caller owns
    offline handling)."""
    from cj_chat import (input_gate, force_meta_routing, route_question,
                         generate_response_stream, _strip_stage_directions)
    abort = abort or threading.Event()
    t0 = time.monotonic()
    # gate and route are independent Haiku calls unless the gate flags an
    # identity probe — run them in PARALLEL and discard the route in that
    # rare case (~2s off time-to-first-audio on every normal turn)
    route_box = {}

    def _route():
        try:
            route_box["r"] = route_question(client, question, artifacts)
        except Exception as e:
            route_box["err"] = e
        finally:
            route_box["s"] = round(time.monotonic() - t0, 2)

    rt = threading.Thread(target=_route, daemon=True)
    rt.start()
    gate = input_gate(client, question)
    gate_s = round(time.monotonic() - t0, 2)
    ooc_text = None
    if gate.get("scope") == "identity_probe":
        routing = force_meta_routing(gate.get("reasoning", ""))
    else:
        if gate.get("scope") == "out_of_corpus":
            try:  # canned out-of-topic deflection (fails open to the composer)
                import canned_answers
                ooc_text = canned_answers.get("out_of_topic")
            except Exception as e:
                print(f"[canned] ooc unavailable ({e})")
        if ooc_text is not None:
            # Skip the router join AND the composer — zero Sonnet tokens; the
            # canned prose flows through the normal sentence/speaker machinery
            # (captions, gestures, stop word) below.
            routing = {"primary_topic": "out_of_topic_canned",
                       "secondary_topics": [], "confidence": "low",
                       "reasoning": gate.get("reasoning", "")}
            print("[canned] out-of-topic fast path — router/composer skipped")
        else:
            rt.join(timeout=30)
            if "err" in route_box:
                raise route_box["err"]
            routing = route_box.get("r") or force_meta_routing("router timeout fallback")
    print(f"[stream] gate {gate_s}s | route {route_box.get('s', '-')}s (parallel)")
    if abort.is_set():
        return None

    # P0 answer gate (kiosk wiring): FORBID-screen each sentence BEFORE it is
    # spoken (~0.15 ms, zero LLM) — a tripped sentence (e.g. AI self-
    # description) is skipped, never voiced. Expected-fact rules need the
    # whole answer, so they run once at the end (logged; audio already out).
    gate_mod, gate_topics, gate_blocked = None, [], []
    try:
        import config as _cfg
        if getattr(_cfg, "ANSWER_GATE_ENABLED", False):
            import answer_gate as gate_mod
            gate_topics = [t for t in [routing.get("primary_topic")]
                           + list(routing.get("secondary_topics") or []) if t]
    except Exception as e:
        print(f"[answer-gate] unavailable, fail-open: {type(e).__name__}")
        gate_mod = None

    speaker = SentenceSpeaker(play_fn, on_first_audio=on_first_audio, abort=abort,
                              style_fn=style_fn)

    def _add_gated(s):
        if gate_mod is not None:
            g = gate_mod.check_answer(question, s, topic_ids=gate_topics,
                                      forbid_only=True)
            if not g["ok"]:
                gate_blocked.append({"sentence": s, "tripped": g["tripped"]})
                print(f"[answer-gate] sentence BLOCKED pre-TTS: "
                      f"{[t['detail'] for t in g['tripped']]}")
                return
        speaker.add(s)

    buf, parts = "", []
    stream_info = {}
    stream_src = ([ooc_text] if ooc_text is not None else
                  generate_response_stream(client, question, routing, artifacts,
                                           history, info=stream_info))
    for piece in stream_src:
        if not parts:
            print(f"[stream] first composer token {time.monotonic() - t0:.1f}s")
        if abort.is_set():
            if speaker.interrupted:
                break        # stop word / mute fired: stop composing, report it
            speaker.cancel()
            return None      # external bail (filler exhaustion)
        parts.append(piece)
        buf += piece
        ready, buf = split_ready(buf)
        for s in ready:
            _add_gated(_strip_stage_directions(s))
    # Async fidelity audit (user-approved 2026-08-21): the Haiku checker runs
    # WHILE the answer's audio plays (speaker.finish() below blocks for the
    # remaining playback, which almost always outlasts the ~1-1.5s check), so
    # it adds no turn latency. Flags are AUDITED — the audio is already out —
    # and surface in the journal, turn meta, and maintenance page. Skipped for
    # canned/out-of-topic prose (hand-curated). Disable: CJ_FIDELITY_AUDIT=0.
    fid_box, fid_thread = {}, None
    audit_text = _strip_stage_directions("".join(parts)).strip()
    if ooc_text is None and audit_text and _fidelity_audit_enabled():
        def _audit():
            try:
                from cj_chat import fidelity_check, build_context
                ctx = build_context(routing, artifacts)
                fid_box.update(fidelity_check(client, ctx, audit_text))
            except Exception as e:   # audit must never break a turn
                print(f"[fidelity] audit failed open: {type(e).__name__}: {e}")
        fid_thread = threading.Thread(target=_audit, daemon=True)
        fid_thread.start()

    dropped_tail = None
    if not speaker.interrupted:
        tail = _strip_stage_directions(buf.strip())
        if tail:
            # Cap-hit truncation guard: if the stream stopped on max_tokens
            # and the leftover buffer is not a complete sentence, it is a
            # mid-clause fragment — never voice it (the classic path trims
            # the same way; the streaming path used to speak it).
            if (stream_info.get("stop_reason") == "max_tokens"
                    and tail[-1] not in ".!?…\"”'’"):
                dropped_tail = tail
                print(f"[stream] cap-hit fragment dropped (never voiced): "
                      f"{tail[:60]!r}")
            else:
                _add_gated(tail)
    compose_s = round(time.monotonic() - t0, 2)
    interrupted = speaker.finish()
    response_text = _strip_stage_directions("".join(parts)).strip()
    if dropped_tail and response_text.endswith(dropped_tail):
        # Keep captions/history/dashboard consistent with what was SPOKEN.
        response_text = response_text[:-len(dropped_tail)].rstrip()
    gate_full = None
    if gate_mod is not None:
        # full-answer check: expected facts need the whole answer. The audio
        # is already out (streaming), so trips here are AUDITED, not blocked.
        gate_full = gate_mod.check_answer(question, response_text,
                                          topic_ids=gate_topics)
        if not gate_full["ok"]:
            print(f"[answer-gate] full-answer trip (audited, already spoken): "
                  f"{[t['rule'] for t in gate_full['tripped']]}")
    if fid_thread is not None:
        # Playback normally outlasts the audit; after a stop-word cut don't
        # hold the turn open — the daemon thread just logs when it lands.
        fid_thread.join(timeout=1.0 if interrupted else 12.0)
        flags = [k for k in ("hallucination", "voice_drift",
                             "guardrail_violation") if fid_box.get(k)]
        if flags:
            print(f"[fidelity] AUDIT flagged (already spoken): {flags} — "
                  f"{fid_box.get('reasoning', '')[:140]}")
        elif fid_box:
            print("[fidelity] audit clean")
    return {
        "response": response_text,
        "routing": routing,
        "interrupted": interrupted,
        "first_audio_s": (round(speaker.first_audio_ts - t0, 2)
                          if speaker.first_audio_ts else None),
        "compose_s": compose_s,
        "n_sentences": speaker.n_sentences,
        "gate_blocked_sentences": gate_blocked,
        "gate_full": gate_full,
        "fidelity": fid_box or None,
    }
