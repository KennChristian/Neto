"""
Generate paired .md + .json corpus files for the CJ Panganiban knowledge base.

Reads curated CSVs from data/csv/ and matching source .txt files from data/text/.
Writes one .md + .json pair per row into corpus/{type}/{theme_folder}/.

Usage:
    python scripts/generate_corpus_files.py
    python scripts/generate_corpus_files.py --dry-run
    python scripts/generate_corpus_files.py --type columns --verbose
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_CSV_DIR = PROJECT_ROOT / "data" / "csv"
SOURCE_TEXT_DIR = PROJECT_ROOT / "data" / "text"
OUTPUT_ROOT = PROJECT_ROOT / "corpus"
REPORTS_DIR = PROJECT_ROOT / "reports"

ID_REGEX = re.compile(r"^([SCG])([A-E])(\d+)$")

THEME_LABELS = {
    "A": "Liberty and Rule of Law",
    "B": "Prosperity and Economic Philosophy",
    "C": "Biographical and Personal",
    "D": "FLP Mission and Foundation",
    "E": "Signature Current Events Commentary",
}

THEME_FOLDERS = {
    "A": "A_liberty_rule_of_law",
    "B": "B_prosperity_economic_philosophy",
    "C": "C_biographical_personal",
    "D": "D_flp_mission_foundation",
    "E": "E_current_events_commentary",
}

TYPE_FOLDERS = {"S": "speeches", "C": "columns", "G": "biography"}
TYPE_LABELS = {"S": "speech", "C": "column", "G": "biography"}

RETRIEVABLE_FOR = {
    "A": ["legal_education", "opinions"],
    "B": ["legal_education", "opinions"],
    "C": ["biography"],
    "D": ["biography", "opinions"],
    "E": ["opinions"],
}

ROUTING_PRIMARY_INTENT = {
    "A": ["legal_education", "opinions"],
    "B": ["legal_education", "opinions"],
    "C": ["biography"],
    "D": ["biography", "institutional"],
    "E": ["opinions"],
}

CSV_FILENAME_TO_TYPE = {
    "cjp_columns_curated.csv": "C",
    "cjp_speeches_curated.csv": "S",
    "cjp_biography_curated.csv": "G",
}

EMOTION_VOCAB = {
    "solemn", "grateful", "reverent", "celebratory", "valedictory",
    "thanksgiving", "doxological", "warm", "tender", "playful",
    "humorous", "wry", "ironic", "indignant", "diplomatic", "sober",
    "pedagogical", "reflective", "elegiac", "joyful", "compassionate",
    "pastoral", "ceremonial", "polemical", "earnest", "intimate",
}

JSON_CELL_COLUMNS = {
    "Keyword/s",
    "primary_topics",
    "sub_topics",
    "signature_phrases",
    "entities",
    "stances",
    "notable_anecdotes",
    "target_audience",
    "register_markers",
    "decision_framework_signals",
}


@dataclass
class ProcessResult:
    article_code: str | None = None
    canonical_id: str | None = None
    status: str = "ok"  # ok | skipped | warned
    message: str = ""
    text_was_placeholder: bool = False
    type_letter: str | None = None
    theme: str | None = None


@dataclass
class RunStats:
    total_rows: int = 0
    successful: int = 0
    skipped: int = 0
    missing_text_placeholders: int = 0
    by_type_and_theme: dict[str, dict[str, int]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # PLAN-0007 §5: first-of-each-stratum samples, captured during write.
    # Keyed by type_letter ("S" / "C" / "G"); value is (id, body_first_chars).
    stratum_samples: dict[str, tuple[str, str]] = field(default_factory=dict)


def read_csv_robust(path: Path) -> tuple[list[dict[str, str]], str]:
    """
    Read a CSV trying common encodings. Returns (rows, encoding_used).

    Falls back to cp1252 with errors='replace' for files that have a few
    undefined bytes — that way em-dashes / smart quotes still decode correctly
    and only the truly unmappable bytes get replaced with U+FFFD. Plain
    `latin-1` is avoided as a final fallback because it lets control bytes
    like 0x97 through into the output and breaks YAML.
    """
    for enc in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                rows = list(csv.DictReader(f))
            return rows, enc
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="cp1252", errors="replace", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows, "cp1252+replace"


def normalize_article_code(raw: str) -> str | None:
    """
    Canonicalise a CSV article code into the form `^[SCG][A-E]\\d{3,}$`.

    Handles common data-entry mistakes:
      - lowercase letters
      - stray whitespace
      - `O` (letter) in place of `0` (digit) in the number portion
      - shorter number portions (zero-pads to 3 digits minimum)

    Returns the canonical code or None if it cannot be coerced.
    """
    if raw is None:
        return None
    code = raw.strip().upper()
    if not code:
        return None
    if len(code) < 3:
        return None
    type_letter, theme_letter, tail = code[0], code[1], code[2:]
    if type_letter not in TYPE_FOLDERS or theme_letter not in THEME_LABELS:
        return None
    # In the number portion, treat letter O as digit 0 (common typo).
    tail_fixed = tail.replace("O", "0")
    if not tail_fixed.isdigit():
        return None
    try:
        number = int(tail_fixed)
    except ValueError:
        return None
    if number <= 0:
        return None
    width = max(3, len(tail_fixed))
    return f"{type_letter}{theme_letter}{number:0{width}d}"


DATE_FORMATS = (
    "%Y-%m-%d",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d %B %Y",
    "%d %b %Y",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%Y/%m/%d",
)


def parse_date(raw: str) -> str | None:
    """Parse a date cell and return ISO YYYY-MM-DD, or None."""
    if raw is None:
        return None
    s = raw.strip()
    if not s or s.lower() in {"[not specified]", "not specified", "n/a", "na", "tbd"}:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _split_semicolon_list(s: str) -> list[str]:
    """Split a semicolon-separated string into trimmed, non-empty pieces."""
    return [piece.strip() for piece in s.split(";") if piece.strip()]


def safe_json_parse(
    cell: str, default: Any, expect: str = "list"
) -> tuple[Any, str | None]:
    """
    Parse a JSON-encoded cell with permissive fallbacks.

    `expect` is one of {"list", "object", "list_of_strings"}. When the cell is
    not valid JSON, fall back to:
      - "" / N/A markers → default
      - JSON-looking text → return default and emit a warning
      - free text with ';' separators → split into a list of strings (when
        expect is "list" or "list_of_strings")
      - any other free text → single-element list of the trimmed string (lists)
        or default (objects), with a warning

    Returns (value, warning_or_None). Warnings let the row succeed with a note.
    """
    if cell is None:
        return default, None
    s = cell.strip()
    if not s:
        return default, None
    if s.lower() in {"n/a", "na", "none", "null", "tbd", "[not specified]"}:
        return default, None
    try:
        return json.loads(s), None
    except json.JSONDecodeError as e:
        msg = f"JSON parse failed ({e.msg} at col {e.colno}); used fallback"
        if expect == "object":
            return default, msg
        # Treat as a list.
        if ";" in s:
            return _split_semicolon_list(s), msg
        return [s], msg


def find_source_text(article_code: str) -> Path | None:
    """Locate the .txt file whose filename contains the article code substring."""
    pattern = str(SOURCE_TEXT_DIR / f"{article_code}*.txt")
    matches = sorted(glob.glob(pattern))
    if not matches:
        # Try without zero-padding (e.g., CA001 also matches CA01).
        m = ID_REGEX.match(article_code)
        if m:
            unpadded = f"{m.group(1)}{m.group(2)}{int(m.group(3))}"
            matches = sorted(glob.glob(str(SOURCE_TEXT_DIR / f"{unpadded}*.txt")))
    if not matches:
        return None
    return Path(matches[0])


_HEADER_KEY_RE = re.compile(
    r"^\s*(Date|Publisher|Source|By|Title|Author|Venue|Occasion)\s*:",
    re.IGNORECASE,
)


def normalize_body(raw: str, title: str | None = None) -> str:
    """Strip the metadata header block from a source .txt and clean whitespace.

    Handles two formats:
      - speech / biography .txt: metadata block ends with a `---` line.
      - column .txt: no `---`; metadata is the first few `Key: value` lines
        plus a `By: ...` byline.
    """
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"^---\s*$", raw, maxsplit=1, flags=re.MULTILINE)
    if len(parts) == 2:
        body = parts[1]
    else:
        # Strip leading title line + contiguous `Key: value` / `By: ...` lines
        # + blank lines. Stop at the first non-header, non-blank line.
        lines = raw.split("\n")
        idx = 0
        # Skip leading blanks.
        while idx < len(lines) and not lines[idx].strip():
            idx += 1
        # Optional title line: matches the supplied title (case-insensitive).
        if title and idx < len(lines):
            if lines[idx].strip().lower() == title.strip().lower():
                idx += 1
        # Header key:value lines and any blank padding around them.
        while idx < len(lines):
            stripped = lines[idx].strip()
            if not stripped:
                idx += 1
                continue
            if _HEADER_KEY_RE.match(stripped):
                idx += 1
                continue
            break
        body = "\n".join(lines[idx:])

    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    return body


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


# Common Tagalog markers used by CJP.
TAGALOG_MARKERS = re.compile(
    r"\b("
    r"po|opo|ako|ikaw|kayo|tayo|sila|ang|ng|sa|naman|talaga|kasi|pero|"
    r"salamat|maraming|magandang|mabuhay|kababayan|kapatid|atin|natin|"
    r"hindi|wala|meron|mayroon|bagay|tikum|bibig|barkada|chismosos|marites|"
    r"tagumpay|nating|lahat|bagong|bayani|haligi|pasalubong|tiendesitas|"
    r"moro-moro"
    r")\b",
    re.IGNORECASE,
)


def detect_languages(text: str) -> tuple[list[str], bool]:
    """Return (languages_list, code_switching_flag)."""
    languages = ["English"]
    has_tagalog = bool(TAGALOG_MARKERS.search(text))
    if has_tagalog:
        languages.append("Tagalog")
    return languages, has_tagalog


def extract_speech_metadata(raw_text: str) -> dict[str, str]:
    """
    Best-effort extraction of speech-only metadata from the .txt header block
    (the section above `---`). Returns whichever fields could be identified.
    """
    head = raw_text.split("---", 1)[0]
    meta: dict[str, str] = {}

    pub_m = re.search(r"Publisher:\s*(.+?)\s*$", head, re.MULTILINE)
    if pub_m:
        val = pub_m.group(1).strip()
        if val and val.lower() not in {"[not specified]", "not specified"}:
            meta["publisher"] = val

    # Descriptive line tends to sit after the metadata block — pick the longest
    # non-`Key: value` line as the occasion sentence.
    candidates = [
        ln.strip()
        for ln in head.splitlines()
        if ln.strip()
        and not re.match(r"^(Date|Publisher|Source|By):", ln.strip())
        and len(ln.strip()) > 40
    ]
    if candidates:
        meta["occasion_raw"] = max(candidates, key=len)

    return meta


def derive_voice_register(register_markers: list[str]) -> list[str]:
    """Extract registry-style descriptors from register_markers."""
    out: list[str] = []
    for marker in register_markers or []:
        m_text = marker.lower()
        # Pull "<word>_register" or "<word> register" leading tokens.
        m = re.match(r"([\w\-]+)(?:\s+register|_register|-register)", m_text)
        if m:
            out.append(m.group(1).replace("_", "-"))
            continue
        # Hyphenated compounds like "valedictory-as-handover" -> first word.
        first = re.split(r"[\s\-_]", m_text, maxsplit=1)[0]
        if first and first not in out:
            out.append(first)
    return out[:6]


def derive_emotional_register(register_markers: list[str]) -> list[str]:
    """Pick emotion tone words from register_markers."""
    out: list[str] = []
    for marker in register_markers or []:
        for token in re.findall(r"[a-zA-Z]+", marker.lower()):
            if token in EMOTION_VOCAB and token not in out:
                out.append(token)
    return out


def yaml_quote(val: str) -> str:
    """Quote a string for safe YAML emission."""
    s = str(val).replace("\\", "\\\\").replace("\"", "\\\"")
    return f"\"{s}\""


def yaml_list(items: list[str]) -> str:
    """Render a list inline for YAML."""
    return "[" + ", ".join(yaml_quote(i) for i in items) + "]"


def build_frontmatter(meta: dict[str, Any]) -> str:
    """Build YAML frontmatter from an ordered dict-like mapping."""
    lines = ["---"]
    for key, value in meta.items():
        if value is None:
            continue
        if isinstance(value, bool):
            lines.append(f"{key}: {'true' if value else 'false'}")
        elif isinstance(value, int):
            lines.append(f"{key}: {value}")
        elif isinstance(value, list):
            lines.append(f"{key}: {yaml_list([str(v) for v in value])}")
        else:
            text = str(value).strip()
            if not text:
                continue
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                lines.append(f"{key}: {text}")
            else:
                lines.append(f"{key}: {yaml_quote(text)}")
    lines.append("---")
    return "\n".join(lines)


def wrap_signature_phrases(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or []:
        if isinstance(item, dict):
            base = {
                "phrase": item.get("phrase", ""),
                "type": item.get("type", "tbd"),
                "voice_marker": item.get("voice_marker", True),
                "reusable": item.get("reusable", True),
                "context": item.get("context", ""),
            }
        else:
            base = {
                "phrase": str(item),
                "type": "tbd",
                "voice_marker": True,
                "reusable": True,
                "context": "",
            }
        out.append(base)
    return out


def wrap_notable_anecdotes(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or []:
        if isinstance(item, dict):
            base = {
                "summary": item.get("summary", ""),
                "characters": item.get("characters", []),
                "deployable_when": item.get("deployable_when", []),
                "tone": item.get("tone", "tbd"),
                "length": item.get("length", "tbd"),
                "deployable_in_solemn_register": item.get(
                    "deployable_in_solemn_register", False
                ),
            }
        else:
            base = {
                "summary": str(item),
                "characters": [],
                "deployable_when": [],
                "tone": "tbd",
                "length": "tbd",
                "deployable_in_solemn_register": False,
            }
        out.append(base)
    return out


def enrich_stances(items: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        enriched = dict(item)
        enriched.setdefault("domain", "")
        enriched.setdefault("would_repeat_today", None)
        out.append(enriched)
    return out


def normalise_entities(raw: Any) -> dict[str, list[str]]:
    base = {
        "people": [],
        "institutions": [],
        "cases": [],
        "laws_treaties": [],
        "events": [],
    }
    if isinstance(raw, dict):
        for k in base.keys():
            v = raw.get(k, [])
            if isinstance(v, list):
                base[k] = [str(x) for x in v]
    return base


def process_row(
    row: dict[str, str],
    csv_path: Path,
    line_no: int,
    expected_type: str | None,
    stats: RunStats,
    verbose: bool,
) -> tuple[ProcessResult, dict[str, Any] | None, str | None]:
    """Validate a CSV row and build the .md/.json payloads in memory."""
    result = ProcessResult(article_code=(row.get("Article Code") or "").strip())

    canonical_id = normalize_article_code(result.article_code or "")
    # Per PLAN-0007 §5: when normalisation actually changes the code, log it
    # so the curator notices drifting CSV conventions.
    if (
        canonical_id
        and result.article_code
        and canonical_id != result.article_code.strip().upper()
    ):
        diff_note = f"{result.article_code} → {canonical_id}"
        stats.warnings.append(
            f"{csv_path.name}:{line_no} INFO normalised Article Code: {diff_note}"
        )
        if verbose:
            print(f"  [   norm] {diff_note}")
    if not canonical_id:
        result.status = "skipped"
        result.message = (
            f"invalid Article Code '{result.article_code}' "
            f"(must match ^[SCG][A-E]\\d+$ after normalisation)"
        )
        stats.errors.append(f"{csv_path.name}:{line_no} SKIP {result.message}")
        return result, None, None
    result.canonical_id = canonical_id
    result.type_letter = canonical_id[0]
    result.theme = canonical_id[1]

    if expected_type and result.type_letter != expected_type:
        result.status = "skipped"
        result.message = (
            f"type mismatch: file implies '{expected_type}' but code is "
            f"'{result.type_letter}' ({canonical_id})"
        )
        stats.errors.append(f"{csv_path.name}:{line_no} SKIP {result.message}")
        return result, None, None

    title = (row.get("Title") or "").strip()
    if not title:
        result.status = "skipped"
        result.message = f"missing Title for {canonical_id}"
        stats.errors.append(f"{csv_path.name}:{line_no} SKIP {result.message}")
        return result, None, None

    date_iso = parse_date(row.get("Date") or "")
    if not date_iso:
        result.status = "skipped"
        result.message = (
            f"missing or unparseable Date '{row.get('Date')}' for {canonical_id}"
        )
        stats.errors.append(f"{csv_path.name}:{line_no} SKIP {result.message}")
        return result, None, None
    year = int(date_iso[:4])

    # Parse JSON-encoded columns. Permissive: fall back to semicolon-splitting
    # or single-item lists when cells are not valid JSON, and log a warning
    # rather than skipping the row.
    parsed: dict[str, Any] = {}
    json_defaults: dict[str, tuple[Any, str]] = {
        "Keyword/s": ([], "list_of_strings"),
        "primary_topics": ([], "list_of_strings"),
        "sub_topics": ([], "list_of_strings"),
        "signature_phrases": ([], "list"),
        "entities": ({}, "object"),
        "stances": ([], "list"),
        "notable_anecdotes": ([], "list"),
        "target_audience": ([], "list_of_strings"),
        "register_markers": ([], "list_of_strings"),
        "decision_framework_signals": ([], "list_of_strings"),
    }
    json_warnings: list[str] = []
    for col, (default, expect) in json_defaults.items():
        value, warn = safe_json_parse(row.get(col, ""), default, expect=expect)
        parsed[col] = value
        if warn:
            json_warnings.append(f"{col}: {warn}")
    if json_warnings:
        stats.warnings.append(
            f"{csv_path.name}:{line_no} WARN {canonical_id} — "
            + "; ".join(json_warnings)
        )

    # Locate source text.
    txt_path = find_source_text(canonical_id)
    if txt_path is None:
        body = "<!-- TEXT TO BE INSERTED -->"
        orig_filename = ""
        word_count = 0
        languages, code_switching = ["English"], False
        speech_meta: dict[str, str] = {}
        result.text_was_placeholder = True
        stats.warnings.append(
            f"{csv_path.name}:{line_no} WARN no source .txt found for {canonical_id}"
        )
        result.status = "warned"
        result.message = "missing source .txt — body placeholder inserted"
    else:
        with open(txt_path, "r", encoding="utf-8", errors="replace") as f:
            raw_text = f.read()
        body = normalize_body(raw_text, title=title)
        orig_filename = txt_path.name
        word_count = count_words(body)
        languages, code_switching = detect_languages(body)
        speech_meta = (
            extract_speech_metadata(raw_text)
            if result.type_letter == "S"
            else {"publisher": ""}
        )

    # Build frontmatter.
    type_label = TYPE_LABELS[result.type_letter]
    theme_label = THEME_LABELS[result.theme]
    number_int = int(re.sub(r"^[SCG][A-E]", "", canonical_id))

    voice_register = derive_voice_register(parsed["register_markers"])

    publisher = speech_meta.get("publisher") or ""
    if not publisher:
        if result.type_letter == "C":
            publisher = "Philippine Daily Inquirer"
        else:
            publisher = "cjpanganiban.com"

    occasion_raw = speech_meta.get("occasion_raw", "")

    frontmatter_meta: dict[str, Any] = {
        "id": canonical_id,
        "type": type_label,
        "theme": result.theme,
        "theme_label": theme_label,
        "number": number_int,
        "title": title,
        "date": date_iso,
        "year": year,
    }
    if result.type_letter == "S":
        if occasion_raw:
            frontmatter_meta["occasion"] = occasion_raw
    frontmatter_meta["publisher"] = publisher
    if row.get("Link"):
        frontmatter_meta["source_url"] = (row.get("Link") or "").strip()
    frontmatter_meta["author"] = "Artemio V. Panganiban"
    if result.type_letter == "S":
        frontmatter_meta["role_at_delivery"] = ""
    frontmatter_meta["voice_register"] = voice_register
    frontmatter_meta["language"] = languages
    frontmatter_meta["code_switching"] = code_switching
    frontmatter_meta["word_count"] = word_count
    frontmatter_meta["retrievable_for"] = RETRIEVABLE_FOR[result.theme]
    frontmatter_meta["orig_filename"] = orig_filename

    # Speech-only fields default to empty strings when we cannot extract them
    # automatically — keep them out of frontmatter when blank so the schema
    # stays clean per spec ("omit otherwise").
    if frontmatter_meta.get("role_at_delivery") == "":
        del frontmatter_meta["role_at_delivery"]

    frontmatter = build_frontmatter(frontmatter_meta)
    md_text = f"{frontmatter}\n\n# {title}\n\n{body}\n"

    # Build JSON record.
    json_record: dict[str, Any] = {
        "id": canonical_id,
        "type": type_label,
        "theme": result.theme,
        "theme_label": theme_label,
        "number": number_int,
        "title": title,
        "date": date_iso,
        "year": year,
        "source_url": (row.get("Link") or "").strip(),
        "routing": {
            "primary_intent": ROUTING_PRIMARY_INTENT[result.theme],
            "secondary_intent": [],
            "audience_match": [str(x) for x in parsed["target_audience"]],
            "complexity": "medium",
            "emotional_register": derive_emotional_register(parsed["register_markers"]),
        },
        "topic_paths": {"primary": [], "secondary": []},
        "keywords": [str(x) for x in parsed["Keyword/s"]],
        "primary_topics": [str(x) for x in parsed["primary_topics"]],
        "sub_topics": [str(x) for x in parsed["sub_topics"]],
        "signature_phrases": wrap_signature_phrases(parsed["signature_phrases"]),
        "entities": normalise_entities(parsed["entities"]),
        "stances": enrich_stances(parsed["stances"]),
        "notable_anecdotes": wrap_notable_anecdotes(parsed["notable_anecdotes"]),
        "decision_framework_signals": [
            str(x) for x in parsed["decision_framework_signals"]
        ],
        "target_audience": [str(x) for x in parsed["target_audience"]],
        "register_markers": [str(x) for x in parsed["register_markers"]],
        "one_paragraph_summary": (row.get("one_paragraph_summary") or "").strip(),
    }

    if verbose:
        print(
            f"  [{result.status:>6}] {canonical_id} → "
            f"{TYPE_FOLDERS[result.type_letter]}/{THEME_FOLDERS[result.theme]}"
            + (" (placeholder text)" if result.text_was_placeholder else "")
        )

    return result, json_record, md_text


def write_outputs(
    result: ProcessResult,
    json_record: dict[str, Any],
    md_text: str,
    dry_run: bool,
) -> tuple[Path, Path]:
    """Write the .md and .json files. Returns the two paths written."""
    assert result.canonical_id and result.type_letter and result.theme
    type_dir = TYPE_FOLDERS[result.type_letter]
    theme_dir = THEME_FOLDERS[result.theme]
    out_dir = OUTPUT_ROOT / type_dir / theme_dir
    md_path = out_dir / f"{result.canonical_id}.md"
    json_path = out_dir / f"{result.canonical_id}.json"
    if dry_run:
        return md_path, json_path
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(md_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(md_text)
    with open(json_path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(json_record, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return md_path, json_path


def detect_type_from_csv_path(csv_path: Path) -> str | None:
    return CSV_FILENAME_TO_TYPE.get(csv_path.name)


def process_csv(
    csv_path: Path,
    stats: RunStats,
    verbose: bool,
    dry_run: bool,
    type_filter: str | None,
) -> None:
    expected_type = detect_type_from_csv_path(csv_path)
    if type_filter and expected_type and TYPE_FOLDERS[expected_type] != type_filter:
        return
    rows, encoding = read_csv_robust(csv_path)
    print(
        f"[ingest] {csv_path.name}: {len(rows)} rows (encoding={encoding}, "
        f"expected_type={expected_type or 'auto'})"
    )
    for i, row in enumerate(rows, start=2):  # line 1 is header
        stats.total_rows += 1
        result, json_record, md_text = process_row(
            row, csv_path, i, expected_type, stats, verbose
        )
        if result.status == "skipped":
            stats.skipped += 1
            continue
        assert json_record is not None and md_text is not None
        if result.text_was_placeholder:
            stats.missing_text_placeholders += 1
        write_outputs(result, json_record, md_text, dry_run)
        type_key = TYPE_FOLDERS[result.type_letter]  # type: ignore[index]
        stats.by_type_and_theme.setdefault(type_key, {})
        stats.by_type_and_theme[type_key].setdefault(result.theme, 0)  # type: ignore[arg-type]
        stats.by_type_and_theme[type_key][result.theme] += 1  # type: ignore[index]
        stats.successful += 1
        # PLAN-0007 §5: capture the first row of each type as a stratum sample.
        if (
            result.type_letter
            and result.canonical_id
            and result.type_letter not in stats.stratum_samples
        ):
            # Slice the body section (after the title line) for the sample.
            try:
                body_idx = md_text.index("\n# ")
                body = md_text[body_idx:].split("\n\n", 2)
                body_excerpt = (body[2] if len(body) > 2 else body[-1]).strip()
            except ValueError:
                body_excerpt = md_text
            stats.stratum_samples[result.type_letter] = (
                result.canonical_id,
                body_excerpt[:80].replace("\n", " "),
            )


def write_reports(stats: RunStats, dry_run: bool) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "total_rows_processed": stats.total_rows,
        "successful_generations": stats.successful,
        "skipped_rows": stats.skipped,
        "missing_text_placeholders": stats.missing_text_placeholders,
        "by_type_and_theme": stats.by_type_and_theme,
    }
    with open(REPORTS_DIR / "generation_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        f.write("\n")

    log_lines: list[str] = []
    if stats.errors:
        log_lines.append("# ERRORS (rows skipped)")
        log_lines.extend(stats.errors)
        log_lines.append("")
    if stats.warnings:
        log_lines.append("# WARNINGS (row generated with notice)")
        log_lines.extend(stats.warnings)
        log_lines.append("")
    if not log_lines:
        log_lines.append("# No anomalies recorded.")
    with open(REPORTS_DIR / "validation_errors.log", "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines).rstrip() + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate without writing")
    parser.add_argument("--verbose", action="store_true", help="print each row processed")
    parser.add_argument(
        "--type",
        choices=list(TYPE_FOLDERS.values()),
        help="process only one document type",
    )
    parser.add_argument(
        "--with-topic-paths",
        action="store_true",
        help=(
            "after writing .md/.json, rebuild corpus/voice/topic_map.json "
            "and backfill topic_paths in every generated .json"
        ),
    )
    args = parser.parse_args(argv)

    if not INPUT_CSV_DIR.is_dir():
        print(f"ERROR: input CSV directory not found: {INPUT_CSV_DIR}", file=sys.stderr)
        return 2

    stats = RunStats()
    csv_paths = sorted(INPUT_CSV_DIR.glob("*.csv"))
    if not csv_paths:
        print(f"ERROR: no CSVs found in {INPUT_CSV_DIR}", file=sys.stderr)
        return 2

    for csv_path in csv_paths:
        process_csv(csv_path, stats, args.verbose, args.dry_run, args.type)

    write_reports(stats, args.dry_run)

    if args.with_topic_paths and not args.dry_run:
        print()
        print("[topic-map] rebuilding corpus/voice/topic_map.json and "
              "backfilling topic_paths …")
        import subprocess
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name("build_topic_map.py"))],
            check=True,
        )
        subprocess.run(
            [sys.executable, str(Path(__file__).with_name("apply_topic_paths.py"))],
            check=True,
        )

    print()
    print("[summary]")
    print(f"  total rows processed     : {stats.total_rows}")
    print(f"  successful generations   : {stats.successful}")
    print(f"  skipped rows             : {stats.skipped}")
    print(f"  missing-text placeholders: {stats.missing_text_placeholders}")
    print(f"  by type/theme            : {stats.by_type_and_theme}")
    print(f"  dry_run                  : {args.dry_run}")
    print(f"  report                   : {REPORTS_DIR / 'generation_report.json'}")
    print(f"  log                      : {REPORTS_DIR / 'validation_errors.log'}")
    # PLAN-0007 §5: first-of-each-stratum samples for cross-type sanity check.
    if stats.stratum_samples:
        print()
        print("[sample]")
        for letter in ("S", "C", "G"):
            if letter in stats.stratum_samples:
                sid, excerpt = stats.stratum_samples[letter]
                label = TYPE_LABELS[letter]
                print(f"  {sid} ({label:9s}): {excerpt!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
