"""P0 post-processing: dictionary-grounded NER + ASR-mishear correction.

Runs on (a) ASR transcripts before they enter the pipeline and (b) composer
output sentences before TTS. Detects domain-critical entities (person / org /
case / event / book) against the canonical dictionary built by
scripts/build_entity_dict.py, corrects ASR misrecognitions to the canonical
form, and preserves exact Supreme Court citation strings.

Ships DARK: with config.POSTPROC_ENABLED=False the public wrappers return
their input byte-identical and never load the dictionary.

Output contract (annotate):
  {text, source, entities: [{surface, canonical, class, span, confidence,
                             kind, corrected}], corrections: [...]}
`span` indexes into the INPUT text; `text` is the corrected string.

Correction policy (what gets rewritten vs merely annotated):
  * `misrecognitions` dictionary hits  -> rewritten to canonical
  * fuzzy/phonetic matches             -> rewritten to canonical
  * class == "case" (SC citations)     -> rewritten to the exact canonical
    citation string (spec: no paraphrase of citation formatting)
  * exact variants differing only in case/diacritics/punctuation -> rewritten
  * all other exact variants (e.g. legitimate acronyms like "FLP") -> annotated
    only; the speaker's words are not rewritten.

Every rewrite is appended as JSONL to config.POSTPROC_LOG_PATH for
precision/recall auditing (P0 spec: log every correction).

The dictionary + overlay are hand-editable JSON; `load(force=True)` or an
mtime change picks up edits without a restart (P2.5 operator requirement).
"""

from __future__ import annotations

import difflib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

_WS = re.compile(r"\s+")

# ---------------------------------------------------------------------------
# Normalization (mirrors scripts/build_entity_dict.py so keys compare equal)
# ---------------------------------------------------------------------------


def match_key(s: str) -> str:
    """Diacritic-folded, punctuation-free lookup key ('Tañada v. Angara' -> 'tanada v angara')."""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\b(?:vs|versus)\b", "v", s)  # 'Lambino vs/versus Comelec' == 'Lambino v. Comelec'
    return _WS.sub(" ", s).strip()


_SOUNDEX = {}
for _cls, _letters in (("1", "bfpv"), ("2", "cgjkqsxz"), ("3", "dt"),
                       ("4", "l"), ("5", "mn"), ("6", "r")):
    for _l in _letters:
        _SOUNDEX[_l] = _cls


def phone_code(word: str) -> str:
    """Compact soundex-class code for mishear bucketing ('echegaray' ~ 'etchegaray')."""
    codes = [_SOUNDEX[c] for c in match_key(word).replace(" ", "") if c in _SOUNDEX]
    out = []
    for c in codes:
        if not out or out[-1] != c:
            out.append(c)
    return "".join(out)[:4] or "0"


def _tokens(text: str):
    """[(word, char_start, char_end)] over the raw input text.

    A sentence-final period stays OUT of the token span (so a rewrite never
    swallows it), but abbreviation dots survive ("v.", "Jr.", "P.A.").
    """
    out = []
    for m in re.finditer(r"[A-Za-z0-9À-ɏ][A-Za-z0-9À-ɏ'’.\-]*", text):
        w, s, e = m.group(0), m.start(), m.end()
        core = w.rstrip(".")
        if w.endswith(".") and len(core) > 2 and "." not in core:
            w, e = core, s + len(core)
        out.append((w, s, e))
    return out


# ---------------------------------------------------------------------------
# Dictionary loading (resident; overlay-aware; mtime hot-reload)
# ---------------------------------------------------------------------------


def _resolve_entries(dict_path: Path, overlay_path: Path) -> list[dict]:
    """entity_dict entries with the hand-curated overlay applied (merge/remove/add)."""
    base = json.loads(Path(dict_path).read_text(encoding="utf-8"))
    entries = {e["id"]: dict(e) for e in base.get("entries", [])}
    if Path(overlay_path).exists():
        ov = json.loads(Path(overlay_path).read_text(encoding="utf-8"))
        for eid, patch in (ov.get("merge") or {}).items():
            e = entries.get(eid)
            if e is None:
                continue
            if patch.get("canonical"):
                e["canonical"] = patch["canonical"]
            if patch.get("gloss"):
                e["gloss"] = list(dict.fromkeys(patch["gloss"] + e.get("gloss", [])))
            e["variants"] = sorted(set(e.get("variants", [])) | set(patch.get("add_variants", [])))
            e["misrecognitions"] = sorted(
                set(e.get("misrecognitions", [])) | set(patch.get("add_misrecognitions", [])))
        for eid in ov.get("remove") or []:
            entries.pop(eid, None)
        for e in ov.get("add") or []:
            if isinstance(e, dict) and e.get("id") and e.get("canonical"):
                entries[e["id"]] = dict(e)
    return list(entries.values())


