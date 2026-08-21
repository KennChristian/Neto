"""
Reference implementation: CJ Panganiban conversation app.

Pipeline: faster-whisper (STT) → Claude Haiku router → Claude Sonnet inference → Piper (TTS)

This is a runnable skeleton. Adapt the audio I/O to your demo environment
(mic + speakers, push-to-talk button, web UI, etc).

DEPENDENCIES:
    pip install anthropic faster-whisper sounddevice numpy webrtcvad

    For Piper TTS, download the binary from:
        https://github.com/rhasspy/piper/releases
    And the voice model (suggest en_US-ryan-high) from:
        https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US/ryan/high

ENVIRONMENT:
    export ANTHROPIC_API_KEY="sk-ant-..."

    Optional path overrides (defaults shown):
        CORPUS_ROOT   = ../corpus       (relative to this app/ directory)
        VOICE_DIR     = ../corpus/voice
        ROUTER_PROMPT = ./artifacts/router_prompt.md
                                       (legacy location until PLAN-0001 §B
                                        replaces it with corpus/voice/router_prompt.md)

ARTIFACTS — loaded from the locations above:
    - {VOICE_DIR}/topic_map.json
    - {VOICE_DIR}/voice_card.md
    - {ROUTER_PROMPT}
    - {CORPUS_ROOT}/{type}/{theme_folder}/{id}.{md,json}
        (e.g., corpus/speeches/A_liberty_rule_of_law/SA136.json)

USAGE:
    python cj_chat.py                  # interactive mode (push-to-talk)
    python cj_chat.py --text "..."     # text-only test (skip STT/TTS)
"""

import os
import json
import sys
import subprocess
import tempfile
import argparse
import re
from dataclasses import dataclass
from pathlib import Path

# Load .env from several plausible locations before importing Anthropic
# so the SDK picks up the key regardless of where the user keeps the
# file. Search order (lowest to highest precedence — later overrides):
#     cwd/.env  →  <repo>/.env  →  <repo>/app/.env
# A custom path can override every default via the DOTENV_PATH env var.
_LOADED_DOTENVS: list[str] = []
try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]

    _app_dir = Path(__file__).resolve().parent
    _repo_root = _app_dir.parent
    _candidates = []
    custom = os.environ.get("DOTENV_PATH")
    if custom:
        _candidates.append(Path(custom).expanduser().resolve())
    _candidates.extend([
        Path.cwd() / ".env",
        _repo_root / ".env",
        _app_dir / ".env",
    ])
    # Deduplicate while preserving order.
    seen: set[str] = set()
    for env_path in _candidates:
        key = str(env_path)
        if key in seen:
            continue
        seen.add(key)
        if env_path.exists() and env_path.is_file():
            load_dotenv(env_path, override=True)
            _LOADED_DOTENVS.append(str(env_path))
except ImportError:
    pass  # dotenv is optional — if not installed, fall back to real env vars

# Make stdout/stderr UTF-8 on Windows so the emoji prints don't crash.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from anthropic import Anthropic

# ============================================================
# Configuration
# ============================================================
# Models — overridable via env / .env so the user can pick the exact
# snapshot they want without code edits. Defaults match what the
# Phase 1-3 work was validated on (Haiku 4.5 for routing+gate+fidelity,
# Sonnet 4.6 for composition).
ROUTER_MODEL = os.environ.get("ROUTER_MODEL", "claude-haiku-4-5-20251001")
INFERENCE_MODEL = os.environ.get("INFERENCE_MODEL", "claude-sonnet-4-6")

# Latency knobs (Pi voice deployment). Env-overridable; defaults favor a fast
# spoken turn: shorter answers and, on Sonnet, low effort (the server default
# is `high`, which spends far more time/tokens than a short persona answer needs).
COMPOSER_MAX_TOKENS = int(os.environ.get("CJ_COMPOSER_MAX_TOKENS", "220"))
# Router output cap (2026-08-21): the router emits ~100 tokens of compact JSON
# (reasoning is prompt-capped to one short clause); a tight cap just bounds
# runaway output. Do NOT set below ~140 — a truncated JSON parse falls back to
# rule_of_law/low-confidence routing.
ROUTER_MAX_TOKENS = int(os.environ.get("CJ_ROUTER_MAX_TOKENS", "300"))
COMPOSER_EFFORT = os.environ.get("CJ_COMPOSER_EFFORT", "low").strip()
SKIP_FIDELITY = os.environ.get("CJ_SKIP_FIDELITY", "").strip().lower() in {"1", "true", "yes", "on"}

# P1 dynamic token budget — kiosk (one-hot) variant. The develop pipeline computes
# a weighted budget over the theme probability vector; this branch has no centroid
# model, so the Haiku router's single routed topic picks its theme's budget from
# the dict below (the p=1 limit of the same formula). Defaults keep the kiosk's
# short-spoken-turn scale around the 220 base; META (identity probes) stays brief.
DYNAMIC_TOKENS_ENABLED = (
    os.environ.get("CJ_DYNAMIC_TOKENS_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"})
# THE dimension -> token-budget dict: one entry per routed TOPIC (the theme
# rollup was removed 2026-08-20, user-directed — matches develop's P1
# refactor). Seeded from the retired per-theme values via each topic's
# theme_anchor; every value is now independently tunable. Env override merges
# topic keys: CJ_TOKEN_BUDGET_BY_DIM='{"rule_of_law": 300}'. A topic missing
# from the table (e.g. after a taxonomy regen) gets TOKEN_BUDGET_DIM_DEFAULT.
_TOKEN_BUDGET_DEFAULT = {
    "rule_of_law": 260,
    "twin_beacons_doctrine": 240,
    "foundation_for_liberty_and_prosperity": 220,
    "with_due_respect_persona": 240,
    "constitutional_doctrine": 260,
    "due_process": 260,
    "judicial_reform": 260,
    "supreme_court_history": 260,
    "impeachment_accountability": 260,
    "international_law_disputes": 260,
    "icc_and_duterte": 260,
    "judicial_activism_and_political_question": 260,
    "asean_law_association": 260,
    "death_penalty_and_echegaray": 260,
    "bar_exam_and_legal_education": 260,
    "economic_governance_and_business_law": 240,
    "eez_resource_sovereignty": 240,
    "msme_and_entrepreneurship": 240,
    "family_and_marriage": 200,
    "mentors_and_legal_lineage": 200,
    "faith_journey": 200,
    "early_life_sampaloc": 200,
    "jbc_discernment_and_appointment": 200,
    "eulogies_and_passing": 200,
    "friendships_and_civic_circles": 200,
    "honors_received": 200,
    "flp_scholarship_programs": 220,
    "museum_for_liberty_and_prosperity": 220,
    "prosperity_fund_msme": 220,
    "flp_donors_and_partners": 220,
    "lawyer_ethics_initiative": 220,
    "ai_and_technology": 240,
    "global_geopolitics": 240,
    "philippine_political_landscape": 240,
    "robot_identity_meta": 120,
}
TOKEN_BUDGET_DIM_DEFAULT = int(os.environ.get("CJ_TOKEN_BUDGET_DIM_DEFAULT", "220"))
# Conversational tune-down (2026-08-21, user-directed): one scale multiplied
# into every budget for snappier back-and-forth (0.4 ≈ half-minute answers
# become ~25s; 1.0 = the published table unchanged). Below 1.0 the composer
# also receives a <length_note> so answers are WRITTEN short and end cleanly
# instead of being truncated at the cap.
try:
    TOKEN_BUDGET_SCALE = float(os.environ.get("CJ_TOKEN_BUDGET_SCALE", "1.0"))
