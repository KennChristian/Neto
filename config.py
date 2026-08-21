"""
config.py — single source of truth for every tunable knob in the
CJ Panganiban pilot.

Design contract (W1.1 / W3.3):
  * ONE file holds every knob. Code reads from here; it never hard-codes a
    literal that belongs in a sweep. W3.3 sweeps *this file* (or the matching
    env var) and never edits the code.
  * Every knob is overridable at runtime via an environment variable (and
    therefore via a `.env` file or a CLI `--set KEY=VALUE` wrapper) so a sweep
    can vary values WITHOUT editing code. Precedence: env var > default here.
  * Importing this module has no side effects beyond reading the environment —
    no network, no file I/O, no model loads. `import config` is always cheap.
  * One-line comment per knob states the trade-off it controls
    (cost / latency / recall / fidelity).

ARCHITECTURE NOTE — two generations of knob live here, tagged [BASELINE] and
[NEW-ARCH]. On the `develop` branch the [NEW-ARCH] knobs are the ones the
SHIPPING pipeline consumes:
  [NEW-ARCH]  the develop retrieval engine that runs TODAY: bge-base dense +
              BM25, RRF hybrid fusion, 34-topic centroid soft-prior, top-p
              nucleus cutoff — plus the streamed Sonnet composer.
  [BASELINE]  knobs for the LEGACY pre-W1.8 kiosk (Haiku router/gate → curated
              35-topic map → Sonnet composer → Haiku fidelity check; no
              embeddings/RRF). Consumed ONLY by the CJ_ALLOW_LEGACY-guarded
              app/cj_chat.py path (the `pre-wake-word-integration` kiosk); NOT
              by the develop pipeline. Kept for that branch; inert on develop.

Usage:
    import config
    config.COMPOSER_MODEL_ID          # any knob, directly
    config.summary()                  # dict snapshot for logging / sweep manifests
"""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths — repo-root anchored so the same config works from repo root, app/,
# or scripts/. Override the root with CJ_REPO_ROOT if the tree is relocated.
# ---------------------------------------------------------------------------
REPO_ROOT: Path = Path(
    os.environ.get("CJ_REPO_ROOT", Path(__file__).resolve().parent)
).resolve()


# ---------------------------------------------------------------------------
# Typed env-override helpers. Each knob below is `_envX("ENV_NAME", default)`
# so a sweep can set the env var OR edit the default literal in place.
# ---------------------------------------------------------------------------
def _env_str(name: str, default: str) -> str:
    v = os.environ.get(name)
    return v if v is not None and v != "" else default


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    try:
        return int(v) if v not in (None, "") else default
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    v = os.environ.get(name)
    try:
        return float(v) if v not in (None, "") else default
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _env_list(name: str, default: list[str]) -> list[str]:
    """Comma-separated env override, e.g. CJ_CENTROID_FIELDS=label,description."""
    v = os.environ.get(name)
    if v is None or v == "":
        return list(default)
    return [item.strip() for item in v.split(",") if item.strip()]


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v).expanduser().resolve() if v else default


# ===========================================================================
# 1. RETRIEVAL CUTOFF                                            [NEW-ARCH]
#    How many passages survive to the composer. Higher recall ⇄ more tokens.
# ===========================================================================
# Keep a chunk iff score >= TAU * top_score. Lower TAU → more chunks kept
# (↑recall, ↑cost/latency); higher TAU → tighter, cheaper context (↓recall).
TAU: float = _env_float("CJ_TAU", 0.30)
# Floor on chunks kept regardless of TAU — guards against an empty context
# when the top score is an outlier (↑recall floor, small ↑cost).
MIN_K: int = _env_int("CJ_MIN_K", 3)
# Ceiling on chunks kept regardless of TAU — hard cap on context size
# (caps cost/latency; too low ↓recall on broad questions).
MAX_K: int = _env_int("CJ_MAX_K", 12)
# ---------------------------------------------------------------------------
# [W2.x-TOPP] Nucleus (top-p) selection cutoff — SUPERSEDES the top-k/MAX_K cap
# as the retrieval selection mechanism. Accumulate RRF-fused chunks in rank order
# until their NORMALIZED relevance mass reaches RETRIEVAL_TOP_P, then stop
# (include the chunk that crosses p). Diffuse queries keep more chunks;
# concentrated queries keep fewer. RETRIEVAL_MIN_K is a floor so a payload is
# never empty/1-chunk. NOTE: MAX_K / MIN_K no longer gate retrieval selection —
# but MAX_K is still the DEFAULT for COMPOSER_TOP_K (a composer-side cap, W2.2,
# out of scope here) and both are still logged in baseline snapshots. FLAGGED.
RETRIEVAL_TOP_P: float = _env_float("CJ_RETRIEVAL_TOP_P", 0.95)
RETRIEVAL_MIN_K: int = _env_int("CJ_RETRIEVAL_MIN_K", 4)
# [W2.x-TOPP-2] Which score basis the nucleus accumulates over:
#   "rrf_flat"     : sum-normalized fused score — DEGENERATE (flat RRF ~753 kept).
#   "cosine"       : softmax(dense cosine sims / temp) — real peak, but drops the
#                    sparse/BM25 signal from the RANKING (grounding risk).
#   "softmax_temp" : softmax(fused score / temp) — keeps the hybrid ranking,
#                    sharpens the mass so top-p concentrates. DEFAULT.
RETRIEVAL_TOP_P_BASIS: str = _env_str("CJ_RETRIEVAL_TOP_P_BASIS", "softmax_temp")
# Temperature for the "cosine"/"softmax_temp" bases (lower = sharper nucleus).
# 0.06 chosen from a sweep over the frozen 40: median 9 chunks (vs flat 12),
# spread 2-17 (real per-query adaptation), 0 grounding losses. The task's
# suggested {0.5,0.3,0.1} do NOT concentrate below 12 (median 768/745/74);
# "cosine" basis fails entirely (bge cosines compressed -> ~718 even at 0.1).
RETRIEVAL_SOFTMAX_TEMP: float = _env_float("CJ_RETRIEVAL_SOFTMAX_TEMP", 0.06)


# ===========================================================================
# 2. FUSION                                                     [NEW-ARCH]
#    Hybrid lexical+dense fusion and the topic-affinity prior.
# ===========================================================================
# Reciprocal-Rank-Fusion constant: rank score = 1/(RRF_K + rank). Larger
# RRF_K flattens the rank advantage (more democratic fusion, ↓precision@1);
# smaller sharpens it (↑precision, more brittle).
RRF_K: int = _env_int("CJ_RRF_K", 60)
# Topic-affinity weight: final = passage_sim + LAMBDA * topic_affinity.
# Higher LAMBDA trusts the topic prior more (↑on-topic, risks ↓recall on
# cross-topic questions); 0 disables the prior (pure passage similarity).
LAMBDA: float = _env_float("CJ_LAMBDA", 0.25)