# function words that acronym/short variants must never claim ("ME" -> "me", "WHO" -> "who")
_COMMON_WORDS = frozenset(
    "me who the a an in on at it is to of and or for by as he she we they you i "
    "no so up do be this that was are with from his her its our your".split())


class EntityIndex:
    """Resident match structures over the resolved dictionary."""

    def __init__(self, entries: list[dict]):
        self.entries = entries
        self.exact: dict[str, tuple[dict, str, bool]] = {}  # key -> (entry, kind, requires_caps)
        self.fuzzy_first: dict[str, list] = {}              # phone(first word) -> [(key, n, entry)]
        self.fuzzy_last: dict[str, list] = {}
        self.max_words = 1
        max_words = int(config.POSTPROC_MAX_PHRASE_WORDS)
        for e in entries:
            forms = ([(e["canonical"], "canonical")]
                     + [(v, "variant") for v in e.get("variants", [])]
                     + [(m, "misrecognition") for m in e.get("misrecognitions", [])])
            for surface, kind in forms:
                key = match_key(surface)
                n = len(key.split())
                if not key or n > max_words or len(key.replace(" ", "")) < 2:
                    continue
                if n == 1 and key in _COMMON_WORDS and not surface.isupper():
                    continue
                # short all-caps variants ("SC", "FLP", "ME") only match capitalized text,
                # so "who" never becomes the World Health Organization but "WHO" still does
                requires_caps = n == 1 and ((len(key) <= 4 and surface.isupper())
                                            or key in _COMMON_WORDS)
                self.max_words = max(self.max_words, n)
                # canonical > misrecognition > variant when two entries claim one
                # key; ties go to the entity seen in more docs ("FLP" -> the org)
                prev = self.exact.get(key)
                rank = {"canonical": 2, "misrecognition": 1, "variant": 0}
                score = (rank[kind], int(e.get("doc_freq", 0)))
                if prev is None or score > (rank[prev[1]], int(prev[0].get("doc_freq", 0))):
                    self.exact[key] = (e, kind, requires_caps)
                if (len(key.replace(" ", "")) >= int(config.POSTPROC_FUZZY_MIN_CHARS)
                        and int(e.get("doc_freq", 0)) >= int(config.POSTPROC_FUZZY_MIN_DOC_FREQ)
                        and (key, id(e)) not in getattr(self, "_fuzzy_seen", set())):
                    self._fuzzy_seen = getattr(self, "_fuzzy_seen", set())
                    self._fuzzy_seen.add((key, id(e)))
                    words = key.split()
                    row = (key, n, e)
                    self.fuzzy_first.setdefault(phone_code(words[0]), []).append(row)
                    self.fuzzy_last.setdefault(phone_code(words[-1]), []).append(row)


_STATE: dict = {"index": None, "mtimes": None}