except ValueError:
    TOKEN_BUDGET_SCALE = 1.0
TOKEN_BUDGET_MIN = int(os.environ.get("CJ_TOKEN_BUDGET_MIN", "60"))
try:
    TOKEN_BUDGET_BY_DIM = dict(_TOKEN_BUDGET_DEFAULT,
                               **json.loads(os.environ.get("CJ_TOKEN_BUDGET_BY_DIM", "{}")))
except (ValueError, TypeError):
    TOKEN_BUDGET_BY_DIM = dict(_TOKEN_BUDGET_DEFAULT)


def _topic_max_tokens(routing: dict, artifacts) -> int:
    """Composer cap for this turn: routed TOPIC's budget, or the fixed cap when
    dark/unroutable. Never raises — a budget bug must not kill a spoken turn."""
    if not DYNAMIC_TOKENS_ENABLED:
        return _scale_budget(COMPOSER_MAX_TOKENS)
    try:
        topic = routing["primary_topic"]
        budget = _scale_budget(int(TOKEN_BUDGET_BY_DIM.get(topic, TOKEN_BUDGET_DIM_DEFAULT)))
        print(f"[token-budget] dim={topic} scale={TOKEN_BUDGET_SCALE} -> max_tokens={budget}")
        return budget
    except Exception as e:
        print(f"[token-budget] fallback to fixed {COMPOSER_MAX_TOKENS}: {e}")
        return _scale_budget(COMPOSER_MAX_TOKENS)


def _scale_budget(budget: int) -> int:
    return max(TOKEN_BUDGET_MIN, int(budget * TOKEN_BUDGET_SCALE))


def _length_note(max_tokens: int) -> str:
    """Brevity cue appended to the composer's user turn when the budget is
    tuned down (TOKEN_BUDGET_SCALE < 1.0). The model must KNOW the ceiling,
    or it composes a full-length answer and the cap truncates it mid-arc.
    ~0.6 words/token leaves headroom below the hard cap (at 0.7 the live META
    turns wrote exactly to the cap and got sentence-trimmed); ~2.5 words/s."""
    if TOKEN_BUDGET_SCALE >= 1.0:
        return ""
    words = max(20, int(max_tokens * 0.6))
    return (
        f"\n\n<length_note>\nThis is a live spoken conversation. Reply in about "
        f"{words} words or fewer (~{max(10, int(words / 2.5))} seconds of speech): "
        f"make ONE focused point in voice, end on a complete sentence, and yield "
        f"the floor. Do not pad with preamble or summary.\n</length_note>")


_theme_max_tokens = _topic_max_tokens  # retired name — kept for any stale caller


def _composer_speed_kwargs() -> dict:
    """Extra kwargs for the composer call. Haiku 4.5 rejects the effort
    parameter, so send nothing there; on Sonnet 4.6+ disable thinking and
    pin effort (empty CJ_COMPOSER_EFFORT sends neither)."""
    if not COMPOSER_EFFORT or "haiku" in INFERENCE_MODEL:
        return {}
    return {"thinking": {"type": "disabled"},
            "output_config": {"effort": COMPOSER_EFFORT}}


# Per ADR-0011: doc IDs follow ^[SCG][A-E]\d+$. The first letter selects the
# corpus subdirectory; the second letter selects the theme subdirectory.
_TYPE_DIRS = {"S": "speeches", "C": "columns", "G": "biography"}
_THEME_DIRS = {
    "A": "A_liberty_rule_of_law",
    "B": "B_prosperity_economic_philosophy",
    "C": "C_biographical_personal",
    "D": "D_flp_mission_foundation",
    "E": "E_current_events_commentary",
}
_DOC_ID_RE = re.compile(r"^([SCG])([A-E])(\d+)$")


@dataclass
class Config:
    """Runtime paths. Defaults assume the app is run from the app/ directory
    or the repo root. Override any path via env var; see module docstring."""

    corpus_root: Path
    voice_dir: Path
    topic_map_path: Path
    voice_card_path: Path
    router_prompt_path: Path

    @classmethod
    def from_env(cls, app_dir: Path | None = None) -> "Config":
        app_dir = app_dir or Path(__file__).resolve().parent
        repo_root = app_dir.parent

        corpus_root = Path(
            os.environ.get("CORPUS_ROOT", repo_root / "corpus")
        ).resolve()
        voice_dir = Path(
            os.environ.get("VOICE_DIR", corpus_root / "voice")
        ).resolve()
        # PLAN-0001 §B: corpus/voice/router_prompt.md is the canonical
        # router prompt. ROUTER_PROMPT env var lets a caller point
        # somewhere else without code edits.
        env_router = os.environ.get("ROUTER_PROMPT")
        router_prompt_path = (
            Path(env_router).resolve() if env_router
            else (voice_dir / "router_prompt.md").resolve()
        )
        return cls(
            corpus_root=corpus_root,
            voice_dir=voice_dir,
            topic_map_path=voice_dir / "topic_map.json",
            voice_card_path=voice_dir / "voice_card.md",
            router_prompt_path=router_prompt_path,
        )


# Default configuration constructed at import time; tests and the dashboard
# may build their own Config and pass it into CorpusArtifacts directly.
DEFAULT_CONFIG = Config.from_env()

# Backwards-compatibility alias kept so `from cj_chat import ARTIFACTS_DIR`
# in app/dashboard.py keeps working. New code should accept a Config.
ARTIFACTS_DIR = DEFAULT_CONFIG.voice_dir

# Piper paths — set these to wherever you installed piper and the voice model
PIPER_BIN = os.environ.get("PIPER_BIN", "piper")
PIPER_VOICE = os.environ.get("PIPER_VOICE", "./voices/en_US-ryan-high.onnx")

# Whisper model size — "small" works for English; use "medium" if Filipino mix
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "medium")

# Audio
SAMPLE_RATE = 16000
RECORD_SECONDS_MAX = 30  # max utterance length before auto-cutoff


# ============================================================
# Anthropic client factory
# ============================================================
# Default SDK retry count is 2 with short backoff (~3s total). We bump to 4
# (~15s of internal retry with exponential backoff + jitter) so transient
# 529 "overloaded" errors and 429 rate-limits get retried automatically
# without the caller seeing a traceback. The SDK retries on connection
# errors, 408, 409, 429, and any 5xx — exactly the right set.
ANTHROPIC_MAX_RETRIES = 4