# ===========================================================================
# 3. ROUTING / SCOPE                                  [BASELINE + NEW-ARCH]
#    When to declare a question out-of-corpus, and how soft the topic prior is.
# ===========================================================================
# Below this top-affinity score the question is treated as out-of-scope and
# the OOC reasoning policy fires. Higher → stricter scope (more "I haven't
# written on that"); lower → more answers attempted (risks ungrounded ones).
# P3 (W1.8): PROVISIONAL / UNCALIBRATED. This gates QUERY→centroid cosine — a
# DIFFERENT distribution from W1.7's 0.68 doc/chunk→centroid coverage floor; do
# NOT reuse 0.68 here. Real calibration needs draft queries (post-W1.8). Below
# this, the soft prior is treated as out-of-scope and retrieval falls through to
# global (the bias is dropped, never gated).
OUT_OF_SCOPE_THRESHOLD: float = _env_float("CJ_OUT_OF_SCOPE_THRESHOLD", 0.15)
# Softmax temperature over topic affinities → soft prior (not a hard pick).
# Higher temperature = flatter prior (more topics contribute, ↑recall);
# lower = peakier (commits to the top topic, ↑precision).
TOPIC_SOFTMAX_TEMPERATURE: float = _env_float("CJ_TOPIC_SOFTMAX_TEMPERATURE", 0.7)


# ===========================================================================
# 4. TOPIC MODEL                                                [NEW-ARCH]
#    Drives the W1.7 centroid regeneration. Must be fully config-driven so the
#    regen is reproducible from this file alone.
# ===========================================================================
# Where the curated/centroid topic map is read from and written to.
TOPIC_MAP_PATH: Path = _env_path(
    "CJ_TOPIC_MAP_PATH", REPO_ROOT / "corpus" / "voice" / "topic_map.json"
)
# Schema/version stamp written into the regenerated map; bump on format change
# so consumers can detect a stale on-disk map (no runtime trade-off, hygiene).
TOPIC_MAP_VERSION: str = _env_str("CJ_TOPIC_MAP_VERSION", "2.0")
# Independence check: two topics whose centroids exceed this cosine are flagged
# as non-independent (merge candidates). RECALIBRATED for bge-large (W1.7 Step 1;
# values carried through the bge-base v4 transition — re-derive if the embedder changes):
# bge cosines are compressed, so distinct hand-curated topics already pair at a
# median 0.84 (p95 0.91, p99 0.93) — the old MiniLM-era 0.85 would merge ~half of
# ALL topic pairs. 0.95 isolates genuine duplicates (only
# msme_and_entrepreneurship≡prosperity_fund_msme @0.976 exceeds it); the 0.93-0.94
# cluster is compression, not duplication. Lower→more merges (↓precision).
TOPIC_MERGE_COSINE: float = _env_float("CJ_TOPIC_MERGE_COSINE", 0.95)
# Max topic tags (primary + secondary) attached to a question/doc, clamped to
# 1–3. More tags → broader context pulled (↑recall, ↑cost); fewer → tighter.
MAX_TOPIC_TAGS: int = max(1, min(3, _env_int("CJ_MAX_TOPIC_TAGS", 3)))
# Which per-topic fields are embedded and averaged into the topic centroid.
# More fields → richer, more stable centroid (↑recall, slower regen); fewer →
# sharper but noisier centroid.
CENTROID_SOURCE_FIELDS: list[str] = _env_list(
    "CJ_CENTROID_SOURCE_FIELDS",
    ["label", "description", "signature_phrases", "exemplar_chunks"],
)
# Per-doc topic_paths derivation (consumed today by build_topic_map.py):
# how many topics become a doc's primary vs secondary routes. More primaries
# → broader routing (↑recall, ↓precision).
TOPIC_PRIMARY_N: int = _env_int("CJ_TOPIC_PRIMARY_N", 2)
TOPIC_SECONDARY_N: int = _env_int("CJ_TOPIC_SECONDARY_N", 3)
# Matcher-health thresholds used by build_topic_map.py's curator warnings
# (taxonomy hygiene only; no inference-time trade-off).
TOPIC_OVER_BROAD_FRAC: float = _env_float("CJ_TOPIC_OVER_BROAD_FRAC", 0.25)
TOPIC_NEAR_DUP_JACCARD: float = _env_float("CJ_TOPIC_NEAR_DUP_JACCARD", 0.50)
TOPIC_DOMINANT_TERM_FRAC: float = _env_float("CJ_TOPIC_DOMINANT_TERM_FRAC", 0.80)


# ===========================================================================
# 5. COMPOSITION                                                [BASELINE]
#    The Sonnet composer call and its retry/guardrail envelope.
# ===========================================================================
# Max output tokens for a spoken response (~20-150 words post-compression).
# Higher → longer answers (↑cost, ↑latency, risk of rambling); lower → terser.
MAX_TOKENS: int = _env_int("CJ_MAX_TOKENS", 300)
# Wall-clock budget for one composer call before giving up (latency guard).
COMPOSER_TIMEOUT_S: float = _env_float("CJ_COMPOSER_TIMEOUT_S", 30.0)
# Composer HTTP transport — one of:
#   "native_sdk"   : anthropic SDK + truststore (OS cert store). The DESIRED
#                    baseline; supports streaming. Works where Python OpenSSL TLS
#                    is intact (a fresh clone / the off-board Service host).
#   "schannel_curl": route the Anthropic call through Windows curl (schannel).
#                    FALLBACK for hosts where a security product injects an
#                    applink-less OpenSSL that HARD-ABORTS outbound Python HTTPS
#                    (OPENSSL_Uplink: no OPENSSL_Applink — observed on THIS build
#                    laptop; breaks pip + anthropic + httpx; truststore does NOT
#                    fix it as the abort is in the handshake transport). Cert
#                    verification stays ON (--ssl-no-revoke skips revocation only).
#   "auto"         : probe native TLS once (subprocess); use native_sdk if it
#                    works, else schannel_curl. Default — correct on both host types.
COMPOSER_HTTP_TRANSPORT: str = _env_str("CJ_COMPOSER_HTTP_TRANSPORT", "auto")
# SDK-level retries on transient 429/5xx (exponential backoff). Higher →
# more resilient to overload (↑tail latency); lower → fails faster.
MAX_RETRIES: int = _env_int("CJ_MAX_RETRIES", 4)
# Composer fidelity-recompose retries on a flagged draft before the safe
# OOC fallback. Higher → more salvage attempts (↑cost/latency); 0 → fallback
# immediately on first flag.
FIDELITY_MAX_RETRIES: int = _env_int("CJ_FIDELITY_MAX_RETRIES", 1)
# ===========================================================================
# [W2.1] Production composer governance.
# COMPOSER_MAX_TOKENS — output ceiling for the streamed composer (prose + the
# trailing ENVELOPE JSON). SIZED FROM DATA, not guessed: in the arch-baseline
# (the old MAX_TOKENS=300 run) the p95 legitimate prose was 286 output tokens
# and one answer (X38) clipped at the 300 ceiling — i.e. 300 was TRUNCATING real
# persona answers. A full 3-5 paragraph persona answer + the envelope JSON
# (~60-80 tok) needs headroom above that. 640 ≈ 2.2x the arch p95 / ~1.4x the
# longest plausible 5-paragraph answer+envelope: fits without truncation, while
# capping a runaway at <650 tok (~$0.0096 max output cost, ~13s max generation).
# The SHAPER is the Voice Card length discipline; this is the safety net.
# [W3.3-LITE 2026-07-18] Lowered 640 -> 480 with the CONCISE spoken-length
# directive (Voice Card). Measured: concise prose runs 107-189 words (worst-case
# anecdote 394 output tok INCL envelope), so 480 fits prose + the ~40-80 tok
# ENVELOPE with headroom. NOTE: 320 was trialed and TRUNCATED the envelope on the
# anecdote answer (cited=[]); 480 recovers it. Do not drop below ~440.
COMPOSER_MAX_TOKENS: int = _env_int("CJ_COMPOSER_MAX_TOKENS", 480)
# Target prose length the Voice Card asks for (the primary length lever).
COMPOSER_TARGET_PARAGRAPHS: str = _env_str("CJ_COMPOSER_TARGET_PARAGRAPHS", "3-5")
# [W3.7] OOS decline BACKSTOP (composer-side). Phase-1 proved the centroid-cosine
# gate (OUT_OF_SCOPE_THRESHOLD) cannot separate OOS from in-scope (weather/dining
# score inside the in-scope cosine band), so the DESIGNED OOS mechanism lives in
# the composer: decline plainly out-of-domain questions, answer everything in the
# CJ domain. ON by default (designed behavior, not dark); conservatively worded to
# protect in-scope from false-declines (see the re-verify gate in W3.7).
COMPOSER_OOS_DECLINE_ENABLED: bool = _env_bool("CJ_COMPOSER_OOS_DECLINE_ENABLED", True)
COMPOSER_OOS_DECLINE_TEXT: str = _env_str(
    "CJ_COMPOSER_OOS_DECLINE_TEXT",
    "- OUT-OF-DOMAIN DECLINE: if the question is plainly outside your domain — everyday "
    "logistics such as the weather, dining or restaurant recommendations, directions, shopping, "
    "sports scores — and the source chunks do not genuinely answer it, DECLINE gracefully in your "
    "own voice (a brief, warm 'that is not something I can speak to here' in character — never a "
    "global claim about your whole record such as 'nowhere in my record') and cite NOTHING. This "
    "applies ONLY to plainly out-of-domain questions. ANY question touching law, the courts, the "
    "Constitution, justice, judicial reform, the Foundation for Liberty and Prosperity, your life, "
    "career, faith, colleagues, or Philippine public affairs is IN your domain — answer it from the "
    "chunks and never decline it.")
