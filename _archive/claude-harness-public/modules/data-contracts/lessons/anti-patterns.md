# Data Contract Anti-Patterns

Lessons extracted from downstream projects about common pitfalls when working with data contracts and output governance.

## AP-1: Configuration Mapping Integrity Gap

**The Pattern**: A configuration file maps integer codes to human-readable labels. The mapping passes structural validation (valid YAML/JSON, all keys present) but contains semantic errors — wrong labels, missing entries, or stale values that don't match the actual data.

**Symptoms**: Output artifacts contain incorrect labels that look plausible. Downstream consumers display wrong information without errors. Automated tests pass because they validate structure, not semantics.

**Root Cause**: Validation checks structure (syntax, required keys) but not semantics (do the values actually correspond to reality?). There is no ground-truth comparison step.

**Prevention**: Add semantic validation that compares configuration mapping values against an authoritative source. Include "spot-check" test cases that assert specific known mappings.

**Detection**: Grep for validation code that checks `is not None` or `len() > 0` without comparing actual values. Look for configuration files that are validated only by schema, not by content.

## AP-2: Stale Output After Source Change

**The Pattern**: A source file (configuration, schema, transformation rule) is modified but the output artifacts that depend on it are not regenerated. The outputs become stale — they reflect the old source state.

**Symptoms**: Output files have older timestamps than their source dependencies. Reports or dashboards show outdated values. Tests pass because they test the generation code, not the generated output.

**Root Cause**: No dependency tracking between source files and output artifacts. Regeneration is manual and easily forgotten.

**Prevention**: Implement freshness checks that compare output timestamps against source timestamps. Add contract `slaProperties.freshness` rules. Use drift detection hooks that warn when sources change without output regeneration.

**Detection**: Compare mtime of output files against mtime of their source dependencies. Look for contract freshness SLAs that are not enforced by automated checks.

## AP-3: Input File Identity Substitution

**The Pattern**: An input file is replaced with a different file (different version, different source, or corrupted copy) without verification. The pipeline processes it without detecting the substitution, producing incorrect output.

**Symptoms**: Output values change unexpectedly between runs. Row counts shift without explanation. Downstream consumers report anomalies that don't trace to code changes.

**Root Cause**: No identity verification for input files. Pipeline trusts file path without validating content fingerprint, row count, or header signature.

**Prevention**: Record input file checksums, row counts, and header signatures in contracts or manifests. Verify identity before processing. Alert on unexpected changes.

**Detection**: Look for pipeline entry points that open files by path without any identity check. Grep for `open()` or `read_csv()` calls without accompanying assertions on file properties.

## Origin

Extracted from kinyen-equiplot BUG-014, BUG-006/009, BUG-034. Generalized to remove domain-specific terminology.