def make_client() -> Anthropic:
    """Return an Anthropic client with retry tuned for transient overload.

    Raises a clear RuntimeError before instantiation if no API key is
    visible — beats the SDK's cryptic 'Could not resolve authentication
    method' message and lets the dashboard render a remediation banner.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        loaded = ", ".join(_LOADED_DOTENVS) if _LOADED_DOTENVS else "(none found)"
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. The runtime searched these "
            f".env files: {loaded}. Add `ANTHROPIC_API_KEY=sk-ant-...` "
            "to one of: <repo>/app/.env, <repo>/.env, <cwd>/.env — or "
            "set DOTENV_PATH to point at a specific file."
        )
    return Anthropic(max_retries=ANTHROPIC_MAX_RETRIES)


def loaded_env_summary() -> dict[str, object]:
    """One-shot dict the dashboard / CLI can print to show what was
    loaded from .env and which models will be used. Cheap, side-effect
    free; suitable for sidebars."""
    return {
        "dotenv_files_loaded": list(_LOADED_DOTENVS),
        "api_key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "router_model": ROUTER_MODEL,
        "inference_model": INFERENCE_MODEL,
        "whisper_model": os.environ.get("WHISPER_MODEL", "medium"),
    }


# ============================================================
# Prompt cache observability
# ============================================================
# Anthropic returns cache_creation_input_tokens and cache_read_input_tokens
# on every response with a Usage object. We accumulate them so a session-end
# summary (or live dashboard panel) can show how much caching saved.
CACHE_STATS: dict[str, dict[str, int]] = {
    "router":    {"creation": 0, "read": 0, "regular_input": 0, "output": 0, "calls": 0},
    "inference": {"creation": 0, "read": 0, "regular_input": 0, "output": 0, "calls": 0},
}


def _log_cache_usage(label: str, usage) -> None:
    """Update CACHE_STATS and print a one-liner per call. Safe if Usage is
    missing fields (older SDK) — getattr defaults to 0."""
    creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    read     = getattr(usage, "cache_read_input_tokens", 0) or 0
    regular  = getattr(usage, "input_tokens", 0) or 0
    output   = getattr(usage, "output_tokens", 0) or 0
    s = CACHE_STATS.get(label)
    if s is not None:
        s["creation"]      += creation
        s["read"]          += read
        s["regular_input"] += regular
        s["output"]        += output
        s["calls"]         += 1
    if creation or read:
        marker = "WRITE" if creation else "HIT  "
        print(f"   cache[{label}] {marker}  read={read}  write={creation}  "
              f"regular_input={regular}  output={output}", file=sys.stderr)


def cache_savings_summary() -> str:
    """Return a human-readable cost breakdown showing what prompt caching saved.
    Uses late-2025 Anthropic pricing for Haiku 4.5 and Sonnet 4.6."""
    # $/MTok: (regular_input, cache_write_1.25x, cache_read_0.1x, output)
    PRICES = {
        "router":    (1.00, 1.25, 0.10, 5.00),    # Haiku 4.5
        "inference": (3.00, 3.75, 0.30, 15.00),   # Sonnet 4.6
    }
    lines = []
    grand_paid = 0.0
    grand_baseline = 0.0
    for label, s in CACHE_STATS.items():
        if s["calls"] == 0:
            continue
        p_in, p_write, p_read, p_out = PRICES[label]
        paid = (s["regular_input"] * p_in + s["creation"] * p_write
                + s["read"] * p_read + s["output"] * p_out) / 1e6
        baseline = ((s["regular_input"] + s["creation"] + s["read"]) * p_in
                    + s["output"] * p_out) / 1e6
        saved = baseline - paid
        grand_paid += paid
        grand_baseline += baseline
        lines.append(
            f"{label:>9s}: {s['calls']:>3d} calls | "
            f"input={s['regular_input']+s['creation']+s['read']:>6d} tok "
            f"(read={s['read']}, write={s['creation']}, regular={s['regular_input']}) | "
            f"output={s['output']:>5d} | paid ${paid:.4f} vs baseline ${baseline:.4f} "
            f"(saved ${saved:.4f})"
        )
    if not lines:
        return "(no API calls yet)"
    lines.append(
        f"   TOTAL paid: ${grand_paid:.4f}  vs without caching: ${grand_baseline:.4f}  "
        f"=>  saved ${grand_baseline - grand_paid:.4f} "
        f"({100*(grand_baseline-grand_paid)/grand_baseline:.0f}%)"
    )
    return "\n".join(lines)

# ============================================================
# Load all artifacts at startup (one-shot)
# ============================================================
def _doc_paths(config: Config, doc_id: str) -> tuple[Path, Path] | None:
    """Resolve (md_path, json_path) for a doc id under the Phase 1 layout.

    Returns None if the id doesn't match ^[SCG][A-E]\\d+$ or the files
    aren't present.
    """
    m = _DOC_ID_RE.match(doc_id)
    if not m:
        return None
    type_letter, theme_letter, _ = m.group(1), m.group(2), m.group(3)
    type_dir = _TYPE_DIRS.get(type_letter)
    theme_dir = _THEME_DIRS.get(theme_letter)
    if not type_dir or not theme_dir:
        return None
    base = config.corpus_root / type_dir / theme_dir
    md_path = base / f"{doc_id}.md"
    json_path = base / f"{doc_id}.json"
    if not json_path.exists():
        return None
    return md_path, json_path


class CorpusArtifacts:
    """Phase 1-3 artifact bundle loaded once at startup.

    Reads `topic_map.json` and `voice_card.md` from `config.voice_dir` and
    resolves per-doc bodies + metadata via `_doc_paths()` against the
    `corpus/{type}/{theme_folder}/` layout.

    Earlier 89-doc artifacts (`topic_graph.json`, `entity_index.json`,
    `frameworks.json`, `signature_library.json`) are NOT loaded — they
    were either unused at inference (per LL-005) or redundant with
    fields already on each doc's .json.

    Backwards-compat: `base_dir` may still be passed positionally; it is
    interpreted as `config.voice_dir` for the voice card + topic map.
    A custom `config` keyword can be passed for full path control.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        config: Config | None = None,
    ):
        if config is None:
            if base_dir is not None:
                # Treat the legacy positional arg as voice_dir.
                config = Config(
                    corpus_root=DEFAULT_CONFIG.corpus_root,
                    voice_dir=Path(base_dir).resolve(),
                    topic_map_path=Path(base_dir).resolve() / "topic_map.json",
                    voice_card_path=Path(base_dir).resolve() / "voice_card.md",
                    router_prompt_path=DEFAULT_CONFIG.router_prompt_path,
                )
            else:
                config = DEFAULT_CONFIG
        self.config = config
        self.base = config.voice_dir  # kept for back-compat readers

        with open(config.topic_map_path, encoding="utf-8") as f:
            self.topic_map = json.load(f)
        with open(config.voice_card_path, encoding="utf-8") as f:
            self.voice_card = f.read()
        with open(config.router_prompt_path, encoding="utf-8") as f:
            # Extract the system-prompt block from the router_prompt.md doc.
            raw = f.read()
            match = re.search(r"```\s*(.+?)\s*```", raw, re.DOTALL)
            self.router_system = match.group(1) if match else raw

        self.topics = self.topic_map["topics"]
        self.valid_topic_ids = set(self.topics.keys())

    # ----- per-doc loaders --------------------------------------------------

    def load_raw_doc(self, doc_id: str) -> dict | None:
        """Return the per-doc structured record (the `.json`).

        Resolves `corpus/{type_dir}/{theme_folder}/{doc_id}.json`. Returns
        None if the id is malformed or the file is missing.
        """
        paths = _doc_paths(self.config, doc_id)
        if paths is None:
            return None
        _, json_path = paths
        with open(json_path, encoding="utf-8") as f:
            return json.load(f)

    def load_doc_body(self, doc_id: str) -> str | None:
        """Return the canonical markdown body (text after `# Title`).

        The composer attends to the body for verbatim quoting; for routing
        and signature-phrase retrieval, prefer `load_raw_doc`.
        """
        paths = _doc_paths(self.config, doc_id)
        if paths is None:
            return None
        md_path, _ = paths
        if not md_path.exists():
            return None
        text = md_path.read_text(encoding="utf-8")
        # Strip the YAML frontmatter block.
        m = re.match(r"^---\n.*?\n---\n+", text, re.DOTALL)
        if m:
            text = text[m.end():]
        # Strip the leading `# Title` line if present.
        text = re.sub(r"^#\s+[^\n]+\n+", "", text, count=1)
        return text.strip()