# App-level bounded retries (distinct from MAX_RETRIES, the SDK's transient
# 429/5xx retry). These cover timeout / transport faults around the stream, with
# exponential backoff COMPOSER_BACKOFF_BASE_S * 2**attempt before each retry.
COMPOSER_MAX_RETRIES: int = _env_int("CJ_COMPOSER_MAX_RETRIES", 2)
COMPOSER_BACKOFF_BASE_S: float = _env_float("CJ_COMPOSER_BACKOFF_BASE_S", 0.5)
# Sentinel that separates streamed PROSE from the trailing ENVELOPE JSON. Prose
# streams first (TTFT preserved); everything after the sentinel is metadata.
COMPOSER_ENVELOPE_SENTINEL: str = _env_str("CJ_COMPOSER_ENVELOPE_SENTINEL", "---ENVELOPE---")
# Graceful degradation: in-voice message returned after retries are exhausted,
# instead of an error/hang. Spoken as CJ, not as a system fault.
COMPOSER_FALLBACK_MESSAGE: str = _env_str(
    "CJ_COMPOSER_FALLBACK_MESSAGE",
    "With due respect, I am unable to give that the considered answer it deserves "
    "just now. Let me reflect on it and get back to you.")
# ===========================================================================
# [W2.2] Payload slimming — INPUT-side cost/latency. The composer payload is
# top-k matched CHUNKS + LEAN directives (theme/register/Theme-A) ONLY. The
# corpus per-doc enrichment (signature_phrases, stances, decision_framework_
# signals, target_audience, register_markers, one_paragraph_summary) is
# DIAGNOSTIC-ONLY and is NEVER placed in the payload.
# COMPOSER_TOP_K — [W2.x-TOPP-2] now a CEILING on the top-p nucleus, not the
# selector. Retrieval returns an ADAPTIVE nucleus (median ~9, range 2-17 chunks);
# build_payload sends min(nucleus, COMPOSER_TOP_K). Concentrated queries send
# FEWER than 12 (cost/TTFT win); diffuse queries are capped at this ceiling so a
# broad query can't explode the payload. RETRIEVAL_MIN_K is the floor.
COMPOSER_TOP_K: int = _env_int("CJ_COMPOSER_TOP_K", MAX_K)
# COMPOSER_CHUNK_CHAR_BUDGET — cap on TOTAL chunk chars in the payload (highest-
# ranked chunks kept until the budget is hit). 0 = unlimited (behavior-preserving
# default). An alternative/complementary lever to COMPOSER_TOP_K.
COMPOSER_CHUNK_CHAR_BUDGET: int = _env_int("CJ_COMPOSER_CHUNK_CHAR_BUDGET", 0)
# COMPOSER_SIGNATURE_PALETTE — optionally offer a few signature phrases as a
# palette ("use when natural"). Default OFF (leaner); this is the ONLY enrichment
# that may enter the payload, and only as an optional hint.
COMPOSER_SIGNATURE_PALETTE: bool = _env_bool("CJ_COMPOSER_SIGNATURE_PALETTE", False)
# [NEW-ARCH] Expand-on-demand gate: if a turn's retrieval would fire (need
# more context) on more than this fraction of turns, escalate to a wider
# pull. ~0.10 keeps expansion rare (↓cost) while catching genuine gaps.
EXPAND_ON_DEMAND_FIRE_RATE_GATE: float = _env_float(
    "CJ_EXPAND_ON_DEMAND_FIRE_RATE_GATE", 0.10
)
# Soft token budget for the assembled context block (baseline composer).
# Higher → more source docs survive (↑recall, ↑cost); lower → tighter context.
CONTEXT_TOKEN_BUDGET: int = _env_int("CJ_CONTEXT_TOKEN_BUDGET", 12_000)
# Approx chars-per-token used to estimate the budget above (tokeniser proxy).
CHARS_PER_TOKEN_APPROX: int = _env_int("CJ_CHARS_PER_TOKEN_APPROX", 4)
# Max source docs pulled into one context block (baseline retrieval).
# Higher → broader grounding (↑recall, ↑cost); lower → sharper, cheaper.
MAX_SOURCE_DOCS: int = _env_int("CJ_MAX_SOURCE_DOCS", 3)


