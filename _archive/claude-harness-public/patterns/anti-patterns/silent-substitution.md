# Anti-Pattern: Silent Substitution

## The Pattern

An input file is replaced with a different file — a different version, a file from a different source, or a corrupted copy — without any identity verification. The pipeline processes it without detecting the substitution, producing output based on wrong input data.

## Symptoms

- Output values change unexpectedly between pipeline runs without any code changes
- Row counts shift without explanation
- Downstream consumers report anomalies that don't trace to code or configuration changes
- The issue is intermittent if the substitution is accidental (e.g., file sync conflicts, manual file copies)

## Root Cause

No identity verification for input files. The pipeline trusts the file path as sufficient identification without validating content properties — checksum, row count, header signature, or schema fingerprint.

## Prevention Rules

1. **Input fingerprinting**: Record checksums (SHA-256), row counts, and column headers for each input file in a manifest or data contract.
2. **Pre-processing verification**: Before processing, verify the input file's fingerprint matches the expected values. Abort on mismatch.
3. **Immutable inputs**: Store input files in a versioned or content-addressed location. Never overwrite — create new versions.
4. **Provenance logging**: Log the identity of every input file processed (path, checksum, size, mtime) for audit trail.

## Detection

- Grep for pipeline entry points that open files by path without any identity assertions
- Look for `read_csv()`, `open()`, or `load()` calls without accompanying checksum or row count checks
- Search for input directories without version control or manifests
- Look for pipeline code that uses relative file paths or glob patterns without validating what was matched

## Origin

Extracted from downstream-project BUG-034. Generalized: "input file" replaces domain-specific data source.
