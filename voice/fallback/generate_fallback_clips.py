"""Generate the offline fallback clips (run once, online).

    python -m voice.fallback.generate_fallback_clips [extra phrases...]

Renders every phrase in speak.REASON_PHRASES (plus any argv extras) through
the normal synth + EQ chain and writes `<sha16>.wav` + `index.json` into
voice/fallback/. Never logs or embeds credentials.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path

import soundfile as sf

from .. import audio, cache
# import from the submodule directly — the package __init__ rebinds the name
# `speak` to the function, shadowing the module
from ..speak import REASON_PHRASES, SynthError, synthesize

log = logging.getLogger("voice.fallback")

FALLBACK_DIR = Path(__file__).resolve().parent
INDEX_PATH = FALLBACK_DIR / "index.json"


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    extras = list(argv if argv is not None else sys.argv[1:])
    phrases = list(REASON_PHRASES.values()) + extras

    index: dict[str, str] = {}
    if INDEX_PATH.is_file():
        index = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    failures = 0
    for phrase in phrases:
        normalized = cache.normalize_text(phrase)
        name = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16] + ".wav"
        if normalized in index and (FALLBACK_DIR / index[normalized]).is_file():
            log.info("exists: %.60s", normalized)
            continue
        try:
            pcm = synthesize(normalized)
        except SynthError as e:
            log.error("synthesis failed for %.60r (%s)", normalized, e.reason)
            failures += 1
            continue
        processed = audio.process(pcm, audio.SYNTH_SAMPLE_RATE)
        sf.write(FALLBACK_DIR / name, processed, audio.SYNTH_SAMPLE_RATE,
                 subtype="PCM_16")
        index[normalized] = name
        log.info("rendered: %.60s -> %s", normalized, name)

    INDEX_PATH.write_text(json.dumps(index, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    log.info("index written with %d clip(s)", len(index))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