# ===========================================================================
# 6. MODELS                                           [BASELINE + NEW-ARCH]
# ===========================================================================
# [NEW-ARCH] Embedding model — see the EMBEDDINGS section below for the
# authoritative knobs. The W1.5 dense arm and W1.7 centroids MUST share these.
# MiniLM-384 and OpenAI text-embedding-3 are the W3.4 benchmark alternatives.
# Back-compat aliases (older code referenced EMBEDDING_*); single source =EMBED_*.
EMBEDDING_MODEL_ID: str = None  # set after EMBED_MODEL_ID is defined (see below)
EMBEDDING_DIM: int = None       # set after EMBED_DIM is defined (see below)
# [BASELINE] Composer model (Sonnet) — quality/cost anchor for composition.
COMPOSER_MODEL_ID: str = _env_str(
    "INFERENCE_MODEL", _env_str("CJ_COMPOSER_MODEL_ID", "claude-sonnet-4-6")
)
# DEPRECATED (W1.8): the Haiku pre-retrieval router/gate is REMOVED from the new
# serial path — routing is now a local centroid soft-prior (zero LLM round-trips
# before composition). Retained only for the legacy cj_chat.py path; do not add
# new pre-composition uses.
ROUTER_MODEL_ID: str = _env_str(
    "ROUTER_MODEL", _env_str("CJ_ROUTER_MODEL_ID", "claude-haiku-4-5-20251001")
)
# Versioned service contract (W1.8 seam) — bump on request/response shape change.
SERVICE_VERSION: str = _env_str("CJ_SERVICE_VERSION", "1.0")
RETRIEVAL_ARCH_VERSION: str = _env_str("CJ_RETRIEVAL_ARCH_VERSION", "w1.8-rrf-softprior")
# [BASELINE] Local STT model size (faster-whisper). Larger → better Tagalog
# mix accuracy (↑latency, ↑memory); smaller → faster.
WHISPER_MODEL_SIZE: str = _env_str("WHISPER_MODEL", "medium")
# [BASELINE] STT backend selector — "openai" (whisper-1 cloud) or "local" (faster-
# whisper on CPU). STT dominates the felt record-stop -> first-audio latency in the
# v5 log (2.3-15.2x the filler-fired budget), so this switch is the biggest lever
# left. Default = "openai" per the demo-host re-bench in
# eval/results/w3_12_stt_local_vs_openai_bench.md: on the build/demo host (Ryzen 7
# 3750H, Zen+ APU) whisper-1 warm-median is ~3.0s/clip vs faster-whisper
# base/int8/cpu at ~7.7s — openai wins on latency. Local wins on accuracy (0 vs 1
# word edit on the SAPI sample; "baron" -> "barren" on openai). STT_BACKEND=local
# remains the OFFLINE-READY path (no network, no API spend) — one env flip.
STT_BACKEND: str = _env_str("STT_BACKEND", "openai")
# [BASELINE] Cloud STT/TTS (voice_io.py OpenAI path).
OPENAI_STT_MODEL: str = _env_str("OPENAI_STT_MODEL", "whisper-1")
# Local faster-whisper knobs (used when STT_BACKEND=="local"). base/int8/cpu is
# the recommended local default per the re-bench: 3.75x faster than small
# (7.7s vs 28.9s warm median on this host) at zero accuracy cost on the SAPI
# harness. Matches the size streamlit_voice_smoke.py already loads.
LOCAL_STT_MODEL: str = _env_str("LOCAL_STT_MODEL", "base")
LOCAL_STT_COMPUTE: str = _env_str("LOCAL_STT_COMPUTE", "int8")
LOCAL_STT_DEVICE: str = _env_str("LOCAL_STT_DEVICE", "cpu")
OPENAI_TTS_MODEL: str = _env_str("OPENAI_TTS_MODEL", "tts-1")
OPENAI_TTS_VOICE: str = _env_str("OPENAI_TTS_VOICE", "echo")
# TTS speed 0.25–4.0; <1 is slower (CJP's measured judicial pace).
OPENAI_TTS_SPEED: float = _env_float("OPENAI_TTS_SPEED", 0.98)


# ===========================================================================
# 7. ENCODING                                                   [CONVENTION]
#    Locked project conventions — preserved verbatim per W1.1.
# ===========================================================================
# Read text/CSV as utf-8-sig so a BOM (if present) is stripped transparently;
# harmless on BOM-free files. Locked convention — do not change casually.
FILE_ENCODING: str = _env_str("CJ_FILE_ENCODING", "utf-8-sig")
# Encoding used when *writing* JSON/text outputs (no BOM on write).
OUTPUT_ENCODING: str = _env_str("CJ_OUTPUT_ENCODING", "utf-8")
# JSON writes keep non-ASCII (Tagalog/Spanish/French) intact, never escaped.
JSON_ENSURE_ASCII: bool = _env_bool("CJ_JSON_ENSURE_ASCII", False)


# ===========================================================================
# 8. AUDIO (baseline push-to-talk recorder)                     [BASELINE]
# ===========================================================================
SAMPLE_RATE: int = _env_int("CJ_SAMPLE_RATE", 16000)
RECORD_SECONDS_MAX: int = _env_int("CJ_RECORD_SECONDS_MAX", 30)
# Energy-based silence detection tunables (int16 RMS) — room-dependent.
SILENCE_RMS_THRESHOLD: int = _env_int("CJ_SILENCE_RMS_THRESHOLD", 350)
TRAILING_SILENCE_MS: int = _env_int("CJ_TRAILING_SILENCE_MS", 1200)
# Piper TTS tempo (baseline local voice).
TTS_SENTENCE_SILENCE: str = _env_str("CJ_TTS_SENTENCE_SILENCE", "0.6")
TTS_LENGTH_SCALE: str = _env_str("CJ_TTS_LENGTH_SCALE", "1.05")


# ===========================================================================
# 9. DATA CONVENTIONS                                           [CONVENTION]
#    Locked schema/ID conventions, surfaced so consumers share one definition.
# ===========================================================================
# Curated CSV schema width — the 15-column contract. Validators read this.
CURATED_SCHEMA_COLUMNS: int = _env_int("CJ_CURATED_SCHEMA_COLUMNS", 15)
# Doc-ID regex. NOTE: the W1.1 brief specifies ^[SCGB][A-E]\d+$ (adds 'B' for
# the forthcoming book corpus, PLAN-0005). The shipping code today recognises
# only S/C/G; 'B' is reserved here so the regex is ready when books land.
DOC_ID_REGEX: str = _env_str("CJ_DOC_ID_REGEX", r"^[SCGB][A-E]\d+$")
# Padded canonical doc-ID regex used by the W1.4 full-corpus pipeline:
# exactly 3 digits (CA034, BE001, GC001, SE012). Stricter than DOC_ID_REGEX.
DOC_ID_REGEX_PADDED: str = _env_str("CJ_DOC_ID_REGEX_PADDED", r"^[CGBS][A-E]\d{3}$")


# ===========================================================================
# 10. CHUNKING (W1.4 full-corpus heading-aware chunker)         [NEW-ARCH]
#     Single source for the chunker; no literals live in the chunk script.
# ===========================================================================
# Target chunk size band, in approx tokens (~CHARS_PER_TOKEN_APPROX chars/tok).
# A heading section under MIN may merge with the next; a run over MAX is split
# on paragraph/sentence boundaries. Smaller -> sharper retrieval, more chunks
# (↑index size); larger -> more context per hit, fewer chunks (↓recall@k).
CHUNK_TARGET_TOKENS_MIN: int = _env_int("CJ_CHUNK_TARGET_TOKENS_MIN", 200)
CHUNK_TARGET_TOKENS_MAX: int = _env_int("CJ_CHUNK_TARGET_TOKENS_MAX", 400)
# Overlap (approx tokens) carried between adjacent chunks of the SAME section
# when a section is split — preserves cross-boundary context (↑recall, small
# ↑redundancy/cost). Small by design.
CHUNK_OVERLAP_TOKENS: int = _env_int("CJ_CHUNK_OVERLAP_TOKENS", 40)
# Heading-aware: split on markdown headings first, packing whole sections up to
# the band before falling back to paragraph/sentence splitting. Keeps anecdote
# sections intact. Turn off for naive fixed-window chunking.
CHUNK_HEADING_AWARE: bool = _env_bool("CJ_CHUNK_HEADING_AWARE", True)
# Never split an anecdote section across chunks even if it exceeds MAX
# (an over-long anecdote becomes its own oversized chunk). Preserves anecdotes
# whole for grounding (↑fidelity, occasional ↑chunk size).
CHUNK_KEEP_ANECDOTES_WHOLE: bool = _env_bool("CJ_CHUNK_KEEP_ANECDOTES_WHOLE", True)