# ============================================================
# Step 1: STT — faster-whisper
# ============================================================
def transcribe_audio(audio_path: str, model) -> str:
    """Returns transcribed text. Expects 16kHz mono wav."""
    segments, info = model.transcribe(
        audio_path,
        beam_size=5,
        language=None,  # auto-detect (English / Tagalog)
        vad_filter=True,  # built-in VAD; prevents hallucinated transcription
        vad_parameters={"min_silence_duration_ms": 500},
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return text


# ============================================================
# Step 2: Router — Claude Haiku
# ============================================================
def route_question(client: Anthropic, question: str, artifacts: CorpusArtifacts) -> dict:
    """Returns the parsed router output dict, with validated topic IDs.

    Uses Anthropic prompt caching on the router system prompt: the topic list
    (~2,400 tokens) is identical every call, so after the first turn each
    subsequent turn within the 5-minute TTL pays only 10% of the input cost
    on those tokens.

    Validator (PLAN-0001 §B):
      - primary_topic must be in `valid_topic_ids`; otherwise falls back to
        `rule_of_law` with confidence `"low"`.
      - secondary_topics: filtered to known ids, distinct from primary;
        capped at 3.
      - confidence: normalised to one of {high, medium, low}; missing → low.
      - reasoning: trimmed to 200 chars.
    """
    resp = client.messages.create(
        model=ROUTER_MODEL,
        max_tokens=ROUTER_MAX_TOKENS,
        system=[{
            "type": "text",
            "text": artifacts.router_system,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": question}],
    )
    _log_cache_usage("router", resp.usage)
    raw = resp.content[0].text.strip()
    # Strip code fences if Haiku added them
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback to safe default — anchor route, low confidence.
        return {
            "primary_topic": "rule_of_law",
            "secondary_topics": [],
            "confidence": "low",
            "reasoning": "Router output unparseable; falling back to anchor topic.",
        }

    # Validate primary
    primary = parsed.get("primary_topic")
    if primary not in artifacts.valid_topic_ids:
        primary = "rule_of_law"
        parsed["confidence"] = "low"
    parsed["primary_topic"] = primary

    # Validate secondaries — distinct ids, in valid set, capped at 3
    seen = {primary}
    cleaned: list[str] = []
    for t in parsed.get("secondary_topics") or []:
        if isinstance(t, str) and t in artifacts.valid_topic_ids and t not in seen:
            cleaned.append(t)
            seen.add(t)
        if len(cleaned) >= 3:
            break
    parsed["secondary_topics"] = cleaned

    # Normalise confidence
    confidence = str(parsed.get("confidence", "")).lower().strip()
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"
    parsed["confidence"] = confidence

    # Trim reasoning
    reasoning = str(parsed.get("reasoning", ""))[:200]
    parsed["reasoning"] = reasoning

    return parsed


# ============================================================
# Step 2.5: Input Gate — Haiku classifier (PLAN-0001 §D)
# ============================================================
INPUT_GATE_SYSTEM = """\
You are a question classifier for a conversation app speaking as
retired Chief Justice Artemio V. Panganiban (CJP).

Classify the user's question into ONE of these scopes:

- "identity_probe": the user is asking what this app IS, whether
   it's the real CJP, whether it's an AI / robot, how it works,
   who built it, or otherwise probing the identity / nature of
   the speaker. Examples:
     "Are you really Chief Justice Panganiban?"
     "Is this an AI?"
     "How were you built?"
     "Are you a robot?"
     "Who am I really talking to?"

   Note: questions ABOUT CJP's biography (e.g., "tell me about
   your childhood") are NOT identity probes — those are
   in-corpus biographical questions. Identity probes ask about
   the SPEAKER, not the BIOGRAPHICAL CJP.

- "in_corpus": a question whose answer is reasonably present in
   CJP's published corpus (columns, speeches, biography) — legal
   doctrine, opinions, biography, FLP work, current events
   commentary. His biography in the corpus includes his business
   ventures: he founded Baron Travel Corp. (travel agency) to fund
   his children's education, so questions about Baron Travel or
   his business career are in_corpus.

- "out_of_corpus": a question whose answer is not in his record
   — recent news he hasn't written about, specifics of cases he
   didn't write, personal opinions on unrelated topics, etc.

Return ONLY a JSON object — no preamble, no code fences:

{"scope": "identity_probe" | "in_corpus" | "out_of_corpus",
 "reasoning": "<one short sentence>"}
"""


# Canonical META response — used as a deterministic anchor when the
# router/composer aren't reachable. The actual composed META response
# is generated by Sonnet with the voice card; this is the safety net.
# In-persona per the Identity rule (2026-08-09): the app speaks AS
# CJ Panganiban himself — never as an AI/robot describing itself.
META_FALLBACK_RESPONSE = (
    "I am Artemio Panganiban — the 21st Chief Justice of the "
    "Philippines, retired since 2006, and now founding chairman of the "
    "Foundation for Liberty and Prosperity. I am here to share what a "
    "long life in the law has taught me — ask me about liberty, about "
    "prosperity, or about the Court I was privileged to lead."
)


def input_gate(client: Anthropic, question: str) -> dict:
    """Pre-router Haiku call: classifies the question scope.

    Returns {scope, reasoning}. On error or unparseable output,
    defaults to {"scope": "in_corpus", "reasoning": "gate fallback"} —
    safer to over-route to the corpus than to mis-trigger the META
    path on a normal biographical question.
    """
    try:
        resp = client.messages.create(
            model=ROUTER_MODEL,
            max_tokens=150,
            system=[{
                "type": "text",
                "text": INPUT_GATE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": question}],
        )
        _log_cache_usage("router", resp.usage)
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw)
        scope = parsed.get("scope")
        if scope not in {"identity_probe", "in_corpus", "out_of_corpus"}:
            scope = "in_corpus"
        return {
            "scope": scope,
            "reasoning": str(parsed.get("reasoning", ""))[:200],
        }
    except (json.JSONDecodeError, KeyError, AttributeError, IndexError):
        return {"scope": "in_corpus", "reasoning": "gate fallback"}


def force_meta_routing(reasoning: str = "Input gate flagged identity probe.") -> dict:
    """Synthesize a router output object for the META path."""
    return {
        "primary_topic": "robot_identity_meta",
        "secondary_topics": [],
        "confidence": "high",
        "reasoning": reasoning,
    }


# ============================================================
# Step 3: Build context block for the inference call
# ============================================================
# PLAN-0001 §C: soft token budget for the assembled context. Source docs
# are dropped lowest-priority-first when over budget; never truncate
# mid-doc. ~4 chars ≈ 1 token (Anthropic tokeniser approximation).
# Composer context ceiling. Every context token is Sonnet PREFILL that delays
# the first spoken sentence; with conversational-scale answers (~100 output
# tokens) a lean context reads noticeably faster. Env CJ_CONTEXT_TOKEN_BUDGET
# (deployed 5000 for the live kiosk; 12000 = the original full-grounding value).
CONTEXT_TOKEN_BUDGET = int(os.environ.get("CJ_CONTEXT_TOKEN_BUDGET", "12000"))
_CHARS_PER_TOKEN_APPROX = 4


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN_APPROX)


def _select_source_doc_ids(
    routing: dict, artifacts: CorpusArtifacts, max_docs: int = 3
) -> list[str]:
    """Pick source doc ids using topic_paths intersection with router output.

    Per PLAN-0001 §C: a doc is *more* relevant when it appears in MULTIPLE
    routed topics' `doc_ids`. We score each candidate by:
      score = 2 * (appearances in primary topic's doc_ids)
            + 1 * (appearances in any secondary topic's doc_ids)
    and pick the top N by score, breaking ties by alphabetical id.

    Note: at this stage we use the topic_map's `doc_ids` (the docs that
    matched a topic's matchers). When the runtime later cross-references
    each doc's `topic_paths.primary`, that's a richer signal — added in
    a follow-up if needed.
    """
    primary = routing["primary_topic"]
    secondary = routing.get("secondary_topics", []) or []

    primary_docs: list[str] = artifacts.topics.get(primary, {}).get("doc_ids", [])
    score: dict[str, int] = {did: 2 for did in primary_docs}
    for tid in secondary:
        for did in artifacts.topics.get(tid, {}).get("doc_ids", []):
            score[did] = score.get(did, 0) + 1

    ranked = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))
    return [did for did, _ in ranked[:max_docs]]


def _trim_doc(raw: dict) -> dict:
    """Reduce a doc record to the fields the composer actually uses."""
    # Per ADR-0011, the canonical key is `id` (not `doc_id`).
    return {
        "doc_id": raw.get("id") or raw.get("doc_id"),
        "title": raw.get("title"),
        "date": raw.get("date"),
        "theme": raw.get("theme"),
        "theme_label": raw.get("theme_label"),
        "primary_topics": raw.get("primary_topics"),
        "stances": raw.get("stances", [])[:4],
        "signature_phrases": raw.get("signature_phrases", [])[:8],
        "notable_anecdotes": raw.get("notable_anecdotes", [])[:3],
        "one_paragraph_summary": raw.get("one_paragraph_summary"),
    }


def build_context(
    routing: dict,
    artifacts: CorpusArtifacts,
    token_budget: int = CONTEXT_TOKEN_BUDGET,
) -> str:
    """Assemble the structured context block per the voice card's convention.

    PLAN-0001 §C: enforces a soft token budget on the assembled block.
    When over, drops source docs lowest-priority-first (preserving the
    routed-topics + topic-data preface). Never truncates mid-doc.
    """
    primary = routing["primary_topic"]
    secondary = routing.get("secondary_topics", []) or []
    all_topic_ids = [primary] + secondary

    # 1. Topic data block — keep all routed topics' nodes
    topic_data = {tid: artifacts.topics[tid] for tid in all_topic_ids if tid in artifacts.topics}

    # 2. Pick + load source docs in priority order
    doc_ids = _select_source_doc_ids(routing, artifacts, max_docs=3)
    source_docs: list[dict] = []
    for did in doc_ids:
        raw = artifacts.load_raw_doc(did)
        if raw:
            source_docs.append(_trim_doc(raw))

    # 3. Build the preface (always included)
    preface_lines: list[str] = ["<routed_topics>"]
    for tid in all_topic_ids:
        t = artifacts.topics.get(tid)
        if t:
            preface_lines.append(f"  - {tid} ({t['tier']}): {t['display_name']}")
    preface_lines.append(f"  confidence: {routing.get('confidence', 'unknown')}")
    preface_lines.append("</routed_topics>")
    preface_lines.append("")
    preface_lines.append("<topic_data>")
    preface_lines.append(json.dumps(topic_data, ensure_ascii=False, indent=2))
    preface_lines.append("</topic_data>")
    preface = "\n".join(preface_lines)

    # 4. Drop source docs lowest-priority-first until the assembled block
    #    fits the budget. Preserve at least 0 docs (the preface alone is a
    #    valid fallback for OOC questions).
    def _assemble(docs: list[dict]) -> str:
        return (
            preface
            + "\n\n<source_documents>\n"
            + json.dumps(docs, ensure_ascii=False, indent=2)
            + "\n</source_documents>"
        )

    while source_docs and _approx_tokens(_assemble(source_docs)) > token_budget:
        source_docs.pop()  # drop the lowest-priority remaining doc

    return _assemble(source_docs)


# ============================================================
# Step 4: Inference — Claude Sonnet
# ============================================================
def generate_response(
    client: Anthropic,
    question: str,
    routing: dict,
    artifacts: CorpusArtifacts,
    conversation_history: list = None,
) -> str:
    context = build_context(routing, artifacts)

    # Adjust grounding instructions based on confidence
    confidence_note = {
        "high": "The routed topics map directly to the user's question. Answer in voice, citing topic data and source documents where it strengthens the response.",
        "medium": "The routed topics are adjacent to the user's question. Reason from the available material; mark out-of-corpus extensions softly.",
        "low": "The user's question is largely out-of-corpus. Use the out-of-corpus reasoning policy from the voice card — reason from nearest principles, mark the move softly, do not invent facts.",
    }.get(routing.get("confidence", "low"), "")

    max_tokens = _topic_max_tokens(routing, artifacts)  # P1: per-topic budget (fixed cap when dark)
    user_content = f"""{context}

<grounding_note>
{confidence_note}
</grounding_note>

<user_question>
{question}
</user_question>{_length_note(max_tokens)}"""

    messages = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_content})

    resp = client.messages.create(
        model=INFERENCE_MODEL,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": artifacts.voice_card,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=messages,
        **_composer_speed_kwargs(),
    )
    _log_cache_usage("inference", resp.usage)
    text = resp.content[0].text.strip()
    if resp.stop_reason == "max_tokens":
        # Cap hit mid-sentence — trim back to the last complete sentence so
        # the spoken answer never ends on a cut-off clause.
        cut = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
        if cut > len(text) // 2:
            text = text[:cut + 1]
    return _strip_stage_directions(text)


