"""Interactive chat dashboard for the CJ Panganiban conversation app.

This is the primary UI: a Streamlit chat app with both inputs (mic +
text) and both outputs (visible transcript + Piper-generated audio),
plus a Sources expander showing which canonical topics the router
matched.

Pipeline:
    faster-whisper (STT) → Claude Haiku (router) → Claude Sonnet (inference) → Piper (TTS)

faster-whisper is loaded lazily — only on the first mic recording, never
on dashboard startup. So opening the page is fast even before the model
is cached locally. Piper is loaded only when the TTS toggle is on AND
the binary is present on PATH (or via PIPER_BIN env var).

Run (from the repo root):
    app/.venv/Scripts/streamlit run app/dashboard.py

Or from the app/ directory:
    .venv/Scripts/streamlit run dashboard.py

Environment overrides (all optional):
    ANTHROPIC_API_KEY — required for router + composer calls.
    WHISPER_MODEL    — model size for faster-whisper (default "medium";
                       "small" is ~470 MB / ~5× faster on cold start,
                       still good for English. Use "medium" for
                       Filipino-mixed audio.)
    HF_HOME          — moves the HuggingFace download cache (where the
                       Whisper model lives) off C: drive.
                       Example: D:\\hf-cache.
    PIPER_BIN        — path to piper.exe if not on PATH.
    PIPER_VOICE      — path to the .onnx voice model.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

import streamlit as st

# Importing cj_chat triggers .env loading and Windows UTF-8 setup, so do it
# before any Anthropic / faster-whisper imports below.
sys.path.insert(0, str(Path(__file__).parent))
import cj_chat  # noqa: F401, E402
from cj_chat import (  # noqa: E402
    CorpusArtifacts,
    route_question,
    generate_response,
    generate_response_stream,
    build_context,
    fidelity_check,
    input_gate,
    force_meta_routing,
    _strip_stage_directions,
    make_client,
    cache_savings_summary,
    loaded_env_summary,
    CACHE_STATS,
    ARTIFACTS_DIR,
)
from voice_io import (  # noqa: E402
    transcribe_openai,
    tts_concatenate_parallel,
    voice_io_summary,
    estimate_voice_cost,
    sentence_chunks,
    TTS_VOICE_DEFAULT,
)
from anthropic import Anthropic, APIStatusError, APIConnectionError  # noqa: E402


# ----- Page chrome ---------------------------------------------------------
st.set_page_config(
    page_title="With Due Respect — CJ Panganiban",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ----- Pre-flight: ANTHROPIC_API_KEY must be visible ----------------------
# cj_chat already searched cwd / repo-root / app/ for a .env. If the key
# still isn't set, bail out HERE with a clear banner — beats letting the
# first router call raise a cryptic SDK error mid-turn.
_env_summary = loaded_env_summary()
if not _env_summary["api_key_present"]:
    st.error(
        "**ANTHROPIC_API_KEY is not set.**\n\n"
        f"The runtime searched these `.env` files: "
        f"{_env_summary['dotenv_files_loaded'] or '(none found)'}.\n\n"
        "Add `ANTHROPIC_API_KEY=sk-ant-...` to one of:\n"
        "- `<repo>/app/.env` (recommended — most specific)\n"
        "- `<repo>/.env`\n"
        "- `<cwd>/.env`\n\n"
        "Or set `DOTENV_PATH=<absolute path>` to point at a specific file."
    )
    st.stop()


# ----- Pre-flight: voice-IO dependencies (openai, pydub) ------------------
# voice_io.py imports `openai` lazily inside its client factories, so a
# missing install only blows up the first time STT or TTS is called —
# usually mid-turn. Detect it up-front and tell the user exactly which
# pip command to run from which venv.
_voice_deps_missing: list[str] = []
try:
    import openai as _openai_check  # noqa: F401
except ImportError:
    _voice_deps_missing.append("openai")
try:
    import pydub as _pydub_check  # noqa: F401
except ImportError:
    # pydub is optional (we fall back to raw byte concat), so warn rather
    # than block.
    pass

if _voice_deps_missing:
    import sys as _sys
    _python_exe = _sys.executable
    # requirements.txt sits next to dashboard.py — resolve absolutely so
    # the install command works regardless of the user's current cwd or
    # whether their venv lives off C: with spaces in the path.
    _req_path = (Path(__file__).resolve().parent / "requirements.txt")
    # PowerShell needs the `&` call operator + double quotes around any
    # path containing spaces (e.g. "Reachy Mini Project", "App 2").
    _ps_cmd = f'& "{_python_exe}" -m pip install -r "{_req_path}"'
    # The same call as a bash one-liner (Git Bash / WSL / macOS / Linux).
    _bash_cmd = f'"{_python_exe}" -m pip install -r "{_req_path}"'
    # Fallback for users who don't want -r requirements.txt:
    _direct_pkgs = " ".join(_voice_deps_missing + ["pydub"])
    _ps_direct = f'& "{_python_exe}" -m pip install {_direct_pkgs}'

    st.error(
        "**Voice-loop dependency missing.** The dashboard's Streamlit "
        "process is using this Python interpreter:\n\n"
        f"`{_python_exe}`\n\n"
        f"…but `{', '.join(_voice_deps_missing)}` is not installed in "
        "that interpreter's site-packages. STT and TTS will fail until "
        "you install it into the **same venv** Streamlit is running "
        "from.\n\n"
        "**Run this exact command in PowerShell** (works from any "
        "directory — the absolute paths are baked in):\n\n"
        "```powershell\n"
        f"{_ps_cmd}\n"
        "```\n\n"
        "If you don't have `app/requirements.txt` at the resolved "
        "location, install the missing packages directly:\n\n"
        "```powershell\n"
        f"{_ps_direct}\n"
        "```\n\n"
        "(Git Bash / WSL / macOS / Linux equivalent — drop the `&`:)\n\n"
        "```\n"
        f"{_bash_cmd}\n"
        "```\n\n"
        "The `&` call operator and the double quotes are required "
        "because the path may contain spaces. After installation, "
        "restart Streamlit (Ctrl+C in the terminal, then re-launch)."
    )
    st.stop()


st.markdown(
    """
    <style>
      /* === Museum / exhibit-hall dark theme ============================ */
      @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@500;600;700&family=Inter:wght@400;500;600&display=swap');

      .stApp {
        background:
          radial-gradient(1200px 600px at 50% -200px,
                          rgba(180, 150, 90, 0.10), transparent 60%),
          radial-gradient(900px 500px at 50% 110%,
                          rgba(74, 210, 149, 0.06), transparent 65%),
          linear-gradient(180deg, #050811 0%, #0a0f1c 45%, #050811 100%);
        color: #d5dae6;
      }
      .stChatMessage { font-size: 1.05rem; line-height: 1.55; }
      .source-meta { color: #9aa4b3; font-size: 0.88rem; }

      /* Museum-grade serif for the brand title */
      .reachy-title h1 {
        font-family: 'Cormorant Garamond', Georgia, serif !important;
        font-weight: 600 !important;
        font-size: 2.5rem !important;
        letter-spacing: 0.5px !important;
        line-height: 1.05 !important;
      }
      .reachy-title p {
        font-family: 'Inter', -apple-system, sans-serif !important;
        font-size: 0.95rem !important;
        color: #b3bccc !important;
        font-style: italic;
      }
      .museum-instruction {
        margin: 0.4rem 0 0.2rem;
        padding: 0.45rem 0.75rem;
        border-left: 3px solid rgba(180, 150, 90, 0.55);
        background: rgba(180, 150, 90, 0.05);
        color: #d5dae6;
        font-family: 'Inter', sans-serif;
        font-size: 0.92rem;
        line-height: 1.45;
        border-radius: 4px;
      }

      /* Topic pills */
      .topic-pill {
        display: inline-block; padding: 0.15rem 0.55rem;
        margin: 0.1rem 0.3rem 0.1rem 0; border-radius: 999px;
        font-size: 0.78rem; font-weight: 500;
      }
      .topic-primary   { background: #2d4ea8; color: #fff; }
      .topic-secondary { background: #2a3144; color: #c5cad6; }
      .conf-high   { color: #4ad295; font-weight: 600; }
      .conf-medium { color: #e6c149; font-weight: 600; }
      .conf-low    { color: #d97f5f; font-weight: 600; }

      /* === Reachy Mini avatar — animated panel ========================= */
      .reachy-panel {
        display: flex; align-items: center; gap: 1.4rem;
        padding: 1.1rem 1.3rem; margin: 0.2rem 0 0.6rem;
        border: 1px solid rgba(154, 164, 179, 0.18);
        border-radius: 18px;
        background:
          linear-gradient(135deg,
                          rgba(20, 28, 48, 0.85) 0%,
                          rgba(12, 18, 32, 0.85) 100%);
        backdrop-filter: blur(8px);
        box-shadow:
          0 12px 32px -16px rgba(0, 0, 0, 0.7),
          0 0 0 1px rgba(74, 210, 149, 0.08) inset;
      }
      .reachy-svg { width: 140px; height: 154px; flex-shrink: 0; }
      .reachy-title h1 {
        margin: 0; color: #f6f1e1; font-size: 2.0rem; font-weight: 600;
        letter-spacing: 0.4px;
      }
      .reachy-title p {
        margin: 0.3rem 0 0; color: #9aa4b3; font-size: 0.95rem;
      }
      .reachy-state {
        display: inline-block; margin-top: 0.55rem;
        padding: 0.18rem 0.7rem; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600; letter-spacing: 0.4px;
        text-transform: uppercase;
      }
      .reachy-state.idle      { color: #4ad295; background: rgba(74,210,149,0.10);
                                border: 1px solid rgba(74,210,149,0.3); }
      .reachy-state.listening { color: #e6c149; background: rgba(230,193,73,0.10);
                                border: 1px solid rgba(230,193,73,0.3); }
      .reachy-state.talking   { color: #66b3ff; background: rgba(102,179,255,0.10);
                                border: 1px solid rgba(102,179,255,0.3); }

      /* Eye dots — colour and pulse vary by state. SMIL animations on
         the SVG drive the breathing pulse; these CSS overrides keep the
         palette tied to the active state class on the parent. */
      .reachy-panel.listening .eye { fill: #e6c149 !important; }
      .reachy-panel.talking .eye   { fill: #66b3ff !important; }
      .reachy-panel.listening .mic-led { fill: #e6c149 !important; }
      .reachy-panel.talking .mic-led   { fill: #66b3ff !important; }

      /* Subtle floating motion on the whole avatar */
      @keyframes reachy-breath {
        0%, 100% { transform: translateY(0) rotate(0deg); }
        50%      { transform: translateY(-3px) rotate(-0.4deg); }
      }
      .reachy-svg .head-group { animation: reachy-breath 4.2s ease-in-out infinite; }

      /* Listening: pulsing ring behind the head */
      @keyframes listening-pulse {
        0%   { opacity: 0.0; transform: scale(0.85); }
        50%  { opacity: 0.55; transform: scale(1.0); }
        100% { opacity: 0.0; transform: scale(1.15); }
      }
      .reachy-panel.listening .listening-ring {
        animation: listening-pulse 1.4s ease-out infinite;
        transform-origin: center;
      }

      /* Talking: speaker grille animates as bars */
      @keyframes speaker-pulse {
        0%, 100% { transform: scaleY(1.0); }
        50%      { transform: scaleY(1.6); }
      }
      .reachy-panel.talking .speaker-bar {
        transform-origin: center;
        animation: speaker-pulse 0.45s ease-in-out infinite;
      }
      .reachy-panel.talking .speaker-bar.b2 { animation-delay: 0.10s; }
      .reachy-panel.talking .speaker-bar.b3 { animation-delay: 0.20s; }

      /* Mic dome subtle pulse always-on */
      @keyframes mic-blink {
        0%, 100% { opacity: 1.0; }
        50%      { opacity: 0.5; }
      }
      .reachy-panel .mic-led { animation: mic-blink 2.4s ease-in-out infinite; }

      /* === Listening / talking status banner =========================== */
      .status-banner {
        display: flex; align-items: center; gap: 0.6rem;
        padding: 0.55rem 0.9rem; margin: 0.4rem 0;
        border-radius: 12px; font-size: 0.92rem;
      }
      .status-banner.listening { background: rgba(230,193,73,0.10);
                                 border: 1px solid rgba(230,193,73,0.3);
                                 color: #f0d77a; }
      .status-banner.talking   { background: rgba(102,179,255,0.10);
                                 border: 1px solid rgba(102,179,255,0.3);
                                 color: #a0c4ff; }
      @keyframes blink {
        0%, 60%, 100% { opacity: 1; }
        30%           { opacity: 0.35; }
      }
      .status-dot { width: 10px; height: 10px; border-radius: 50%;
                    animation: blink 1.2s ease-in-out infinite; }
      .status-banner.listening .status-dot { background: #e6c149; }
      .status-banner.talking .status-dot   { background: #66b3ff; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ----- Cached resources (loaded once per Streamlit session) ----------------
@st.cache_resource(show_spinner="Loading corpus artifacts…")
def get_artifacts() -> CorpusArtifacts:
    return CorpusArtifacts(ARTIFACTS_DIR)


@st.cache_resource(show_spinner="Connecting to Claude…")
def get_client() -> Anthropic:
    # max_retries=4 inside make_client() so transient 529/429 errors get
    # retried automatically with exponential backoff before they bubble up.
    return make_client()


def get_tts_dir() -> Path:
    d = Path(__file__).parent / "state" / "tts"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----- Session state -------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []  # list of {role, content, audio_path?, routing?}
if "last_audio_hash" not in st.session_state:
    st.session_state.last_audio_hash = None
if "mic_counter" not in st.session_state:
    st.session_state.mic_counter = 0
if "tts_enabled" not in st.session_state:
    st.session_state.tts_enabled = True
if "robot_state" not in st.session_state:
    # idle | listening | talking — drives the avatar's class for CSS animations
    st.session_state.robot_state = "idle"


# ----- Sidebar -------------------------------------------------------------
with st.sidebar:
    st.markdown("### Settings")
    st.session_state.tts_enabled = st.checkbox(
        "Voice response", value=st.session_state.tts_enabled,
        help=(
            "When on, the response is synthesized via OpenAI TTS in "
            "parallel per-sentence chunks (~$0.003-$0.005 per turn) "
            "and auto-plays once the text stream finishes."
        ),
    )
    st.session_state.show_tts_debug = st.checkbox(
        "Show TTS sentence chunks (debug)", value=False,
        help="Show the per-sentence segments sent to OpenAI TTS in parallel.",
    )
    if st.button("🧹 Clear conversation"):
        st.session_state.messages = []
        st.session_state.last_audio_hash = None
        st.session_state.mic_counter += 1
        st.session_state.robot_state = "idle"
        st.rerun()
    st.markdown("---")
    _voice_summary = voice_io_summary()
    st.markdown(
        "**Pipeline**: OpenAI Whisper (STT, push-to-talk) → "
        "Claude Haiku 4.5 (router + gate + fidelity) → "
        "Claude Sonnet 4.6 (streaming composer) → "
        "OpenAI TTS (per-sentence parallel)."
    )
    st.caption(f"Router model:    `{_env_summary['router_model']}`")
    st.caption(f"Inference model: `{_env_summary['inference_model']}`")
    st.caption(f"STT model:       `{_voice_summary['stt_model']}`")
    st.caption(f"TTS model/voice: `{_voice_summary['tts_model']}` / "
               f"`{_voice_summary['tts_voice']}` @ "
               f"{_voice_summary['tts_speed']}×")
    st.caption(f"ffmpeg:          `{_voice_summary['ffmpeg_path']}`")
    st.caption(f"Topics loaded:   {len(get_artifacts().topics)}")
    if not _voice_summary["openai_key_present"]:
        st.warning(
            "OPENAI_API_KEY not set — STT and TTS will both fail. "
            "Add it to your `.env`.",
            icon="⚠️",
        )
    if _env_summary["dotenv_files_loaded"]:
        with st.expander("🔑 .env files loaded", expanded=False):
            for p in _env_summary["dotenv_files_loaded"]:
                st.code(p, language=None)

    # ---- Prompt cache stats panel ----
    inf = CACHE_STATS["inference"]
    rt = CACHE_STATS["router"]
    if inf["calls"] or rt["calls"]:
        st.markdown("---")
        st.markdown("### 💰 Prompt cache (this session)")
        # Compute paid vs baseline cost
        paid = (
            inf["regular_input"]*3 + inf["creation"]*3.75 + inf["read"]*0.30 + inf["output"]*15
            + rt["regular_input"]*1 + rt["creation"]*1.25 + rt["read"]*0.10 + rt["output"]*5
        ) / 1e6
        baseline = (
            (inf["regular_input"]+inf["creation"]+inf["read"])*3 + inf["output"]*15
            + (rt["regular_input"]+rt["creation"]+rt["read"])*1 + rt["output"]*5
        ) / 1e6
        saved_pct = (100*(baseline-paid)/baseline) if baseline > 0 else 0
        col_l, col_r = st.columns(2)
        col_l.metric("Paid", f"${paid:.4f}")
        col_r.metric("Saved", f"${baseline-paid:.4f}", f"{saved_pct:.0f}%")
        st.caption(
            f"Inference: {inf['calls']} calls · "
            f"{inf['read']:,} cached-read tok · {inf['creation']:,} cache-write tok"
        )
        st.caption(
            f"Router: {rt['calls']} calls · "
            f"caching not honored on Haiku 4.5 in this SDK version"
        )


# ----- Header — animated Reachy Mini avatar with state ---------------------
# All animations live INSIDE the SVG via SMIL (<animate>, <animateTransform>).
# Streamlit's HTML sandbox sometimes drops externally-defined CSS keyframes,
# but every browser honors SMIL elements that ship inline with the SVG.
# State-specific motion (listening ring pulse, talking equaliser bars) is
# emitted conditionally per state, so we don't depend on a parent CSS class
# crossing the DOM boundary.
def _reachy_eye_colour(state: str) -> str:
    return {"idle": "#4ad295", "listening": "#e6c149", "talking": "#66b3ff"}[state]


def _listening_overlay() -> str:
    """SMIL-animated pulse ring shown only in the listening state."""
    return """
    <circle cx='100' cy='115' fill='none'
            stroke='#e6c149' stroke-width='3' opacity='0'>
      <animate attributeName='r'       values='62;102;120' dur='1.4s' repeatCount='indefinite'/>
      <animate attributeName='opacity' values='0.0;0.7;0.0' dur='1.4s' repeatCount='indefinite'/>
    </circle>
    """


def _talking_overlay() -> str:
    """SMIL equaliser bars below the face — only emitted while talking."""
    bars = []
    # 5 bars with staggered phase + varied amplitude → equaliser feel
    cfg = [
        (62,  '0.32s', '0.00s', '10;26;10'),
        (78,  '0.38s', '0.07s', '8;32;8'),
        (94,  '0.30s', '0.15s', '12;22;12'),
        (110, '0.36s', '0.05s', '10;30;10'),
        (126, '0.34s', '0.12s', '8;24;8'),
    ]
    for x, dur, begin, hvals in cfg:
        # Bars grow upward from a baseline; we animate BOTH y and height
        # so the bar appears anchored at its bottom.
        first_h = int(hvals.split(';')[0])
        bars.append(f"""
        <rect x='{x}' y='{200 - first_h}' width='10' height='{first_h}' rx='2' fill='#66b3ff'>
          <animate attributeName='height' values='{hvals}'
                   dur='{dur}' begin='{begin}' repeatCount='indefinite'/>
          <animate attributeName='y' values='{';'.join(str(200 - int(v)) for v in hvals.split(';'))}'
                   dur='{dur}' begin='{begin}' repeatCount='indefinite'/>
        </rect>
        """)
    return "\n".join(bars)


def _reachy_svg(state: str) -> str:
    """Build the state-aware SVG. SMIL animations are baked in:
       - eyes breathe + blink (every ~5 s)
       - mic LED pulses
       - whole head gently sways (always-on)
       - listening: yellow ring expands + fades
       - talking: blue equaliser bars dance below the head
    """
    eye = _reachy_eye_colour(state)
    listening = _listening_overlay() if state == "listening" else ""
    talking = _talking_overlay() if state == "talking" else ""
    # Idle mic colour is green; in active states match the eyes.
    mic_colour = eye

    return f"""
    <svg class='reachy-svg' viewBox='0 0 200 220'
         xmlns='http://www.w3.org/2000/svg'
         aria-label='Reachy Mini robot avatar'>
      <defs>
        <linearGradient id='shellGrad' x1='0' y1='0' x2='0' y2='1'>
          <stop offset='0%'   stop-color='#36405a'/>
          <stop offset='100%' stop-color='#1c2334'/>
        </linearGradient>
        <radialGradient id='glowGrad' cx='50%' cy='50%' r='50%'>
          <stop offset='0%' stop-color='{eye}' stop-opacity='0.45'/>
          <stop offset='100%' stop-color='{eye}' stop-opacity='0.0'/>
        </radialGradient>
      </defs>

      <!-- Soft ambient glow behind the whole head -->
      <ellipse cx='100' cy='115' rx='84' ry='90' fill='url(#glowGrad)'/>

      <!-- Listening state: pulsing yellow ring -->
      {listening}

      <!-- HEAD GROUP — gentle continuous sway + float (always on) -->
      <g>
        <animateTransform attributeName='transform' attributeType='XML'
          type='translate' values='0 0; 0 -3; 0 0; 0 -1; 0 0'
          dur='5.5s' repeatCount='indefinite'/>
        <animateTransform attributeName='transform' attributeType='XML'
          type='rotate' values='-1 100 115; 1 100 115; -1 100 115'
          dur='8s' repeatCount='indefinite' additive='sum'/>

        <!-- side cups / ear-microphones -->
        <ellipse cx='30'  cy='115' rx='15' ry='32'
                 fill='#262d40' stroke='#9aa4b3' stroke-width='2'/>
        <ellipse cx='170' cy='115' rx='15' ry='32'
                 fill='#262d40' stroke='#9aa4b3' stroke-width='2'/>
        <circle  cx='30'  cy='115' r='8' fill='#0e1320'/>
        <circle  cx='170' cy='115' r='8' fill='#0e1320'/>

        <!-- main body / head shell -->
        <rect x='52' y='58' width='96' height='128' rx='22'
              fill='url(#shellGrad)' stroke='#9aa4b3' stroke-width='2'/>

        <!-- top cap / dome -->
        <ellipse cx='100' cy='58' rx='50' ry='16'
                 fill='#262d40' stroke='#9aa4b3' stroke-width='2'/>

        <!-- mic LED on top — pulses on every state -->
        <circle cx='100' cy='34' r='7' fill='{mic_colour}'>
          <animate attributeName='opacity' values='1;0.55;1'
                   dur='2.2s' repeatCount='indefinite'/>
        </circle>
        <line x1='100' y1='41' x2='100' y2='58'
              stroke='#9aa4b3' stroke-width='2'/>

        <!-- screen / face -->
        <rect x='65' y='80' width='70' height='58' rx='10'
              fill='#0a0f1c' stroke='#2d4ea8' stroke-width='1.5'/>

        <!-- LEFT EYE — breathe scale + occasional blink -->
        <ellipse cx='84' cy='106' rx='7' ry='7' fill='{eye}'>
          <animate attributeName='rx' values='7;6.2;7' dur='3.2s' repeatCount='indefinite'/>
          <animate attributeName='ry'
                   values='7;7;0.6;7;7'
                   keyTimes='0;0.45;0.5;0.55;1'
                   dur='5.4s' repeatCount='indefinite'/>
        </ellipse>

        <!-- RIGHT EYE — synchronised blink -->
        <ellipse cx='116' cy='106' rx='7' ry='7' fill='{eye}'>
          <animate attributeName='rx' values='7;6.2;7' dur='3.2s' repeatCount='indefinite'/>
          <animate attributeName='ry'
                   values='7;7;0.6;7;7'
                   keyTimes='0;0.45;0.5;0.55;1'
                   dur='5.4s' repeatCount='indefinite'/>
        </ellipse>

        <!-- smile / mouth -->
        <path d='M 78 128 Q 100 134 122 128'
              stroke='#2d4ea8' stroke-width='2.5' fill='none'
              stroke-linecap='round'/>

        <!-- speaker grille (static; talking-overlay renders the bars) -->
        <line x1='74'  y1='158' x2='126' y2='158'
              stroke='#9aa4b3' stroke-width='1.8'/>
        <line x1='74'  y1='164' x2='126' y2='164'
              stroke='#9aa4b3' stroke-width='1.8'/>
        <line x1='74'  y1='170' x2='126' y2='170'
              stroke='#9aa4b3' stroke-width='1.8'/>
      </g>

      <!-- Talking state: equaliser bars below the head, animated -->
      {talking}
    </svg>
    """


def autoplay_audio_html(audio_bytes: bytes, mime: str = "audio/mp3") -> None:
    """Render an HTML5 audio element that auto-plays the given bytes.

    Uses st.components.v1.html (iframe) so:
      - `<script>` shims aren't stripped by Streamlit's markdown
        sanitizer
      - the `autoplay` attribute survives the DOM insertion path
        intact
      - browser autoplay policy is satisfied because the visitor has
        already interacted with the page (record → stop), allowing
        media playback for the page origin.

    The element shows native controls (`controls` attr) so the visitor
    can scrub, pause, or replay; the JS shim calls `.play()` on
    `loadeddata` as a fallback in case the autoplay attribute alone
    is rejected by a strict browser policy.
    """
    import base64
    import streamlit.components.v1 as components
    b64 = base64.b64encode(audio_bytes).decode("ascii")
    # Inline both the audio element and the play() shim in a
    # self-contained iframe document.
    document = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<style>"
        "  html,body { margin:0; padding:0; background:transparent; }"
        "  audio { width:100%; max-width:540px; "
        "          margin:0.25rem 0; display:block; }"
        "</style></head><body>"
        f"<audio id='cj-audio' autoplay controls "
        f"src='data:{mime};base64,{b64}'></audio>"
        "<script>"
        "(function(){"
        " const a = document.getElementById('cj-audio');"
        " if (!a) return;"
        " const tryPlay = () => { a.play().catch(()=>{}); };"
        " if (a.readyState >= 2) tryPlay();"
        " else a.addEventListener('loadeddata', tryPlay, {once:true});"
        "})();"
        "</script>"
        "</body></html>"
    )
    components.html(document, height=72)


def _flatten_html(s: str) -> str:
    """Collapse a multi-line HTML/SVG string into a single line.

    Streamlit's Markdown processor treats any line that begins with 4+
    spaces as a code block, which causes `unsafe_allow_html=True` HTML
    to be rendered as escaped preformatted text. Flattening to one
    line keeps the document a single HTML block that Markdown won't
    re-interpret.

    We replace newlines with a SINGLE SPACE rather than concatenate
    with no separator, because SVG attributes split across source
    lines (e.g. `viewBox='0 0 200 220'\n  xmlns='http://...'`) would
    otherwise run together and break the parser.
    """
    return " ".join(line.strip() for line in s.splitlines() if line.strip())


def render_reachy_header(state: str = "idle") -> None:
    state_label = {
        "idle":      "🟢 Idle — waiting for your question",
        "listening": "🟡 Listening — your microphone is recording",
        "talking":   "🔵 Speaking — synthesising the response",
    }.get(state, state)

    svg_html = _flatten_html(_reachy_svg(state))
    panel = (
        f"<div class='reachy-panel {state}'>"
        f"{svg_html}"
        "<div class='reachy-title'>"
        "<h1>⚖️ With Due Respect</h1>"
        "<p>Reachy Mini × retired Chief Justice Artemio V. Panganiban</p>"
        f"<span class='reachy-state {state}'>{state_label}</span>"
        "</div>"
        "</div>"
    )

    # st.markdown(unsafe_allow_html=True) is the preferred path — keeps
    # the avatar inside the page so parent CSS (panel border, glass
    # blur, state-coloured chip) styles it. If Streamlit's HTML
    # sanitizer ever drops SMIL or strips the SVG, the components.html
    # fallback below renders the same SVG inside an iframe, which is
    # immune to Markdown re-parsing and SVG sanitization.
    st.markdown(panel, unsafe_allow_html=True)


def render_reachy_header_iframe_fallback(state: str = "idle") -> None:
    """Iframe-based renderer for environments where the markdown path
    fails. Not called by default; the operator can switch to it by
    setting REACHY_RENDER=iframe in the env.

    Trade-offs vs the markdown path: the iframe is sandboxed, so the
    parent `.reachy-panel` CSS doesn't reach inside. We inline the
    minimal CSS needed for the avatar to look right standalone.
    """
    import streamlit.components.v1 as components
    state_label = {
        "idle":      "🟢 Idle",
        "listening": "🟡 Listening",
        "talking":   "🔵 Speaking",
    }.get(state, state)
    svg_html = _flatten_html(_reachy_svg(state))
    document = _flatten_html(f"""
        <!doctype html>
        <html><head><meta charset='utf-8'>
        <style>
          html, body {{ margin: 0; padding: 0; background: transparent;
                        color: #f6f1e1; font-family: -apple-system, Segoe UI, sans-serif; }}
          .wrap {{ display: flex; align-items: center; gap: 1rem; padding: 0.6rem; }}
          .wrap svg {{ width: 140px; height: 154px; flex-shrink: 0; }}
          h1 {{ margin: 0; font-size: 1.7rem; }}
          p {{ margin: 0.2rem 0; color: #9aa4b3; font-size: 0.9rem; }}
          .state {{ display: inline-block; padding: 0.15rem 0.6rem;
                    border-radius: 999px; font-size: 0.78rem;
                    background: rgba(74,210,149,0.15); color: #4ad295; }}
        </style></head><body>
        <div class='wrap'>{svg_html}<div>
          <h1>⚖️ With Due Respect</h1>
          <p>Reachy Mini × retired Chief Justice Artemio V. Panganiban</p>
          <span class='state'>{state_label}</span>
        </div></div>
        </body></html>
    """)
    components.html(document, height=180)


# Render path is selectable via REACHY_RENDER env var:
#   "markdown" (default) — fastest path, inherits parent CSS panel.
#   "iframe"             — bulletproof fallback via st.components.html.
if os.environ.get("REACHY_RENDER", "markdown").lower() == "iframe":
    render_reachy_header_iframe_fallback(st.session_state.robot_state)
else:
    render_reachy_header(st.session_state.robot_state)

# Museum-style instructional plaque under the title — matches the
# "Ask your question using the 'Record' button. Wait for a response."
# museum-exhibit copy the user referenced.
st.markdown(
    "<div class='museum-instruction'>"
    "Ask Chief Justice Panganiban a question using the "
    "<b>🎤 record</b> button below — press <b>⏺</b> to start, <b>⏹</b> "
    "to stop. Or type your question in the box. The response "
    "will be spoken back to you automatically."
    "</div>",
    unsafe_allow_html=True,
)


# ----- Source-rendering helper --------------------------------------------
def render_sources(routing: dict, artifacts: CorpusArtifacts) -> None:
    """Render an expander showing the routed topics and the raw docs the
    inference call would have seen (the top 3 doc_ids of the primary topic)."""
    primary = routing.get("primary_topic", "—")
    secondary = routing.get("secondary_topics", []) or []
    confidence = routing.get("confidence", "—")
    reasoning = routing.get("reasoning", "")

    primary_topic_obj = artifacts.topics.get(primary, {})
    doc_ids = primary_topic_obj.get("doc_ids", [])[:3]
    primary_display = primary_topic_obj.get("display_name", primary)

    with st.expander(f"📚 Sources — {primary_display} ({confidence})"):
        # Topic pills
        pills = [f"<span class='topic-pill topic-primary'>{primary}</span>"]
        for t in secondary:
            pills.append(f"<span class='topic-pill topic-secondary'>{t}</span>")
        st.markdown("**Routed topics:** " + " ".join(pills), unsafe_allow_html=True)

        conf_class = f"conf-{confidence}" if confidence in {"high", "medium", "low"} else ""
        st.markdown(
            f"**Confidence:** <span class='{conf_class}'>{confidence}</span>",
            unsafe_allow_html=True,
        )
        if reasoning:
            st.markdown(f"**Router reasoning:** *{reasoning}*")

        if doc_ids:
            st.markdown("**Source documents (top 3 of primary topic):**")
            for did in doc_ids:
                raw = artifacts.load_raw_doc(did)
                if not raw:
                    st.markdown(f"- `{did}`")
                    continue
                title = raw.get("title", did)
                date = raw.get("date", "")
                meta = f" · {date}" if date else ""
                st.markdown(f"- **{title}**<span class='source-meta'>  ·  `{did}`{meta}</span>",
                            unsafe_allow_html=True)


# ----- Render conversation history ----------------------------------------
artifacts = get_artifacts()
USER_AVATAR = "👤"
CJ_AVATAR = "⚖️"

for msg in st.session_state.messages:
    avatar = USER_AVATAR if msg["role"] == "user" else CJ_AVATAR
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])
        ap = msg.get("audio_path")
        if ap and Path(ap).exists():
            # Historical replay — manual control, no autoplay (autoplay
            # the most-recent turn only, done elsewhere).
            st.audio(ap)
        # Routing details tucked behind a popover (matches the
        # in-flight UI — keeps the chat surface clean).
        if msg.get("routing"):
            with st.popover("🔍 Details", use_container_width=False):
                routing_msg = msg["routing"]
                primary = routing_msg.get("primary_topic", "—")
                conf = routing_msg.get("confidence", "—")
                st.caption(f"Routed to **{primary}** ({conf})")
                if routing_msg.get("secondary_topics"):
                    st.caption(
                        "Secondary: " +
                        ", ".join(f"`{t}`" for t in routing_msg["secondary_topics"])
                    )
                render_sources(routing_msg, artifacts)


# ----- Input row — push-to-talk + text fallback ---------------------------
# Push-to-talk only: the mic is opened ONLY while the user is recording,
# and OpenAI Whisper is called exactly ONCE after they press Stop. There
# is no always-on streaming and no continuous transcription. This is the
# central cost-control decision documented in ADR-0018.
st.markdown(
    "<p style='color:#9aa4b3; margin: 0.8rem 0 0.3rem; font-size: 0.95rem;'>"
    "🎤 <b>Start Talking</b> — press the record button below, ask your "
    "question, then press the <b>stop</b> button on the recorder. "
    "Transcription only fires after you stop."
    "</p>",
    unsafe_allow_html=True,
)
mic_col, _ = st.columns([1, 1])
with mic_col:
    audio_in = st.audio_input(
        "Press ⏺ to start talking · press ⏹ to stop",
        key=f"mic_{st.session_state.mic_counter}",
    )

text_in = st.chat_input("…or type your question (fallback)")


# ----- Resolve the new input to a question string -------------------------
question: str | None = None

if audio_in is not None:
    audio_bytes = audio_in.getvalue()
    audio_hash = hashlib.md5(audio_bytes).hexdigest()
    if audio_hash != st.session_state.last_audio_hash:
        st.session_state.last_audio_hash = audio_hash
        # Robot enters "listening" state visually while STT runs.
        # OpenAI Whisper is a SINGLE call per recording — no streaming,
        # no continuous mic. ~$0.001 per 10-15s utterance.
        st.session_state.robot_state = "listening"
        with st.status("🎧 Transcribing via OpenAI Whisper…", expanded=False) as status:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                wav_path = tmp.name
            try:
                question = transcribe_openai(wav_path)
                status.update(label="🎧 Transcribed", state="complete")
            except RuntimeError as e:
                status.update(label=str(e)[:80], state="error")
                question = None
            except Exception as e:
                status.update(label=f"STT failed: {type(e).__name__}: {e}",
                              state="error")
                question = None
            finally:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass
        if not question or not question.strip():
            if question is not None:  # only warn if STT itself succeeded but empty
                st.warning("No speech detected — please try again.")
            question = None
        else:
            # bump mic key so the widget resets for the next question
            st.session_state.mic_counter += 1

if text_in:
    question = text_in


# ----- Run the turn --------------------------------------------------------
if question:
    # 1. Render the user's message immediately, append to history
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user", avatar=USER_AVATAR):
        st.markdown(question)

    # Conversation history for the inference call (last 10 turns = 20 messages)
    inference_history = [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.messages[:-1]
        if m["role"] in ("user", "assistant")
    ][-20:]

    # 2. Render the assistant's response stage by stage
    with st.chat_message("assistant", avatar=CJ_AVATAR):
        client = get_client()

        # The SDK already retries 5xx/429 with exponential backoff
        # (ANTHROPIC_MAX_RETRIES = 4 in cj_chat.py). If we still get an error
        # after that, show a friendly message and persist a marker turn so
        # the user's question stays in history.
        routing = None
        response = None
        fidelity = None
        api_error: str | None = None
        # A single lightweight progress placeholder replaces the previous
        # always-visible status chips. Once the response streams in, the
        # placeholder is cleared and the pipeline details collapse into a
        # popover ("🔍 Pipeline details") next to the response — so the
        # default view is clean, but every diagnostic is one click away.
        progress_slot = st.empty()
        flags: list[str] = []
        gate: dict = {}
        try:
            # 2a. Input Gate — catches identity probes before they hit
            # the topic router (PLAN-0001 §D).
            progress_slot.markdown(
                "<span style='color:#9aa4b3;font-size:0.85rem;'>"
                "🚪 Checking question scope…</span>",
                unsafe_allow_html=True,
            )
            gate = input_gate(client, question)

            # 2b. Topic routing (or META override if the gate fired)
            progress_slot.markdown(
                "<span style='color:#9aa4b3;font-size:0.85rem;'>"
                "🧭 Routing topics…</span>",
                unsafe_allow_html=True,
            )
            if gate["scope"] == "identity_probe":
                routing = force_meta_routing(gate["reasoning"])
            else:
                routing = route_question(client, question, artifacts)

            # 2c. Build context once so both the streamer and the
            # fidelity check see the same prompt material.
            context = build_context(routing, artifacts)

            # 2d. Stream Sonnet's response token-by-token. The UI
            # renders text as it arrives — no waiting for the full
            # composition before the user sees anything.
            progress_slot.empty()  # clear "routing…" before the stream
            response_raw = st.write_stream(
                generate_response_stream(
                    client, question, routing, artifacts, inference_history
                )
            )
            response = _strip_stage_directions(response_raw)

            # 2e. Fidelity check (advisory). The response is already
            # visible to the user; flags surface as a non-blocking
            # warning rather than a retry. This trades guardrail
            # strictness for streaming UX — matches dashboard
            # ergonomics; the headless CLI keeps the strict retry path.
            fidelity = fidelity_check(client, context, response)
            flags = [
                k for k in ("hallucination", "voice_drift", "guardrail_violation")
                if fidelity.get(k)
            ]
            if flags:
                st.warning(
                    f"⚠ Fidelity flagged: {', '.join(flags)} — "
                    f"{fidelity.get('reasoning', '')}",
                    icon="⚠️",
                )
        except APIStatusError as e:
            # 529 = Anthropic overloaded; 429 = rate-limited; 5xx = upstream error.
            # The SDK already retried ANTHROPIC_MAX_RETRIES times; if we're here
            # the issue outlasted that window.
            if e.status_code == 529:
                api_error = (
                    "Claude's servers are overloaded right now (HTTP 529). The app "
                    "already retried automatically — please try the same question "
                    "again in a few seconds. Your message is still in the conversation."
                )
            elif e.status_code == 429:
                api_error = (
                    "Hit Claude's rate limit (HTTP 429). Wait a few seconds and try again."
                )
            else:
                api_error = (
                    f"Claude API returned HTTP {e.status_code}: {e.message}. "
                    f"Try again in a moment."
                )
        except APIConnectionError as e:
            api_error = (
                f"Couldn't reach Claude's API ({e}). Check your network connection "
                f"and try again."
            )
        except Exception as e:
            api_error = f"Unexpected error contacting Claude: {type(e).__name__}: {e}"

        if api_error:
            st.error("⚠️  " + api_error)
            st.session_state.messages.append({
                "role": "assistant",
                "content": "⚠️ " + api_error,
                "audio_path": None,
                "routing": None,
                "is_error": True,
            })
            st.stop()

        # Note: response already rendered via st.write_stream() above —
        # no extra st.markdown(response) needed.

        # 3. TTS (optional, never blocks the turn — TTS errors are local).
        # Robot enters "talking" state during synthesis + playback.
        audio_path = None
        audio_bytes_mp3: bytes | None = None
        tts_meta: dict = {}
        if st.session_state.tts_enabled:
            st.session_state.robot_state = "talking"
            progress_slot.markdown(
                "<span style='color:#9aa4b3;font-size:0.85rem;'>"
                "🔊 Synthesising voice…</span>",
                unsafe_allow_html=True,
            )
            try:
                audio_bytes_mp3 = tts_concatenate_parallel(response)
                cost = estimate_voice_cost(response)
                n_chunks = len(sentence_chunks(response))
                tts_meta = {
                    "chunks": n_chunks,
                    "cost_usd": cost['tts_usd'],
                    "ok": True,
                }
            except RuntimeError as e:
                tts_meta = {"ok": False, "error": str(e)[:200]}
            except Exception as e:
                tts_meta = {"ok": False,
                            "error": f"{type(e).__name__}: {e}"[:200]}
            progress_slot.empty()
            if audio_bytes_mp3:
                # Persist for the history rerender (replays use st.audio).
                audio_path = str(get_tts_dir() / f"resp_{int(time.time()*1000)}.mp3")
                try:
                    Path(audio_path).write_bytes(audio_bytes_mp3)
                except OSError:
                    audio_path = None
                # Use the HTML5 autoplay path with a JS .play() shim —
                # st.audio(autoplay=True) is unreliable on browsers with
                # strict autoplay policies; this guarantees playback.
                autoplay_audio_html(audio_bytes_mp3, mime="audio/mp3")

        # Settle the robot back to idle after the turn renders.
        st.session_state.robot_state = "idle"

        # 4. Pipeline details — collapsed into a single popover so the
        # default view stays clean. Click "🔍 Details" to expand.
        with st.popover("🔍 Details", use_container_width=False):
            st.markdown("##### 🚪 Input gate")
            st.caption(
                f"Scope: **{gate.get('scope', '—')}** — "
                f"{gate.get('reasoning', '')}"
            )
            st.markdown("##### 🧭 Routing")
            if routing:
                st.caption(
                    f"Primary: **{routing.get('primary_topic', '—')}** "
                    f"({routing.get('confidence', '—')})"
                )
                if routing.get("secondary_topics"):
                    st.caption(
                        "Secondary: " +
                        ", ".join(f"`{t}`" for t in routing["secondary_topics"])
                    )
                if routing.get("reasoning"):
                    st.caption(f"Router reasoning: *{routing['reasoning']}*")
            st.markdown("##### 📚 Sources")
            render_sources(routing, artifacts)
            if fidelity:
                st.markdown("##### 🛡️ Fidelity check")
                st.caption(
                    f"hallucination={fidelity.get('hallucination')}, "
                    f"voice_drift={fidelity.get('voice_drift')}, "
                    f"guardrail_violation={fidelity.get('guardrail_violation')}"
                )
                if fidelity.get("reasoning"):
                    st.caption(f"*{fidelity['reasoning']}*")
            if tts_meta:
                st.markdown("##### 🔊 TTS")
                if tts_meta.get("ok"):
                    st.caption(
                        f"{tts_meta['chunks']} sentence chunk(s) via "
                        f"`{TTS_VOICE_DEFAULT}` — "
                        f"~${tts_meta['cost_usd']:.4f}"
                    )
                else:
                    st.caption(f"⚠ {tts_meta.get('error', 'TTS failed')}")
                if st.session_state.get("show_tts_debug"):
                    st.markdown("**Sentence chunks sent to OpenAI:**")
                    for i, c in enumerate(sentence_chunks(response), 1):
                        st.caption(f"[{i}] ({len(c)} chars) {c}")

    # 5. Persist the assistant turn so it survives the next rerun
    st.session_state.messages.append({
        "role": "assistant",
        "content": response,
        "audio_path": audio_path,
        "routing": routing,
    })

    # Trigger one rerun so the mic widget resets cleanly via the bumped key
    st.rerun()