# ===========================================================================
# 11. EMBEDDINGS (W1.5 runtime dense arm + W1.7 centroids)      [NEW-ARCH]
#     Authoritative embedding knobs. The W1.5 pilot dense index and the W1.7
#     full-corpus centroids MUST use the SAME EMBED_MODEL_ID + EMBED_DIM.
#     Model stays swappable via config (MiniLM-384 / OpenAI text-embedding-3 are
#     the W3.4 benchmark alternatives) — never hardcode at a call site.
# ===========================================================================
# Embedding model id. Quality/latency/dim anchor for ALL dense retrieval.
EMBED_MODEL_ID: str = _env_str("CJ_EMBED_MODEL_ID", "BAAI/bge-base-en-v1.5")
# Output dimensionality of EMBED_MODEL_ID; matrix/centroid shape depends on it.
EMBED_DIM: int = _env_int("CJ_EMBED_DIM", 768)
# Device for local embedding inference ("cpu" or "cuda"). cuda ↓latency if present.
EMBED_DEVICE: str = _env_str("CJ_EMBED_DEVICE", "cuda")
# Optional local snapshot DIR for the embedding model (portable; retires any
# machine-specific path). get_model() resolution: EMBED_MODEL_PATH (if set+exists)
# → the HF cache snapshot (if present) → EMBED_MODEL_ID (hub download). Empty by
# default so a fresh clone / the Service host resolves by hub name.
EMBED_MODEL_PATH: str = _env_str("CJ_EMBED_MODEL_PATH", "")
# Unit-normalise embeddings so dot product == cosine (required for the index).
EMBED_NORMALIZE: bool = _env_bool("CJ_EMBED_NORMALIZE", True)
# bge query/document asymmetry: queries get the instruction prefix, documents
# none. Wrong prefix silently degrades recall — set once, here.
EMBED_QUERY_PREFIX: str = _env_str(
    "CJ_EMBED_QUERY_PREFIX",
    "Represent this sentence for searching relevant passages: ")
EMBED_DOCUMENT_PREFIX: str = _env_str("CJ_EMBED_DOCUMENT_PREFIX", "")
# Embedding backend / precision (W1.7 Step 0). "cpu_fp32" = torch fp32 on CPU
# (numerically faithful to W1.5; benchmarked ~0.27 chunks/s on this AMD Zen+ APU).
# "cuda_fp32" when a GPU is present (orders of magnitude faster). Recorded in the
# index meta so the system never mixes two embedding regimes (parity gate).
EMBED_BACKEND: str = _env_str("CJ_EMBED_BACKEND", "cuda_fp32")
# Encode batch size. GPU path uses small batches (GTX 1650, 4 GB VRAM — ~3 GB
# free after the display); 8 is the smoke-tested fp32 batch.
EMBED_BATCH_SIZE: int = _env_int("CJ_EMBED_BATCH_SIZE", 8)
# Persisted pilot dense index (float32 matrix) + sidecar meta.
DENSE_INDEX_PATH: Path = _env_path("CJ_DENSE_INDEX_PATH", REPO_ROOT / "data" / "index" / "pilot_dense.npy")
DENSE_INDEX_META_PATH: Path = _env_path("CJ_DENSE_INDEX_META_PATH", REPO_ROOT / "data" / "index" / "pilot_dense_meta.json")

# Back-compat aliases (section 6): older code referenced EMBEDDING_*.
EMBEDDING_MODEL_ID = EMBED_MODEL_ID
EMBEDDING_DIM = EMBED_DIM


# ===========================================================================
# 12. SPARSE ARM (W1.6 BM25 over full chunk text + atomic-phrase dict) [NEW-ARCH]
#     Exact-identifier complement to the dense arm (statutes, case names,
#     entities). Defaults only — BM25 tuning is W3.3/W3.4, do NOT tune here.
# ===========================================================================
# BM25 term-frequency saturation. Higher → repeated terms count more (↑recall
# of keyword-dense chunks); standard default 1.5.
BM25_K1: float = _env_float("CJ_BM25_K1", 1.5)
# BM25 length normalisation (0=none, 1=full). 0.75 = standard; higher penalises
# long chunks more.
BM25_B: float = _env_float("CJ_BM25_B", 0.75)
# Default number of ranked chunks sparse_score returns. Higher → more candidates
# for fusion (↑recall, ↑W1.8 fusion cost).
SPARSE_TOP_K: int = _env_int("CJ_SPARSE_TOP_K", 50)
# Glob for the curated source of the atomic-phrase dictionary (Keyword/s + entities).
CURATED_XLSX_GLOB: str = _env_str("CJ_CURATED_XLSX_GLOB", "data/csv/*_curated_normalized.xlsx")
# Persisted sparse index state + atomic-phrase dictionary + pin meta.
SPARSE_INDEX_PATH: Path = _env_path("CJ_SPARSE_INDEX_PATH", REPO_ROOT / "data" / "index" / "pilot_sparse.pkl")
SPARSE_DICT_PATH: Path = _env_path("CJ_SPARSE_DICT_PATH", REPO_ROOT / "data" / "index" / "sparse_phrase_dict.json")
SPARSE_META_PATH: Path = _env_path("CJ_SPARSE_META_PATH", REPO_ROOT / "data" / "index" / "pilot_sparse_meta.json")
# ===========================================================================
# [W2.4] Date index — ADDITIVE temporal filter/boost. SHIPS DARK: default OFF.
# When ENABLED and the deterministic router detects explicit temporal intent
# (year/range) or recency, the date table narrows/orders candidates by date.
# With the flag OFF the retrieval path is byte-identical to arch-baseline-v2
# (the date branch is never entered). Enabling it is a separate later decision.
DATE_INDEX_ENABLED: bool = _env_bool("CJ_DATE_INDEX_ENABLED", False)
DATE_INDEX_PATH: Path = _env_path("CJ_DATE_INDEX_PATH", REPO_ROOT / "data" / "index" / "date_index.json")
# "filter" = narrow candidates to date-matching docs; recency orders by date desc.
DATE_INDEX_MODE: str = _env_str("CJ_DATE_INDEX_MODE", "filter")
# ===========================================================================
# [W2.6] Expand-on-demand fallback — COMPOSE-SIDE. On a weakly-grounded first
# compose, do ONE bounded retry with fuller context, then recompose. SHIPS DARK
# (default OFF); with the flag OFF compose behavior is verbatim (no retry, no
# added envelope keys). HARD-CAPPED at 1 retry — never loops.
EXPAND_ON_DEMAND_ENABLED: bool = _env_bool("CJ_EXPAND_ON_DEMAND_ENABLED", False)
# Trigger: retry if the first compose is degraded OR cites FEWER than this floor
# (floor=1 -> fire only on empty citations []). Higher = more aggressive.
EXPAND_TRIGGER_MIN_CITATIONS: int = _env_int("CJ_EXPAND_TRIGGER_MIN_CITATIONS", 1)
# Retry context cap: whole parent doc of the top chunk + the nucleus, up to this
# many chunks (also the retry's build_payload top_k, so fuller context is sent).
EXPAND_MAX_CHUNKS: int = _env_int("CJ_EXPAND_MAX_CHUNKS", 20)
# Fire-rate ceiling: if retries exceed this fraction over a run, that's an
# UPSTREAM-RETRIEVAL signal to flag (do not mask a retrieval gap with retries).
EXPAND_FIRE_RATE_CEILING: float = _env_float("CJ_EXPAND_FIRE_RATE_CEILING", 0.10)
# ===========================================================================
# [ENTITY-RESCUE] Deterministic exact-entity guarantee — FUSION-BOUNDARY. When
# the query contains a CURATED ATOMIC PHRASE (the sparse arm's designed job,
# e.g. "Museum of Liberty and Prosperity"), the best-scoring in-universe chunk
# that actually contains that phrase is INJECTED into the payload regardless of
# its RRF-fused rank or soft-prior score — so an exact curated-entity match is
# always reachable by the composer, never buried by fusion/prior/cutoff. SHIPS
# DARK (default OFF): with the flag OFF, retrieve()/build_payload are
# behavior-identical (no chunk added, selection set + order unchanged). Appended
# to (never replacing) the normal top-k, deduped, bounded at TOP_N. Keys on
# curated-phrase EXACT match only — it stays silent on out-of-scope queries.
ENTITY_RESCUE_ENABLED: bool = _env_bool("CJ_ENTITY_RESCUE_ENABLED", False)
# Bound: inject at most this many rescued chunks (highest fused score first),
# so an exact match can never flood the payload.
ENTITY_RESCUE_TOP_N: int = _env_int("CJ_ENTITY_RESCUE_TOP_N", 2)
# DISTINCTIVENESS BAR: only rescue a curated phrase that is a rare ENTITY — one
# appearing in at most this many corpus docs. Common doctrinal phrases ("the
# Supreme Court" df=706, "rule of law" df=145, "due process" df=124) are already
# well-served by dense+BM25 and must NOT trigger rescue; distinctive entities
# ("Museum of Liberty and Prosperity" df=4, "Baron Travel" df=7, "Roe v. Wade"
# df=4) do. Measured gap: distinctive entities top out ~24, common phrases start
# ~45 (see entity_rescue_report.md). Default 25 sits in that gap.
ENTITY_RESCUE_MAX_DOC_FREQ: int = _env_int("CJ_ENTITY_RESCUE_MAX_DOC_FREQ", 25)