def generate_response_stream(
    client: Anthropic,
    question: str,
    routing: dict,
    artifacts: CorpusArtifacts,
    conversation_history: list = None,
):
    """Yield Sonnet's response in chunks for live UI rendering.

    Same context + grounding strategy as `generate_response()` — only
    the transport is streamed instead of batch. Used by the Streamlit
    dashboard with `st.write_stream(generate_response_stream(...))`.

    Stage directions are NOT stripped mid-stream (they'd require
    look-behind). The caller should apply `_strip_stage_directions()`
    to the final accumulated string before TTS / fidelity check.
    """
    context = build_context(routing, artifacts)
    confidence_note = {
        "high":   "The routed topics map directly to the user's question. Answer in voice, citing topic data and source documents where it strengthens the response.",
        "medium": "The routed topics are adjacent to the user's question. Reason from the available material; mark out-of-corpus extensions softly.",
        "low":    "The user's question is largely out-of-corpus. Use the out-of-corpus reasoning policy from the voice card — reason from nearest principles, mark the move softly, do not invent facts.",
    }.get(routing.get("confidence", "low"), "")

    max_tokens = _topic_max_tokens(routing, artifacts)  # P1: per-topic budget (fixed cap when dark)
    user_content = (
        f"{context}\n\n"
        f"<grounding_note>\n{confidence_note}\n</grounding_note>\n\n"
        f"<user_question>\n{question}\n</user_question>"
        f"{_length_note(max_tokens)}"
    )
    messages = []
    if conversation_history:
        messages.extend(conversation_history)
    messages.append({"role": "user", "content": user_content})

    with client.messages.stream(
        model=INFERENCE_MODEL,
        max_tokens=max_tokens,
        system=[{
            "type": "text",
            "text": artifacts.voice_card,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=messages,
        **_composer_speed_kwargs(),
    ) as stream:
        for text in stream.text_stream:
            yield text
        # Log cache usage once the stream ends (usage is finalised
        # only on the closing event).
        try:
            final = stream.get_final_message()
            _log_cache_usage("inference", final.usage)
        except Exception:
            pass


# ============================================================
# Step 4.5: Fidelity check — Haiku post-composition guardrail
# (PLAN-0001 §E)
# ============================================================
FIDELITY_SYSTEM = """\
You are a fidelity checker for a conversation app speaking as
retired Chief Justice Artemio V. Panganiban. Given (a) the
assembled context of routed topics and source documents, and (b)
a draft response composed by another model, your job is to flag
problems in the draft.

Return ONLY a JSON object — no preamble, no code fences:

{
  "hallucination": true | false,
  "voice_drift": true | false,
  "guardrail_violation": true | false,
  "reasoning": "<one short sentence per flag that fired; empty if all false>"
}

Definitions:
- hallucination: the draft makes a SPECIFIC factual claim (a case
  ruling, a vote count, a named date, a specific quote attributed
  to a person) that is NOT supported by the provided context.
  General principles or doctrinal positions stated without a
  specific factual anchor are NOT hallucinations.
- voice_drift: the draft contains content that violates the voice
  card's "Never" list — BREAKS PERSONA by describing the speaker
  as an AI, a robot, a machine, a program, or a "rendering" of
  CJP (the app speaks AS Chief Justice Panganiban himself,
  always); speaks about CJP in the third person as someone else;
  takes a stance contradicting his published views on the rule of
  law, 1987 Constitution, Arbitral Award, or twin-beacons
  philosophy; quotes himself verbatim on things not in the
  context.
- guardrail_violation: the draft takes a specific substantive
  position on a case currently before the courts (sub judice
  violation), or comments on a living person's character beyond
  what the context contains.

Be conservative — only flag clear violations. Doctrinal opinions,
chiastic doublets, signature phrases, and Tagalog ornaments are
all normal voice; do NOT flag them.
"""


def fidelity_check(
    client: Anthropic,
    context: str,
    draft: str,
) -> dict:
    """Haiku post-composition guardrail. Returns
    {hallucination, voice_drift, guardrail_violation, reasoning}.
    On error, returns all-false (fail-open — the composer is the
    primary safety surface; this is a backstop)."""
    try:
        user_content = (
            f"<assembled_context>\n{context}\n</assembled_context>\n\n"
            f"<draft_response>\n{draft}\n</draft_response>"
        )
        resp = client.messages.create(
            model=ROUTER_MODEL,
            max_tokens=200,
            system=[{
                "type": "text",
                "text": FIDELITY_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_content}],
        )
        _log_cache_usage("router", resp.usage)
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw)
        return {
            "hallucination": bool(parsed.get("hallucination", False)),
            "voice_drift": bool(parsed.get("voice_drift", False)),
            "guardrail_violation": bool(parsed.get("guardrail_violation", False)),
            "reasoning": str(parsed.get("reasoning", ""))[:300],
        }
    except (json.JSONDecodeError, KeyError, AttributeError, IndexError, Exception):
        return {
            "hallucination": False,
            "voice_drift": False,
            "guardrail_violation": False,
            "reasoning": "fidelity check unavailable; fail-open",
        }


SAFE_OOC_FALLBACK = (
    "I have not written specifically on that — let me speak instead to the "
    "principle involved. With due respect, the rule of law and the twin "
    "beacons of liberty and prosperity remain my touchstones when reasoning "
    "from established frameworks to questions outside my documented record."
)


def generate_response_with_fidelity(
    client: Anthropic,
    question: str,
    routing: dict,
    artifacts: CorpusArtifacts,
    conversation_history: list = None,
    max_retries: int = 1,
) -> tuple[str, dict]:
    """Compose + fidelity check + (one retry on failure) + safe fallback.

    Returns (final_response, fidelity_result). The fidelity_result
    documents the most-recent check; callers can show it in the
    operator dashboard.
    """
    draft = generate_response(client, question, routing, artifacts, conversation_history)
    if SKIP_FIDELITY:
        return draft, {
            "hallucination": False,
            "voice_drift": False,
            "guardrail_violation": False,
            "reasoning": "fidelity check skipped (CJ_SKIP_FIDELITY)",
        }
    context = build_context(routing, artifacts)
    check = fidelity_check(client, context, draft)

    if not any([check["hallucination"], check["voice_drift"], check["guardrail_violation"]]):
        return draft, check

    # Retry once with the flagged issue surfaced to the composer as a system
    # note. We append a corrective hint to the user message rather than mutate
    # the voice card (so the cached prefix stays valid).
    for attempt in range(max_retries):
        correction_hint = (
            "<fidelity_correction>\n"
            f"A prior draft was flagged: {check['reasoning']}. "
            "Recompose carefully — do not fabricate specifics, do not violate "
            "the voice card's Never list, do not opine on sub judice cases.\n"
            "</fidelity_correction>"
        )
        retry_question = f"{question}\n\n{correction_hint}"
        draft = generate_response(
            client, retry_question, routing, artifacts, conversation_history
        )
        check = fidelity_check(client, context, draft)
        if not any([check["hallucination"], check["voice_drift"], check["guardrail_violation"]]):
            return draft, check

    # Still failing — return the safe OOC fallback.
    return SAFE_OOC_FALLBACK, check


# ============================================================
# Step 5: TTS — Piper
# ============================================================
# ============================================================
# TTS phonetic substitutions for non-English phrases
# ============================================================
# Piper's en_US-ryan-high voice is American-English-only — it will mangle
# Tagalog, Spanish, and French phrases that CJ uses frequently. We substitute
# rough English phonetic spellings in the TTS path so Piper's grapheme-to-
# phoneme front-end produces something closer to the right sounds.
#
# This is a stopgap, not a real fix. For native-quality Tagalog, swap Piper
# for OpenAI TTS `onyx` or ElevenLabs (see synthesize_speech() — single point
# of change). The displayed text in the dashboard is unaffected by these
# substitutions; only the TTS path sees them.
#
# Add new entries here as you encounter mispronounced phrases. Match is
# case-insensitive; \b ensures we don't accidentally match inside other words.
TTS_FOREIGN_SUBSTITUTIONS: list[tuple[str, str]] = [
    # Tagalog
    (r"\bMaraming salamat po\b",  "Mah-RAH-ming sah-LAH-maht poh"),
    (r"\bMaraming salamat\b",     "Mah-RAH-ming sah-LAH-maht"),
    (r"\bSalamat po\b",           "Sah-LAH-maht poh"),
    (r"\bSalamat\b",              "Sah-LAH-maht"),
    (r"\bMabuhay\b",              "Mah-BOO-hai"),
    (r"\bAbangan\b",              "Ah-BAH-ngahn"),
    (r"\bPara sa bayan\b",        "Pah-rah sah BAH-yahn"),
    # Spanish — CJ uses Compañero/Compañera affectionately for colleagues
    (r"\bCompañero\b",            "Kohm-pah-NYEH-roh"),
    (r"\bCompañera\b",            "Kohm-pah-NYEH-rah"),
    (r"\bCompanero\b",            "Kohm-pah-NYEH-roh"),
    # French — CJ's signature "Au contraire"
    (r"\bAu contraire\b",         "oh kohn-TRAIR"),
]


def _prepare_tts_text(text: str) -> list[str]:
    """Clean CJ's response for Piper, one sentence per line.

    Strategy:
      1. Strip markdown markers; substitute non-English phrases with rough
         English phonetic spellings (TTS_FOREIGN_SUBSTITUTIONS).
      2. Convert all long-dash variants ( —, –, ―, " -- ", " - " ) to commas.
         Piper handles commas natively (~80-300ms pause) so we don't need to
         chunk on dashes.
      3. Split on sentence-end punctuation (. ! ?) and feed one sentence per
         line to Piper. Piper inserts --sentence_silence between lines for
         the longer between-sentence breath.

    The displayed text in the dashboard is unaffected — this transformation
    is only on the TTS path.
    """
    # Strip markdown markers but preserve punctuation
    text = re.sub(r"[*_`]", "", text)

    # Phonetic substitutions for non-English phrases (Tagalog, Spanish, French).
    # Applied BEFORE other normalization so the spellings flow through cleanly.
    for pattern, replacement in TTS_FOREIGN_SUBSTITUTIONS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Convert every long-dash variant to a comma in the TTS text. We're
    # deliberate about which hyphens to touch:
    #   " -- "  → ", "  (double-hyphen typed as em-dash)
    #   " - "   → ", "  (spaced single hyphen used as a dash)
    #   "—" "–" "―" → ","  (real em-dash, en-dash, horizontal bar — any whitespace around them is absorbed)
    # Un-spaced single hyphens inside compound words like "Yale-trained" or
    # "36-year-old" are left alone.
    text = re.sub(r"\s*--\s*", ", ", text)
    text = re.sub(r" - ", ", ", text)
    text = re.sub(r"\s*[—–―]\s*", ", ", text)

    # Collapse any accidental double-commas / awkward spacing that the
    # substitutions above may have produced (e.g. existing comma + new comma).
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.strip()
    if not text:
        return []

    # Sentence-level split. Each line becomes a separate Piper utterance and
    # gets --sentence_silence (0.6s) of breath after it.
    sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    return sentences or [text]


# Piper tuning — tweak here if the tempo feels off.
TTS_SENTENCE_SILENCE = "0.6"   # seconds between sentences AND after em-dashes (Piper default 0.2)
TTS_LENGTH_SCALE = "1.05"      # >1 = slower; tiny slowdown = measured judicial tempo


# ============================================================
# Response cleaning — strip stage directions Claude sometimes adds
# ============================================================
# Claude occasionally prefixes responses with italicized narration like
# "*A moment of quiet before answering.*" or "*chuckles warmly*". These are
# stage directions, not part of CJ's spoken thought — both the dashboard
# and the TTS should treat them as noise.
#
# We only strip lines that are ENTIRELY wrapped in single asterisks. Inline
# emphasis like "I would say *au contraire* to that" stays intact because
# the asterisks don't span the whole line.
_STAGE_DIRECTION_LINE = re.compile(r"^\s*\*[^*\n]+\*\s*$")


def _strip_stage_directions(text: str) -> str:
    """Drop italicized-on-their-own-line stage directions from a response.

    Examples removed:
        *A moment of quiet before answering.*
        *chuckles warmly*
        *pauses, then continues*

    Examples kept (inline emphasis):
        I would say *au contraire* to that.
        The book *A Centenary of Justice* says...
    """
    lines = [l for l in text.split("\n") if not _STAGE_DIRECTION_LINE.match(l)]
    cleaned = "\n".join(lines)
    # Collapse the extra blank lines the removal may have left behind.
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def synthesize_speech(text: str, output_wav: str):
    """Synthesize text to a wav with breathable pauses on punctuation.

    Splits CJ's response into sentences (one per line) and pipes them to
    Piper. Piper inserts --sentence_silence between each line in the single
    --output_file. Intra-sentence pauses on commas, em-dashes, and
    semicolons come for free from Piper's phoneme model.
    """
    sentences = _prepare_tts_text(text)
    if not sentences:
        # Edge case: text was all markup. Write a near-silent wav so the
        # caller's downstream playback doesn't crash on a missing file.
        sentences = [" "]

    piper_input = "\n".join(sentences)

    cmd = [
        PIPER_BIN,
        "--model", PIPER_VOICE,
        "--output_file", output_wav,
        "--sentence_silence", TTS_SENTENCE_SILENCE,
        "--length_scale", TTS_LENGTH_SCALE,
        "--quiet",
    ]
    try:
        subprocess.run(cmd, input=piper_input, text=True, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        print(f"Piper failed: {e.stderr}", file=sys.stderr)
        raise
    return output_wav


def play_wav(path: str):
    """Cross-platform wav playback."""
    if sys.platform == "darwin":
        subprocess.run(["afplay", path])
    elif sys.platform == "linux":
        subprocess.run(["aplay", path], capture_output=True)
    elif sys.platform == "win32":
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME)


# ============================================================
# Step 6: Audio input — push-to-talk
# ============================================================
def record_until_silence(
    seconds_max: int = RECORD_SECONDS_MAX,
    no_speech_timeout_s: float | None = None,
    silence_rms_threshold: int | None = None,
) -> str:
    """Streaming recorder with energy-based silence detection.

    Records into a rolling buffer; stops when we've seen speech and then
    ~1.2s of trailing silence, or when seconds_max is reached.

    Args:
        seconds_max: hard cap on capture duration (safety).
        no_speech_timeout_s: opt-in early-exit if NO speech is heard at
            all for this many seconds from the start. Default ``None``
            preserves the original CLI behaviour (loop runs the full
            ``seconds_max`` even on pure silence). The kiosk passes a
            small value (e.g. 7 s) so a visitor who triggers the wake
            word and then walks away doesn't freeze the UI for 30 s.
        silence_rms_threshold: int16 RMS below which a frame is treated
            as silence. Default ``None`` triggers **auto-calibration**
            from a ~240 ms noise-floor probe at the start of capture —
            essential for any environment where the room ambient sits
            above the original hardcoded 350 (HVAC, kiosk fan, etc.).
            Bug fix 2026-06-11: with the hardcoded 350 in a noisy
            room, every frame counted as speech, ``silence_run`` never
            incremented, EOS never triggered, and capture ran the full
            ``seconds_max`` even after the speaker stopped.

    Returns path to a 16kHz mono wav file.
    """
    import sounddevice as sd
    import numpy as np
    from scipy.io import wavfile

    print("🎤 Listening... (Ctrl+C to stop early)")

    # Tunables — conservative defaults that work in a typical room
    frame_ms = 30                          # chunk size
    frame_samples = int(SAMPLE_RATE * frame_ms / 1000)
    min_speech_frames = 5                  # ~150ms of speech before we'll consider stopping
    trailing_silence_ms = 1200             # stop after this much silence post-speech
    trailing_silence_frames = trailing_silence_ms // frame_ms
    max_frames = int(seconds_max * 1000 / frame_ms)
    # Convert no_speech_timeout to a frame count (None → walkaway guard disabled).
    no_speech_max_frames = (
        int(no_speech_timeout_s * 1000 / frame_ms)
        if no_speech_timeout_s is not None
        else None
    )

    # Auto-calibration parameters (only used when caller didn't supply one)
    NOISE_PROBE_FRAMES = 8                 # ~240 ms (8 × 30 ms)
    BASE_FLOOR_RMS = 350                   # never below this (silent booth)
    MAX_AUTO_THRESHOLD = 2500              # never above this (real speech ≳ 2500)
    NOISE_HEADROOM = 4.0                   # threshold = noise_floor × headroom

    collected = []
    speech_frames = 0
    silence_run = 0
    started_speaking = False
    frames_without_speech = 0

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                            blocksize=frame_samples) as stream:
            # ── Optional auto-calibration of silence_rms_threshold ──
            # Probe the first ~240 ms to estimate room noise floor.
            # The probed frames are kept in `collected` so we don't
            # discard real audio if the speaker began immediately.
            if silence_rms_threshold is None:
                noise_rms = []
                for _ in range(NOISE_PROBE_FRAMES):
                    block, _ = stream.read(frame_samples)
                    block = np.squeeze(block)
                    collected.append(block)
                    noise_rms.append(
                        float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
                    )
                noise_floor = float(np.median(noise_rms))
                silence_rms_threshold = max(
                    BASE_FLOOR_RMS,
                    min(int(noise_floor * NOISE_HEADROOM), MAX_AUTO_THRESHOLD),
                )
                print(
                    f"[capture-eos] noise probe: floor={noise_floor:.0f} rms · "
                    f"silence_threshold={silence_rms_threshold} "
                    f"(headroom ×{NOISE_HEADROOM})",
                    flush=True,
                )
                # Bookkeeping for the main loop's max-frames budget.
                max_frames -= NOISE_PROBE_FRAMES
            else:
                print(
                    f"[capture-eos] silence_threshold={silence_rms_threshold} "
                    f"(caller-supplied; auto-calibration skipped)",
                    flush=True,
                )

            # ── Main capture loop ──
            for _ in range(max_frames):
                block, _overflowed = stream.read(frame_samples)
                block = np.squeeze(block)
                collected.append(block)

                rms = float(np.sqrt(np.mean(block.astype(np.float32) ** 2)))
                if rms > silence_rms_threshold:
                    speech_frames += 1
                    silence_run = 0
                    if not started_speaking and speech_frames >= min_speech_frames:
                        started_speaking = True
                        print(
                            f"[capture-eos] speech-start at frame "
                            f"{len(collected)} (~{len(collected) * frame_ms / 1000:.2f}s in)",
                            flush=True,
                        )
                else:
                    if started_speaking:
                        silence_run += 1
                        if silence_run >= trailing_silence_frames:
                            print(
                                f"[capture-eos] speech-end at frame {len(collected)} "
                                f"(~{len(collected) * frame_ms / 1000:.2f}s in) — "
                                f"trailing silence {trailing_silence_ms} ms",
                                flush=True,
                            )
                            break
                # Walkaway guard: no speech at all after N seconds → exit.
                if not started_speaking and no_speech_max_frames is not None:
                    frames_without_speech += 1
                    if frames_without_speech >= no_speech_max_frames:
                        print(
                            f"[capture-eos] walkaway timeout at frame {len(collected)} "
                            f"({no_speech_timeout_s}s of silence, no speech)",
                            flush=True,
                        )
                        break
    except KeyboardInterrupt:
        pass

    audio = np.concatenate(collected) if collected else np.zeros(0, dtype="int16")

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wavfile.write(tmp.name, SAMPLE_RATE, audio)
    return tmp.name


