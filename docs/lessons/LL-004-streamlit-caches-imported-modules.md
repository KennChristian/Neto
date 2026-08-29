# LL-004: Streamlit caches imported modules across reloads

* Date: 2026-05-15
* Severity: minor
* Related: [ADR-0008](../decisions/0008-streamlit-dashboard-operator-ui.md)

## Symptom

Edited `app/cj_chat.py` (e.g., a TTS pause length, a phonetic
substitution). Saved. Streamlit auto-reloaded `dashboard.py` and the
page refreshed. The dashboard ran the new turn — but the edited
behavior in `cj_chat.py` did not take effect. The change appeared to
have been ignored, suggesting (incorrectly) that the file was wired
somewhere else.

## 5 Whys

1. **Why didn't the edit to `cj_chat.py` take effect?** Streamlit did
   not pick up the change.
2. **Why didn't Streamlit pick up the change?** Streamlit's
   auto-reload watches the script file (`dashboard.py`) and reruns it
   on edit, not imported modules.
3. **Why doesn't it reload imported modules?** Because Streamlit
   re-executes `dashboard.py` from the top, but Python's `import`
   machinery returns the already-loaded module object from `sys.modules`
   — it does not re-read the file unless explicitly told to.
4. **Why is the import machinery designed that way?** Re-importing on
   every reference would break the language's invariants around module
   identity and would be expensive. Module caching is a Python feature,
   not a Streamlit one.
5. **Why was this a surprise?** Because Streamlit's "edit and watch
   it reload" experience reads as "edit any file and watch it reload,"
   so the boundary between watched script and cached import is
   non-obvious.

## Root Cause

Streamlit's file watcher targets the entry script; Python's `import`
machinery caches imported modules. Combining the two means edits to an
imported module don't take effect until the Streamlit process is
restarted.

## Fix Applied

Operator note documented in [PROJECT.md](../../PROJECT.md) §14
(troubleshooting) and in [handover 2026-05-16](../handover_claude_code_2026-05-16.md) §8
(row "Streamlit caches imported modules across reloads"). Workflow:
Ctrl+C the Streamlit process and re-run `streamlit run dashboard.py`
after editing any file under `app/cj_chat.py` (or any other module
imported by `dashboard.py`). No code fix is appropriate — this is a
Streamlit/Python behavior, not a bug.

## Generalizable Lesson

When a hot-reload tool seems to skip your edit, check whether the file
you edited is the watched entry point or a transitive import. Watched
files reload; imported modules don't (without explicit
`importlib.reload`). This applies to Streamlit, but also to Jupyter
notebooks, Flask's `--reload`, FastAPI's `--reload`, and any other
auto-reload mechanism. If you find yourself thinking "the change didn't
apply," restart the process before assuming anything subtler.