# ===========================================================================
# 13. CENTROID TOPIC MODEL (W1.7 box 6 — full-corpus dense + centroids) [NEW-ARCH]
# ===========================================================================
# Full-corpus dense matrix (all chunks) + meta. The 827 pilot rows must equal
# pilot_dense.npy (one embedding regime — parity gate).
CORPUS_DENSE_PATH: Path = _env_path("CJ_CORPUS_DENSE_PATH", REPO_ROOT / "data" / "index" / "corpus_dense.npy")
CORPUS_DENSE_META_PATH: Path = _env_path("CJ_CORPUS_DENSE_META_PATH", REPO_ROOT / "data" / "index" / "corpus_dense_meta.json")
# Persisted topic centroids (n_topics x EMBED_DIM) + meta.
CENTROIDS_PATH: Path = _env_path("CJ_CENTROIDS_PATH", REPO_ROOT / "data" / "index" / "topic_centroids.npy")
CENTROIDS_META_PATH: Path = _env_path("CJ_CENTROIDS_META_PATH", REPO_ROOT / "data" / "index" / "topic_centroids_meta.json")
# Exemplar member chunks averaged into each centroid (with label/description/
# signature_phrases). More → smoother centroid (↑stability, ↑build cost).
N_EXEMPLAR_CHUNKS: int = _env_int("CJ_N_EXEMPLAR_CHUNKS", 8)
# CHUNK-LEVEL assignment floor (LOCKED, W1.7): a chunk whose nearest centroid
# cosine is below this is flagged as taxonomy-gap content. Derived from the bge
# chunk-vs-nearest-centroid p5 (full corpus: p50 0.76, p25 0.73, p5 0.68, p1 0.64).
# GC006 (0.7566) and CA330 (0.8124) are keyword-rarity / retrieval-gap cases, NOT
# taxonomy orphans — they map cleanly to real topics. Doc-level coverage is
# complete (0/1,089 below floor). The 400/8,887 chunk-level flags are a REVIEW
# SURFACE (taxonomy-gap vs rare-language), not an orphan defect count. This floor
# is calibrated for taxonomy COVERAGE, not retrieval recall; GC006-style recall is
# the dense+sparse arms' job (W1.8 / W1.6 case short-form fix). NOT the same as
# W1.8's query-time OUT_OF_SCOPE_THRESHOLD (query→centroid, a different distribution).
TOPIC_ASSIGN_MIN_COSINE: float = _env_float("CJ_TOPIC_ASSIGN_MIN_COSINE", 0.68)


# ===========================================================================
# VOICE-APP + ROBOT SEAM knobs (demo wrapper / boot; not on the retrieval path)
# ===========================================================================
# [A] Streaming TTS: when True, per-sentence TTS uses tts-1's STREAMED (PCM)
# response so Web-Audio playback begins as chunks arrive (attacks the ~3s tts-1
# floor). Default FALSE = the current whole-clip mp3 mode (behavior-preserving;
# the demo can't break). HELD — not paid-verified yet (~2 TTS calls, ~$0.02).
STREAM_TTS_ENABLED: bool = _env_bool("CJ_STREAM_TTS_ENABLED", False)
# [C] Warm the resident embedder + transport at boot so no visitor pays the
# ~30-40s cold load on question 1.
WARM_ON_BOOT: bool = _env_bool("CJ_WARM_ON_BOOT", True)
# [B] Filler clip pool dir (local SAPI stand-ins now; re-synth with tts-1 or the
# robot Piper voice later). Two-stage: stage-1 ack at transcript-confirm, stage-2
# micro-bridge only if content audio isn't ready when the ack ends.
FILLER_CLIP_DIR: Path = _env_path("CJ_FILLER_CLIP_DIR", REPO_ROOT / "assets" / "filler_clips")

