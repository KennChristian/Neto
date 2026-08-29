"""Persistent API usage tally for the maintenance page (2026-08-25, user:
"show the update of the tokens from Claude and ElevenLabs").

One JSON file (CJ_USAGE_PATH, default ~/cj_usage.json) with two counters
per provider: `lifetime` (survives restarts and reboots) and `session`
(reset when the service process starts). Every hook fails open — the tally
must never break a turn.

  anthropic[label]  calls, input, cache_write, cache_read, output, cost_usd
  elevenlabs        requests, chars (billed — cache misses only), cache_hits,
                    cache_chars (served from ~/.voice_cache, not billed)
  openai            stt_calls, stt_seconds
"""
import contextlib, json, os, threading, time

PATH = os.environ.get("CJ_USAGE_PATH", os.path.expanduser("~/cj_usage.json"))
# "session" = one run of the systemd service. INVOCATION_ID is fixed for the
# service's lifetime and absent for ad-hoc CLI runs, which then add to the
# lifetime tally without resetting the session (2026-08-25 review: a second
# writer used to reset the session block on every alternation).
SESSION_KEY = os.environ.get("INVOCATION_ID") or None
SESSION_START = time.time()
_lock = threading.Lock()

# $/MTok: regular input, cache write, cache read, output (late-2025 pricing),
# by model family; label fallback keeps old callers priced.
PRICES_BY_MODEL = {"claude-haiku": (1.00, 1.25, 0.10, 5.00),
                   "claude-sonnet": (3.00, 3.75, 0.30, 15.00),
                   "claude-opus": (15.00, 18.75, 1.50, 75.00)}
PRICES = {"router": PRICES_BY_MODEL["claude-haiku"],
          "inference": PRICES_BY_MODEL["claude-sonnet"]}


def _prices(label, model=None):
    for prefix, p in PRICES_BY_MODEL.items():
        if model and str(model).startswith(prefix):
            return p
    return PRICES.get(label, (0, 0, 0, 0))


def _load():
    try:
        with open(PATH) as f:
            doc = json.load(f)
        if not isinstance(doc, dict):
            raise ValueError("not a JSON object")
    except FileNotFoundError:
        doc = {}
    except (OSError, ValueError):
        # keep the damaged file for inspection instead of overwriting the
        # lifetime tally with a fresh one
        with contextlib.suppress(OSError):
            os.replace(PATH, PATH + ".bad")
        doc = {}
    doc.setdefault("lifetime", {})
    if SESSION_KEY and doc.get("session_key") != SESSION_KEY:
        doc["session"] = {}
        doc["session_key"] = SESSION_KEY
        doc["session_start"] = SESSION_START
    doc.setdefault("session", {})
    return doc


def _save(doc):
    doc["updated"] = time.time()
    tmp = f"{PATH}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as f:
        json.dump(doc, f)
        f.flush()
        os.fsync(f.fileno())      # survive a hand power-cycle
    os.replace(tmp, PATH)


@contextlib.contextmanager
def _file_lock():
    """Cross-process lock (the app and CLI/smoke runs may both write)."""
    try:
        import fcntl
        fd = os.open(PATH + ".lock", os.O_RDWR | os.O_CREAT, 0o644)
    except Exception:
        yield
        return
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _bump(path, **fields):
    """Add numeric fields at doc[scope][*path] for both scopes."""
    with _lock, _file_lock():
        doc = _load()
        for scope in ("lifetime", "session"):
            node = doc.setdefault(scope, {})
            for k in path:
                node = node.setdefault(k, {})
                if not isinstance(node, dict):
                    return
            for f, v in fields.items():
                node[f] = round(_num(node.get(f, 0)) + v, 6)
        _save(doc)


def anthropic(label, regular=0, creation=0, read=0, output=0, model=None, aborted=False):
    """One API call. aborted=True records a call whose usage the API never
    reported (stream cut by the stop word) so the undercount is visible."""
    try:
        p_in, p_write, p_read, p_out = _prices(label, model)
        cost = (regular * p_in + creation * p_write + read * p_read + output * p_out) / 1e6
        _bump(("anthropic", label), calls=1, input=regular, cache_write=creation,
              cache_read=read, output=output, cost_usd=cost,
              aborted=1 if aborted else 0)
    except Exception:
        pass


def elevenlabs(chars, cached=False):
    try:
        if cached:
            _bump(("elevenlabs",), cache_hits=1, cache_chars=chars)
        else:
            _bump(("elevenlabs",), requests=1, chars=chars)
    except Exception:
        pass


def openai_stt(seconds=0.0):
    try:
        _bump(("openai",), stt_calls=1, stt_seconds=float(seconds or 0.0))
    except Exception:
        pass