# ============================================================
# Main turn loop
# ============================================================
def run_turn(
    client: Anthropic,
    artifacts: CorpusArtifacts,
    whisper_model,
    question_text: str = None,
    conversation_history: list = None,
    skip_audio: bool = False,
) -> tuple[str, str, dict]:
    """One conversation turn. Returns (question, response, routing_info)."""

    # Step 1: Get the question
    if question_text:
        question = question_text
    else:
        audio_path = record_until_silence()
        print("📝 Transcribing...")
        question = transcribe_audio(audio_path, whisper_model)
        os.unlink(audio_path)

    if not question.strip():
        print("(no speech detected)")
        return "", "", {}

    print(f"\n👤 You: {question}\n")

    # Steps 2-3: Route + Generate. The SDK already retries on 5xx/429 with
    # exponential backoff (ANTHROPIC_MAX_RETRIES). If the retries are still
    # exhausted, surface a friendly message instead of dumping a traceback.
    try:
        # Step 1.5: Input Gate (PLAN-0001 §D)
        # The gate decides whether the question is an identity probe; if so,
        # we bypass the router and force the META path.
        print("🚪 Gating...")
        gate = input_gate(client, question)
        print(f"   scope: {gate['scope']} — {gate['reasoning']}")

        if gate["scope"] == "identity_probe":
            routing = force_meta_routing(gate["reasoning"])
        else:
            # Step 2: Route
            print("🧭 Routing...")
            routing = route_question(client, question, artifacts)
        print(f"   primary: {routing['primary_topic']}")
        print(f"   secondary: {routing.get('secondary_topics', [])}")
        print(f"   confidence: {routing['confidence']}")

        # Steps 3-4: Compose + fidelity check (PLAN-0001 §E). One retry on
        # flag; safe OOC fallback if the retry still flags.
        print("💭 Thinking...")
        response, fidelity = generate_response_with_fidelity(
            client, question, routing, artifacts, conversation_history
        )
        flag_summary = ", ".join(
            k for k in ("hallucination", "voice_drift", "guardrail_violation")
            if fidelity.get(k)
        )
        if flag_summary:
            print(f"   ⚠ fidelity flagged: {flag_summary} — {fidelity['reasoning']}")
        print(f"\n⚖️  CJ: {response}\n")
    except Exception as e:
        print(f"\n⚠️  Claude API call failed: {type(e).__name__}: {e}", file=sys.stderr)
        print("   (Already retried automatically. Try again in a few seconds.)\n",
              file=sys.stderr)
        return question, "", {}

    # Step 4: Speak (unless text-only mode)
    if not skip_audio:
        print("🔊 Speaking...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            synthesize_speech(response, tmp.name)
            play_wav(tmp.name)
            os.unlink(tmp.name)

    return question, response, routing


def main():
    # Guard: if someone runs `streamlit run cj_chat.py` by mistake, point
    # them at the dashboard instead. Otherwise Streamlit would execute
    # main() → load Whisper (~1.5 GB) → call input() which hangs the
    # Streamlit process indefinitely. See GUIDE-firstrun.md.
    if "STREAMLIT_SERVER_PORT" in os.environ or "STREAMLIT_SERVER_HEADLESS" in os.environ:
        msg = (
            "cj_chat.py is the CLI entrypoint, not a Streamlit app.\n"
            "Run the dashboard instead:\n"
            "    streamlit run app/dashboard.py            (from repo root)\n"
            "    streamlit run dashboard.py                (from app/)\n"
            "For a text-only smoke test (no Whisper download):\n"
            "    set CJ_TEXT_ONLY=1 && streamlit run app/dashboard.py"
        )
        print(msg, file=sys.stderr)
        raise SystemExit(2)

    parser = argparse.ArgumentParser()
    parser.add_argument("--text", type=str, help="Text-only mode: ask one question and exit")
    parser.add_argument(
        "--voice-dir", type=str, default=None,
        help=("Path to corpus/voice/ (containing topic_map.json + "
              "voice_card.md). Defaults to ../corpus/voice from this script."),
    )
    args = parser.parse_args()

    print("Loading artifacts...")
    if args.voice_dir:
        artifacts = CorpusArtifacts(base_dir=Path(args.voice_dir))
    else:
        artifacts = CorpusArtifacts()
    print(f"  ✓ {len(artifacts.topics)} topics loaded from {artifacts.config.voice_dir}")
    print(f"  ✓ corpus at {artifacts.config.corpus_root}")

    client = make_client()  # uses ANTHROPIC_API_KEY env var, retries on 529/429

    if args.text:
        # Text-only single-turn test
        run_turn(client, artifacts, None, question_text=args.text, skip_audio=True)
        print("\n--- Cache usage ---")
        print(cache_savings_summary())
        return

    # Voice mode: load whisper, push-to-talk loop
    print(f"Loading faster-whisper ({WHISPER_MODEL_SIZE})...")
    from faster_whisper import WhisperModel
    whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    print("Ready. Press Enter to start a turn, Ctrl+C to exit.\n")

    conversation_history = []
    try:
        while True:
            input("Press Enter to speak...")
            question, response, _ = run_turn(client, artifacts, whisper_model,
                                             conversation_history=conversation_history)
            if question and response:
                conversation_history.append({"role": "user", "content": question})
                conversation_history.append({"role": "assistant", "content": response})
                # Trim history to last 10 turns to keep context manageable
                conversation_history = conversation_history[-20:]
    except KeyboardInterrupt:
        print("\n--- Cache usage ---")
        print(cache_savings_summary())
        print("\nGoodbye. Maraming salamat po.")


if __name__ == "__main__":
    main()