def _mtimes() -> tuple:
    out = []
    for p in (Path(config.ENTITY_DICT_PATH), Path(config.ENTITY_OVERRIDES_PATH)):
        try:
            out.append(p.stat().st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


def load(force: bool = False) -> EntityIndex:
    """Resident EntityIndex; reloads when the dict/overlay files change on disk."""
    mt = _mtimes()
    if force or _STATE["index"] is None or mt != _STATE["mtimes"]:
        entries = _resolve_entries(Path(config.ENTITY_DICT_PATH),
                                   Path(config.ENTITY_OVERRIDES_PATH))
        _STATE["index"] = EntityIndex(entries)
        _STATE["mtimes"] = mt
        print(f"[postproc] entity dictionary loaded: {len(entries)} entries, "
              f"{len(_STATE['index'].exact)} match keys", file=sys.stderr)
    return _STATE["index"]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _fold_equal(a: str, b: str) -> bool:
    return match_key(a) == match_key(b)


def _should_rewrite(kind: str, entry: dict, surface: str) -> bool:
    if kind in ("misrecognition", "fuzzy"):
        return True
    if entry["class"] == "case":
        return surface != entry["canonical"]  # exact citation formatting, always
    return _fold_equal(surface, entry["canonical"]) and surface != entry["canonical"]


def _exact_pass(toks, index: EntityIndex, taken):
    hits = []
    i = 0
    while i < len(toks):
        matched_n = 0
        for n in range(min(index.max_words, len(toks) - i), 0, -1):
            if any((i + j) in taken for j in range(n)):
                continue
            raw = " ".join(t[0] for t in toks[i:i + n])
            key = match_key(raw)
            got = index.exact.get(key)
            if got:
                entry, kind, requires_caps = got
                if requires_caps and any(c.islower() for c in raw):
                    continue
                hits.append((i, n, entry, kind, 1.0 if kind != "misrecognition" else 0.95))
                for j in range(n):
                    taken.add(i + j)
                matched_n = n
                break
        i += matched_n or 1
    return hits


def _fuzzy_pass(toks, index: EntityIndex, taken):
    ratio_min = float(config.POSTPROC_FUZZY_RATIO)
    min_chars = int(config.POSTPROC_FUZZY_MIN_CHARS)
    hits = []
    i = 0
    while i < len(toks):
        if i in taken:
            i += 1
            continue
        best = None  # (ratio, n, entry)
        for n in range(min(index.max_words + 1, len(toks) - i), 0, -1):
            if any((i + j) in taken for j in range(n)):
                continue  # a shorter window at this start may still be clear
            key = match_key(" ".join(t[0] for t in toks[i:i + n]))
            flat = key.replace(" ", "")
            if len(flat) < min_chars:
                continue
            words = key.split()
            cands = {id(r): r for r in index.fuzzy_first.get(phone_code(words[0]), [])}
            for r in index.fuzzy_last.get(phone_code(words[-1]), []):
                cands.setdefault(id(r), r)
            for ckey, cn, entry in cands.values():
                if abs(cn - n) > 1:
                    continue
                cflat = ckey.replace(" ", "")
                if abs(len(cflat) - len(flat)) > max(3, int(0.3 * len(cflat))):
                    continue
                sm = difflib.SequenceMatcher(None, flat, cflat)
                if sm.real_quick_ratio() < ratio_min:
                    continue
                r = sm.ratio()
                if r >= ratio_min and (best is None or r > best[0]):
                    best = (r, n, entry)
        if best and match_key(" ".join(t[0] for t in toks[i:i + best[1]])) != match_key(best[2]["canonical"]):
            ratio, n, entry = best
            hits.append((i, n, entry, "fuzzy", round(ratio, 3)))
            for j in range(n):
                taken.add(i + j)
            i += n
        else:
            i += 1
    return hits


def _audit(records: list[dict]):
    path = str(getattr(config, "POSTPROC_LOG_PATH", "") or "")
    if not path or not records:
        return
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    except OSError as exc:  # auditing must never break the voice path
        print(f"[postproc] audit log write failed: {exc}", file=sys.stderr)


def annotate(text: str, source: str = "asr") -> dict:
    """NER + correction over one utterance/sentence. Pure str-in, dict-out."""
    index = load()
    toks = _tokens(text)
    taken: set[int] = set()
    raw_hits = _exact_pass(toks, index, taken)
    if source == "asr":  # composer output is model text, not mishears — no fuzzy rewrite
        raw_hits += _fuzzy_pass(toks, index, taken)

    entities = []
    for i, n, entry, kind, conf in sorted(raw_hits):
        start, end = toks[i][1], toks[i + n - 1][2]
        surface = text[start:end]
        entities.append({
            "surface": surface,
            "canonical": entry["canonical"],
            "class": entry["class"],
            "span": [start, end],
            "confidence": conf,
            "kind": kind,
            "corrected": _should_rewrite(kind, entry, surface),
        })

    corrected = text
    for ent in sorted(entities, key=lambda e: -e["span"][0]):
        if ent["corrected"]:
            s, e = ent["span"]
            repl = ent["canonical"]
            # keep the speaker's possessive: "Corona's impeachment" must survive rewrite
            m = re.search(r"['’]s?$", ent["surface"])
            if m and not re.search(r"['’]s?$", repl):
                repl += m.group(0)
            corrected = corrected[:s] + repl + corrected[e:]

    corrections = [e for e in entities if e["corrected"]]
    _audit([{
        "ts": round(time.time(), 3), "source": source,
        "surface": e["surface"], "canonical": e["canonical"], "class": e["class"],
        "kind": e["kind"], "confidence": e["confidence"],
    } for e in corrections])
    return {"text": corrected, "source": source, "entities": entities,
            "corrections": corrections}


# ---------------------------------------------------------------------------
# Dark wrappers — the only functions the voice path calls
# ---------------------------------------------------------------------------


def process_transcript(text: str) -> str:
    """ASR seam. POSTPROC_ENABLED=False -> byte-identical passthrough."""
    if not getattr(config, "POSTPROC_ENABLED", False) or not text:
        return text
    try:
        return annotate(text, source="asr")["text"]
    except Exception as exc:  # never let post-processing kill a turn
        print(f"[postproc] transcript pass failed open: {exc}", file=sys.stderr)
        return text


def process_tts_sentence(text: str) -> str:
    """Composer-output seam, called per streamed sentence (TTFA-safe)."""
    if not getattr(config, "POSTPROC_ENABLED", False) or not text:
        return text
    try:
        return annotate(text, source="llm")["text"]
    except Exception as exc:
        print(f"[postproc] llm pass failed open: {exc}", file=sys.stderr)
        return text