# ===========================================================================
# FILLER v5 — TWO-PART THEME+TOPIC FILLER (extender-free). Chain =
#   THEME clip (or NEUTRAL) -> [TOPIC sentence if gated] -> content -> silence.
# Filler 1 (theme) is pre-synthesized (instant); Filler 2 (topic) is runtime-
# synthesized during theme playback and disk-cached. See app/filler_route.py and
# eval/results/filler_v5_thresholds.md for the threshold derivations.
# ===========================================================================
# Master switch: True -> v5 theme+topic sequencer; False -> the v3 role grammar
# (opener/extender/leadin) is used instead. Behavior-preserving fallback.
FILLER_V5_ENABLED: bool = _env_bool("CJ_FILLER_V5_ENABLED", True)
# THEME gate. Fire a THEME clip only when the route's top-topic cosine (theme
# confidence) >= this; else NEUTRAL. DERIVED from the frozen-40 route-score bands
# (filler_v5_route_bands.json): 0.51 is the cut just above the highest out-of-
# domain stray (X35 weather 0.5072) — it sends all 4 strays/meta to NEUTRAL at the
# cost of 2/34 in-scope (C18 0.4904, E29 0.5025) getting a generic opener (they
# still answer). The bands OVERLAP (in-scope floor 0.4904 < weather 0.5072) so no
# perfect cut exists; the composer OOS-decline is the real backstop.
THEME_CONF_THRESHOLD: float = _env_float("CJ_THEME_CONF_THRESHOLD", 0.51)
# TOPIC gate (Filler 2). Name the specific topic only when top-topic cosine minus
# the best NON-fallback runner-up cosine (CLEAN margin — gmean-fallback centroids
# honors_received/robot_identity_meta excluded from the runner-up) >= this. DERIVED
# from the in-scope clean-margin p75 (~0.0094): 0.01 fires the topic clip only on
# the ~20% genuinely-separated queries; near-ties stay SILENT (never name a coin-
# flip topic). Raw top-minus-runner-up is degenerate (p50 0.004) because the two
# corpus-mean fallback centroids keep grabbing the runner-up slot.
TOPIC_MARGIN_THRESHOLD: float = _env_float("CJ_TOPIC_MARGIN_THRESHOLD", 0.01)
# At filler-selection, wait at most this long for the route (embed+centroid) to
# resolve; past it, fire NEUTRAL rather than make the visitor wait (late-route).
# NOTE: consulted only on the legacy FILLER_FIRE_MODE=gated path (below); the
# unconditional default fires before the route, so this wait no longer applies.
FILLER_ROUTE_WAIT_MS: int = _env_int("CJ_FILLER_ROUTE_WAIT_MS", 300)
# [PHASE-2 FIX] Gate inversion. "unconditional" (default): deal a subject-free clip
# at transcript-confirm with zero route/margin/cache/content dependency — silence is
# not a reachable outcome. "gated": the legacy route-then-decide path (the demo-week
# rollback lever; still fully reachable). Latency, not fidelity, is what this controls.
FILLER_FIRE_MODE: str = _env_str("CJ_FILLER_FIRE_MODE", "unconditional")
# [PHASE-2 FIX] Dead-air watchdog timeout. Independent safety net: if NOTHING is
# enqueued by transcript-confirm + this, force a neutral clip. A firing in production
# is a DEFECT signal (the unconditional fire should always win), never normal.
DEADAIR_WATCHDOG_MS: int = _env_int("CJ_DEADAIR_WATCHDOG_MS", 800)


# ===========================================================================
# 12. WAKE WORD (hands-free front door)                          [NEW-ARCH]
#    Upstream of the pipeline per the Reachy seam (design/w2_7_reachy_seam.md §f):
#    WAKE detect -> record -> STT -> query_text; the pipeline sees only query_text.
#    The wake phrase is a NAMED PARAMETER here, never hardcoded (resolves the
#    long-flagged "Seejop"/"CJ"). Consumed by app/wake_word.py + wake_demo.py.
# ===========================================================================
# The spoken wake phrase (display/log only — matching is driven by the variants).
# Canonical wake phrase "Hey Cee Jap" / "Cee Jap" — spelling ratified
# by Sir Jacob & Atty. Rae, 2026-07-27. Phonetically identical to
# prior "See-Jap"; variant list unchanged.
WAKE_PHRASE: str = _env_str("CJ_WAKE_PHRASE", "Cee-Jap")
# Accepted spoken forms (Whisper mishears "Cee-Jap"/"Hey Cee-Jap" many ways). The legacy
# "CJ"/"see jay" family is retired (WW-5, 2026-07-27). Multi-word forms match adjacent
# tokens; single-word forms match a whole token. Re-parameterize by editing this list
# (or CJ_WAKE_PHRASE_VARIANTS) — no model retrain needed on the stt_keyword backend.
WAKE_PHRASE_VARIANTS: list[str] = _env_list("CJ_WAKE_PHRASE_VARIANTS", [
    # Cee-Jap "-jap" mishears ONLY. The legacy "CJ"/"see jay"/"Jay" family is RETIRED
    # per the WW-5 decision (Dev0+Dok, 2026-07-27): spoken "CJ" ("see jay") must stay silent.
    "see jap", "cee jap", "see jab", "cee jab", "sea jap", "see jip", "see jop", "c jap",
    "seejap", "ceejap", "cjap", "seajap", "seejop", "ceejop", "seejip"])
# Master switch for the hands-free mic loop (wake_demo.py). OFF by default so it never
# disturbs the push-to-talk Streamlit demo; the loop is opt-in.
WAKE_WORD_ENABLED: bool = _env_bool("CJ_WAKE_WORD_ENABLED", False)
# Detector backend: "stt_keyword" (default — keyword-spot the existing STT, no trained
# model, re-parameterizable) | "openwakeword" (robot/production; needs a trained model).
WAKE_BACKEND: str = _env_str("CJ_WAKE_BACKEND", "stt_keyword")
# STT backend for the wake WINDOW specifically (independent of the main STT_BACKEND).
# "local" (faster-whisper) is preferred — cheap + offline for the always-listening loop.
WAKE_STT_BACKEND: str = _env_str("CJ_WAKE_STT_BACKEND", "local")
# Listening window length (s) transcribed per wake check — shorter = snappier + cheaper,
# longer = more tolerant of slow speakers (risks catching trailing words).
WAKE_WINDOW_S: float = _env_float("CJ_WAKE_WINDOW_S", 1.5)
# Max seconds recorded for the QUERY after the wake fires (fixed window; a robot-side
# VAD record-until-silence is the production upgrade).
WAKE_QUERY_MAX_S: float = _env_float("CJ_WAKE_QUERY_MAX_S", 6.0)
# Debounce after a wake fires, so one utterance can't double-trigger.
WAKE_COOLDOWN_S: float = _env_float("CJ_WAKE_COOLDOWN_S", 1.0)
# Fuzzy thresholds for the matcher. word_ratio: per-token similarity for multi-word
# forms (higher = stricter, fewer false fires). token_ratio: whole-token similarity for
# single-word forms (with a tight length guard). Defaults tuned on the Cee-Jap family.
WAKE_WORD_RATIO: float = _env_float("CJ_WAKE_WORD_RATIO", 0.80)
WAKE_TOKEN_RATIO: float = _env_float("CJ_WAKE_TOKEN_RATIO", 0.86)
# Trained-model path for the openWakeWord backend. Empty = the bundled default,
# app/wake/models/hey_cee_jap.onnx (trained 2026-08, wakeword_robot bundle; its
# .onnx.data external-weights file must sit beside it).
WAKE_OWW_MODEL_PATH: str = _env_str("CJ_WAKE_OWW_MODEL_PATH", "")
# Fire threshold for the openWakeWord backend — peak per-frame score a window must
# reach. 0.5 is the trained model's recommended_threshold (training_record.json);
# tune upward against real gallery ambient (Phase 4) if false accepts appear.
WAKE_OWW_THRESHOLD: float = _env_float("CJ_WAKE_OWW_THRESHOLD", 0.5)
# STOP WORD (barge-in): saying the wake phrase WHILE the robot is speaking cuts
# playback and goes straight to listening for the next question. openwakeword
# (streaming) backend only — the STT backend can't listen during playback.
STOP_WORD_ENABLED: bool = _env_bool("CJ_STOP_WORD_ENABLED", True)
# Separate, HIGHER threshold than WAKE_OWW_THRESHOLD: a false stop mid-answer is
# far more disruptive than a missed wake, and the mic hears the robot's own
# speaker during playback (XMOS AEC covers the internal speaker only — on a
# Bluetooth speaker there is NO echo cancellation, so keep this conservative).
STOP_OWW_THRESHOLD: float = _env_float("CJ_STOP_OWW_THRESHOLD", 0.4)


