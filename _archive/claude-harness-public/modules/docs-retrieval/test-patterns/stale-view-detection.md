# Test Pattern: Stale-View Detection (Hand-Edit Guard)

Generic pre-commit hook pattern for detecting hand-edits and stale
regeneration of files emitted by a generator. Protects the single-writer
invariant (LL-067) for generated views: MANIFESTs, per-axis views,
`00-index.md`, `registry.yaml`, etc.

## Mechanism

Every generated file carries a hash header on its first line:

```
<!-- generated: {ISO8601 UTC} | source-sha: {sha256} | generator: {script}@v1 -->
```

The hook walks every generated file under a known glob set, extracts the
`source-sha` from the header, recomputes it from the current inputs, and
compares. Any mismatch is a failure — either the file is stale relative to
its inputs (re-run the generator) or the file was hand-edited (revert and
fix the source).

## Single-writer invariant

Every generated file has exactly one writer: the generator script named in
its header. Pre-commit enforces this: any commit that touches a generated
file without re-running the generator fails with:

```
HAND-EDIT DETECTED: <file> — run <generator> to regenerate
```

## Pre-commit integration

Add to `.claude/settings.json` PreCommit hooks:

```json
{
  "PreCommit": [
    { "command": "bash scripts/detect_hand_edits.sh --staged-only" }
  ]
}
```

`--staged-only` limits scanning to files in `git diff --cached` for speed.
CI runs the detector without the flag to check every generated file.

## Hash computation

Deterministic over inputs (sorted by relative path):

```
source-sha = sha256(concat(
  for each input (sorted):
    relative_path || NUL || raw_bytes_LF_normalized || NUL
))
```

CRLF→LF normalization keeps hashes stable across platforms. The timestamp
in the header is wall-clock (debugging aid) and is NOT part of the hash.

## Reference implementation

See `../scripts/detect_hand_edits.sh` for the canonical implementation.
Bash-based for fast pre-commit startup (no Python cold-start per hook).

## Origin

Extracted from `rev1_2` / Plan 233 §2 and ADR-143. The same pattern applies
to any project emitting derived markdown, YAML, or JSON files alongside
authored sources.
