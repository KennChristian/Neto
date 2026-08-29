"""P3 dynamic filler — a question-relevant thinking-aloud sentence.

Design (hybrid, latency-safe): the FIRST filler is always a canned clip from
~/fillers (zero latency). While it plays, this module generates ONE short
in-persona sentence acknowledging the question's topic (Haiku) and voices it
(same TTS voice as live speech), then injects it as the NEXT filler clip via
FillerLoop.inject(). Generation typically lands in 2-4s — inside the first
clip + gap — so it can never delay first filler audio or the real answer.

Dark behind CJ_DYNAMIC_FILLER=1. Every failure is silent-open: the loop just
keeps playing canned clips.
"""

import os
import subprocess
import tempfile
import threading
import time

_SYSTEM = (
    "You are Chief Justice Artemio V. Panganiban (ret.), thinking aloud for a "
    "brief moment before answering a visitor's question. Reply with EXACTLY "
    "ONE short sentence (at most 14 words) that acknowledges the TOPIC of the "
    "question without answering it. No facts, no dates, no case holdings, no "
    "opinions, no questions back, no quotation marks. Warm, dignified, first "
    "person, as if gathering your thoughts. Examples: "
    "Ah, the West Philippine Sea — a subject close to my heart. / "
    "Impeachment — let me look back through my years on the bench. / "
    "A question about my family; allow me a fond moment."
)


def enabled() -> bool:
    return os.environ.get("CJ_DYNAMIC_FILLER", "").strip().lower() in {
        "1", "true", "yes", "on"}


def start(client, question, filler, note=None):
    """Fire-and-forget: generate + voice a relevant filler and inject it into
    `filler` (a FillerLoop). No-op unless CJ_DYNAMIC_FILLER is set."""
    if not enabled() or not question:
        return
    threading.Thread(target=_work, args=(client, question, filler, note),
                     daemon=True).start()


def _work(client, question, filler, note):
    t0 = time.monotonic()
    try:
        from cj_chat import ROUTER_MODEL
        msg = client.messages.create(
            model=ROUTER_MODEL, max_tokens=60, system=_SYSTEM,
            messages=[{"role": "user", "content": question[:500]}])
        text = msg.content[0].text.strip().strip('"').strip()
        if not text or "\n" in text or len(text.split()) > 20:
            print(f"[dynfiller] rejected generation: {text!r}")
            return
        import voice_io
        wav = None
        if getattr(voice_io, "TTS_BACKEND", "openai") == "elevenlabs":
            try:  # cloned voice, matches the answer + canned filler pool
                wav = voice_io.tts_elevenlabs_wav(text)
            except Exception as e:
                print(f"[dynfiller] elevenlabs failed ({type(e).__name__}) "
                      f"— openai fallback")
        if wav is None:
            from voice_io import (_sync_client, tts_create_kwargs,
                                  TTS_MODEL_DEFAULT, TTS_VOICE_DEFAULT,
                                  TTS_SPEED_DEFAULT)
            kw = tts_create_kwargs(TTS_MODEL_DEFAULT, TTS_VOICE_DEFAULT,
                                   TTS_SPEED_DEFAULT, text)
            mp3 = _sync_client().audio.speech.create(**kw).content
            f = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False,
                                            dir="/dev/shm", prefix="cj_dynfil_")
            f.write(mp3)
            f.close()
            wav = f.name.replace(".mp3", ".wav")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "quiet", "-i", f.name, wav],
                           check=True)
            os.unlink(f.name)
        secs = round(time.monotonic() - t0, 2)
        if filler.inject(wav):
            print(f'[dynfiller] injected in {secs}s: "{text}"')
            if note:
                try:
                    note("note", f'(dynamic filler, ready {secs}s: "{text}")')
                except Exception:
                    pass
        else:  # answer already speaking — filler no longer needed
            print(f"[dynfiller] ready in {secs}s but too late, discarded")
            for p in (wav, wav + ".align.json"):
                try:
                    os.unlink(p)
                except OSError:
                    pass
    except Exception as e:
        print(f"[dynfiller] skipped ({type(e).__name__}: {e})")
