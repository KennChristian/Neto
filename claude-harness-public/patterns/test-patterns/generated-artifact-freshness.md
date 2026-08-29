# Test Pattern: Generated-Artifact Freshness

## The Pattern

Verify that a file declared to be generated is actually fresh relative to its inputs. Detect two failure modes: (1) stale generation — the file is older than its source and needs regeneration; (2) hand-edit — the file has been modified outside the generator.

## When To Use

Any project that generates derived artifacts (views, indexes, summaries, cross-reference tables) alongside authored sources. Without freshness verification, drift creeps in through both missed regeneration and well-intentioned hand-edits.

## Hash Header Format

Every generated file carries a machine-readable comment at the top:

```
<!-- generated: {ISO8601 UTC} | source-sha: {sha256-hex} | generator: {script-path}@{version} -->
```

- `generated` — wall-clock timestamp (human debugging; not part of freshness check)
- `source-sha` — SHA-256 of the inputs that produced this file (the freshness oracle)
- `generator` — identity of the tool that wrote the file (single-writer contract)

## Source Hash Computation

Inputs are specified per-generator but must be deterministic:

1. Enumerate inputs in sorted order (lexicographic by relative path)
2. For each input, concatenate: `relative-path + null-byte + file-contents + null-byte`
3. SHA-256 over the full concatenation
4. Record the hex digest in the header

Line-ending normalization (CRLF→LF) happens before hashing to keep hashes stable across platforms.

## Freshness Check

Given a generated file:
1. Extract the `source-sha` from the header
2. Recompute the source hash over the current inputs (using the same algorithm)
3. Compare: match → fresh; mismatch → stale or hand-edited
4. Exit 0 if fresh, exit 2 if drift detected

The check does NOT compare timestamps — only content hashes — because generators re-run on unchanged input produce the same body but a new timestamp. Timestamp-based checks create false positives.

## Hand-Edit Detection

Hand-edits are detected the same way as stale generation: the recomputed hash will not match the header. The pre-commit hook distinguishes the two cases by checking whether the inputs have actually changed:
- **Inputs changed, header old:** stale; user should regenerate
- **Inputs unchanged, file body different from recomputation:** hand-edit; user should revert and fix the source

Both cases reject the commit with a clear, directive message.

## Pre-Commit vs. CI

- **Pre-commit:** fast, approximate check on staged files only. Extract header, recompute hash over the specific inputs, compare.
- **CI:** full sweep across every generated file in the corpus. Catches any drift that pre-commit missed (e.g., regeneration skipped locally).

## Idempotency Corollary

A generator is idempotent if two consecutive runs on unchanged input produce byte-identical output (modulo the timestamp in the header). The freshness check implicitly validates idempotency: if regeneration would produce different output, the hash would differ.

## Origin

`rev1_2` (ADR-143, Plans 231b/232/233). The hash header format and the pre-commit hand-edit detector are direct lifts from the project's `detect_hand_edits.sh` and generator specs.

## Related

- `anti-patterns/hand-edited-generated-artifact.md` — the failure mode this pattern prevents
- `anti-patterns/manifest-schema-drift.md` — sibling failure mode
- `test-patterns/frontmatter-schema-validator.md` — complementary validation pattern
