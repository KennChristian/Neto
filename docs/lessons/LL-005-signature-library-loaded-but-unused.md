# LL-005: `signature_library.json` is loaded but never sent to inference

* Date: 2026-05-16
* Severity: moderate
* Related: [ADR-0003](../decisions/0003-reject-embeddings-for-v1.md)

## Symptom

The synthesis pipeline produces `app/artifacts/signature_library.json`
containing 684 normalized signature phrases from CJ's corpus. The app
loads this file at startup (it lives on the `CorpusArtifacts` object).
On 2026-05-16, while explaining the inference call to the user, the
question "is voice_card the signature phrases?" surfaced the fact that
the loaded library is **not** referenced by `build_context()` and is
therefore not in any inference prompt. The model only sees the ~30-50
example phrases inlined in `voice_card.md`.

## 5 Whys

1. **Why isn't the signature library reaching inference?**
   `build_context()` does not look it up.
2. **Why doesn't `build_context()` look it up?** When `build_context()`
   was written, the voice card already inlined a representative sample
   of phrases; the larger library wasn't slotted into the per-turn
   context.
3. **Why was the loader wired but the consumer not?** Because loading
   followed the pattern "load every artifact at startup so it's
   available." Using each loaded artifact in `build_context()` was a
   separate step that didn't happen for this one.
4. **Why didn't the omission show up earlier?** No automated test
   asserts which artifacts reach the inference call. Manual smoke
   tests verify the *behavior* of responses (twin beacons, signature
   closers) — which the inlined examples in `voice_card.md` already
   produce well enough — not the *coverage* of the library.
5. **Why is verifying coverage hard without tests?** Because the only
   way to confirm what reaches the model is to inspect the assembled
   prompt programmatically. Without a test that does this, "loaded"
   was conflated with "used."

## Root Cause

The loader-then-consumer pipeline was implemented in two steps and the
second step was skipped for `signature_library.json`. No test or
assertion enforced "every loaded artifact is referenced by
`build_context()`," so the gap stayed invisible.

## Fix Applied

Documented as a gap in [handover 2026-05-16](../handover_claude_code_2026-05-16.md)
§7 (row "`signature_library.json` loaded but never sent to inference")
and §8 (tech debt). A planned task to surface the relevant phrases for
the routed primary topic into `build_context()` is item #5 in §10 of
the same doc — *"Surface `signature_library.json` to inference for the
primary topic"* — estimated at 1-2 hours; may require indexing the
library by topic first. Wiring will be in
[app/cj_chat.py](../../app/cj_chat.py) `build_context()`.

## Generalizable Lesson

When you add a loader, immediately verify that the loaded data reaches
the consumer that motivated the load. "It's in memory" and "it's in the
prompt" are not the same. A two-line check at the end of the
consumer's assembly — e.g. assert each expected artifact appears in
the rendered context, or print the artifact sizes flowing into the
LLM call — would catch this class of bug at the cost of seconds.
