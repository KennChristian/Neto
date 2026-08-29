# Anti-Pattern: Stale Output

## The Pattern

A configuration file, transformation rule, or schema definition is modified, but the output artifacts that depend on it are not regenerated. The outputs reflect the old state of the source, creating a silent divergence between configuration and reality.

## Symptoms

- Output file timestamps are older than source dependency timestamps
- Reports or dashboards show values that don't match current configuration
- Tests pass because they test the generation code path, not the generated output itself
- Changes to configuration are verified in code review but the reviewer doesn't check regenerated outputs

## Root Cause

No automated dependency tracking between source files and output artifacts. Regeneration is a manual step that is easily forgotten, especially when the source change seems minor or when the developer is focused on code changes rather than output artifacts.

## Prevention Rules

1. **Freshness check**: Implement a script that compares output file mtimes against source dependency mtimes. Run as a CI gate or pre-commit hook.
2. **Regeneration reminder**: After modifying any source file, add a checklist item: "Regenerate all affected outputs."
3. **Output-as-code**: Treat output artifacts as generated code — never edit them directly, always regenerate from source.
4. **Contract SLA**: Declare freshness requirements in data contracts. Enforce via automated drift detection.

## Detection

- Compare mtime of output files against mtime of their source dependencies
- Look for output directories with old timestamps while source directories have recent changes
- Search for CI pipelines that test code but don't verify output freshness
- Grep for manual regeneration instructions in README or docs (indicates manual process)

## Origin

Extracted from downstream-project BUG-006/009. Generalized: "output artifact" replaces domain-specific visualization format.