# ===========================================================================
# 13. HEAD ORIENTATION (turn toward the speaker on wake)      [ROBOT-SIDE]
#    On a wake fire, estimate the speaker's direction and turn the Reachy Mini
#    head toward it. Motors/gaze are ROBOT-side per the seam (design/w2_7_reachy_seam.md);
#    real direction-of-arrival (mic-array GCC-PHAT) + the Reachy SDK head-turn are
#    HARDWARE-week work. Until then the "signal inputs" are HARD-CODED here (a fixed
#    azimuth + a level/distance gate) and the head-turn is a logging stub — the seam is
#    parameterized and unit-tested so the real DOA/controller drop in without rewiring.
#    Consumed by app/head_orient.py + app/wake_word.run_hands_free_loop.
# ===========================================================================
# Master switch (OFF by default — opt-in; never disturbs the laptop demo).
HEAD_ORIENT_ENABLED: bool = _env_bool("CJ_HEAD_ORIENT_ENABLED", False)
# Direction estimator: "fixed" (hard-coded azimuth below — the interim signal) |
# "doa" (real mic-array direction-of-arrival — hardware-week stub, needs the array).
HEAD_ORIENT_BACKEND: str = _env_str("CJ_HEAD_ORIENT_BACKEND", "fixed")
# HARD-CODED direction signal (degrees): 0 = straight ahead, + = speaker to the robot's
# right, - = left. The interim value until real DOA lands; tune per bench geometry.
HEAD_ORIENT_FIXED_AZIMUTH_DEG: float = _env_float("CJ_HEAD_ORIENT_FIXED_AZIMUTH_DEG", 0.0)
# HARD-CODED level for the fixed estimator (0..1) — a stand-in for the wake audio loudness
# the real DOA path will measure; must clear MIN_LEVEL below for the head to move.
HEAD_ORIENT_FIXED_LEVEL: float = _env_float("CJ_HEAD_ORIENT_FIXED_LEVEL", 1.0)
# Distance/level GATE: only turn if the wake signal level >= this (0..1). "Voice heard
# from a certain distance" — a far/quiet voice stays below the gate and the head holds.
HEAD_ORIENT_MIN_LEVEL: float = _env_float("CJ_HEAD_ORIENT_MIN_LEVEL", 0.15)
# Head yaw mechanical limit (degrees): the estimated azimuth is clamped to +/- this so a
# command never exceeds the neck's range. Reachy Mini is conservative here.
HEAD_ORIENT_YAW_LIMIT_DEG: float = _env_float("CJ_HEAD_ORIENT_YAW_LIMIT_DEG", 90.0)
# Head controller: "log" (default — prints the target yaw, no hardware) | "reachy"
# (real Reachy Mini SDK head-turn — hardware-week stub).
HEAD_ORIENT_CONTROLLER: str = _env_str("CJ_HEAD_ORIENT_CONTROLLER", "log")
# Display-name source (Part D output) — spoken topic names + speakable flags.
TOPIC_DISPLAY_NAMES_PATH: Path = _env_path(
    "CJ_TOPIC_DISPLAY_NAMES_PATH", REPO_ROOT / "eval" / "results" / "topic_display_names.json")


# ===========================================================================
# 14. POST-PROCESSING — dictionary-grounded NER + ASR-mishear correction  [P0]
#    app/postprocess.py (ported from develop 2026-08-11): detects domain
#    entities (person/org/case/event/book) against data/entities/entity_dict.json
#    (+ hand-curated entity_overrides.json, hot-reloaded on mtime — no restart
#    needed), corrects ASR mishears to the canonical form, and enforces exact
#    SC-citation strings. Wired in cj_voice_cloud.handle_turn (transcript) and
#    speak() (TTS text). DARK unless enabled.
# ===========================================================================
# Master switch (OFF = byte-identical passthrough; postprocess never loads the dict).
POSTPROC_ENABLED: bool = _env_bool("CJ_POSTPROC_ENABLED", False)
# Canonical entity dictionary (generated on develop by scripts/build_entity_dict.py).
ENTITY_DICT_PATH: Path = _env_path(
    "CJ_ENTITY_DICT_PATH", REPO_ROOT / "data" / "entities" / "entity_dict.json")
# Hand-curated overlay (merge/remove/add over the dict; edit freely, no rebuild).
ENTITY_OVERRIDES_PATH: Path = _env_path(
    "CJ_ENTITY_OVERRIDES_PATH", REPO_ROOT / "data" / "entities" / "entity_overrides.json")
# Correction audit log (JSONL, append-only). On the Pi keep this on /dev/shm.
POSTPROC_LOG_PATH: Path = _env_path(
    "CJ_POSTPROC_LOG_PATH", REPO_ROOT / "reports" / "postproc_corrections.jsonl")
# Fuzzy accept threshold (difflib ratio on folded keys); higher = stricter.
POSTPROC_FUZZY_RATIO: float = _env_float("CJ_POSTPROC_FUZZY_RATIO", 0.84)
# Minimum folded length (chars) before a window may fuzzy-match; keep >= 8.
POSTPROC_FUZZY_MIN_CHARS: int = _env_int("CJ_POSTPROC_FUZZY_MIN_CHARS", 8)
# Fuzzy-correction targets need >= this doc_freq (rare one-offs must not rewrite speech).
POSTPROC_FUZZY_MIN_DOC_FREQ: int = _env_int("CJ_POSTPROC_FUZZY_MIN_DOC_FREQ", 2)
# Dictionary forms longer than this many words are skipped at index build.
POSTPROC_MAX_PHRASE_WORDS: int = _env_int("CJ_POSTPROC_MAX_PHRASE_WORDS", 6)


# ===========================================================================
# ANSWER GATE [P0] — deterministic recheck of composed answers BEFORE TTS.
#    app/answer_gate.py: keyword/regex rules (data/entities/answer_gate_rules
#    .json, mtime hot-reload) verify each answer against hand-curated expected
#    data — wrong dates, missing case names, AI self-description. ZERO LLM
#    calls, ~0.15 ms per check. Kiosk wiring: streaming answers get a
#    per-sentence FORBID screen before each sentence is spoken (a tripped
#    sentence is skipped) + a full-answer check logged at the end; the classic
#    (non-streaming) path blocks the whole answer and speaks the safe
#    fallback instead. Ships DARK.
# ===========================================================================
ANSWER_GATE_ENABLED: bool = _env_bool("CJ_ANSWER_GATE_ENABLED", False)
ANSWER_GATE_RULES_PATH: Path = _env_path(
    "CJ_ANSWER_GATE_RULES_PATH", REPO_ROOT / "data" / "entities" / "answer_gate_rules.json")
# Trip audit log (JSONL, append-only). On the Pi keep this on /dev/shm.
ANSWER_GATE_LOG_PATH: Path = _env_path(
    "CJ_ANSWER_GATE_LOG_PATH", REPO_ROOT / "reports" / "answer_gate.jsonl")


# ---------------------------------------------------------------------------
# Introspection — single call that surfaces every knob (for logs / sweeps).
# ---------------------------------------------------------------------------
def summary() -> dict[str, object]:
    """Flat snapshot of every knob — for run logs and sweep manifests."""
    return {
        k: (str(v) if isinstance(v, Path) else v)
        for k, v in globals().items()
        if k.isupper() and not k.startswith("_")
    }


if __name__ == "__main__":
    import json

    print(json.dumps(summary(), indent=2, ensure_ascii=JSON_ENSURE_ASCII))
