# LL-003: `python-dotenv`'s default `override=False` silently kept an empty `ANTHROPIC_API_KEY`

* Date: 2026-05-15
* Severity: moderate

## Symptom

App raised an authentication error from the Anthropic SDK on startup
even though the `app/.env` file contained a valid `ANTHROPIC_API_KEY`.
The `.env` file had been loaded — no exception from `load_dotenv()` —
but the SDK behaved as if the key were missing or empty.

## 5 Whys

1. **Why did the SDK fail auth?** It saw an empty `ANTHROPIC_API_KEY`
   in the environment.
2. **Why was the environment value empty when the `.env` was valid?**
   The local shell already had `ANTHROPIC_API_KEY=""` exported in its
   profile.
3. **Why didn't `load_dotenv()` overwrite the empty shell value with
   the valid `.env` value?** `python-dotenv`'s default is
   `override=False` — if a variable is already set in the environment,
   `.env` will not change it.
4. **Why does an empty string count as "already set"?** Because
   `python-dotenv` checks whether the variable exists in `os.environ`,
   not whether it has a non-empty value. An empty string is "set."
5. **Why was the failure mode silent rather than loud?** Because
   `load_dotenv()` returns `True` on success of *loading the file*,
   not on success of *applying* the values. There was no exception or
   warning to surface that a value was skipped.

## Root Cause

`python-dotenv`'s default `override=False` treats an empty shell-set
variable as already-set and silently skips the `.env` value. The
combination of "default behavior is non-override" and "empty string is
already-set" produced an invisible misconfiguration.

## Fix Applied

[app/cj_chat.py](../../app/cj_chat.py:47-50) loads `.env` with
`load_dotenv(..., override=True)`. [handover 2026-05-16](../handover_claude_code_2026-05-16.md)
§6 row "python-dotenv with `override=True`" documents the reason:
*"User's shell environment had an empty `ANTHROPIC_API_KEY` shadowing
the `.env`. Default `override=False` silently kept the empty value."*
[PROJECT.md](../../PROJECT.md) §14 (troubleshooting) carries the
operator-facing note: *"`.env` is loaded with `override=True` so an
empty shell var won't shadow it."*

## Generalizable Lesson

When loading `.env` files in environments where the shell may have
shell-set variables (CI, development machines with profile exports,
mixed-config environments), pass `override=True` — or explicitly
unset the shell value before launch. More generally: any "merge two
config sources" code path needs a clear rule for empty values and a
loud failure when the rule produces a surprise. "Already set in the
environment" is rarely what you actually mean; "set to a non-empty
value" usually is.
