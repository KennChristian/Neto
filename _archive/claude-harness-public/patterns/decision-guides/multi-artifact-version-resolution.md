# Multi-Artifact Version Resolution

## Problem

Projects that manage two or more independently versioned artifacts (e.g., Schema, API spec, UI kit) often use a single-valued "version impact" column in their plan index. This makes non-primary artifacts invisible to orchestration: a plan that only affects the API spec declares `none` impact because the column assumes the Schema is the only versioned artifact. The result is missed version bumps, stale downstream artifacts, and orchestration blind spots.

## When to Use

- Your project has 2+ independently versioned artifacts
- You use a plan orchestration system that reads impact declarations to decide version bumps
- Non-primary artifacts are currently invisible because the impact column is single-valued

## Artifact Registry Contract

Each artifact type in the project must be registered with a standard set of fields. The registry is the single source of truth for discovery, parsing, and provisioning.

```yaml
artifact_registry:
  SCHEMA:
    name: Schema definition
    glob: "versions/*/schema_*.json"
    version_parse: "v(\\d+)\\.(\\d+)\\.(\\d+)"
    provision: promote_schema.py
    directory_scope: "versions/v{major}.{minor}/"
    resolves_first: true
  API:
    name: API specification
    glob: "api/v*/openapi_*.yaml"
    version_parse: "api-v(\\d+)\\.(\\d+)\\.(\\d+)"
    provision: generate_api_spec.sh
    directory_scope: "api/v{schema}/"
    parent_artifact: SCHEMA
  UIKIT:
    name: UI component kit
    glob: "ui/dist/kit_*.zip"
    version_parse: "kit-(\\d+)\\.(\\d+)\\.(\\d+)"
    provision: build_ui_kit.sh
    directory_scope: "ui/dist/"
    parent_artifact: SCHEMA
```

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Human-readable artifact name |
| `glob` | string | Filesystem discovery pattern to find existing versions |
| `version_parse` | regex | Extract version components from filename or path |
| `provision` | string | Mechanism to create a new version (script path, prompt reference, or manual instruction) |
| `directory_scope` | template | Path template for artifact location; may reference parent artifact's resolved version |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `parent_artifact` | prefix | Artifact whose resolution must complete first (directory dependency) |
| `resolves_first` | boolean | If true, this artifact resolves before all others (only one artifact should set this) |

## Impact Notation

Plans declare their impact on versioned artifacts using `PREFIX:level` notation.

### Format

- **Single artifact:** `SCHEMA:major`, `API:minor`
- **Multiple artifacts:** `SCHEMA:patch, API:minor` (comma-separated)
- **No impact:** `none`
- **Backward compatibility:** Bare `major`/`minor`/`patch` (no prefix) is treated as `{primary_artifact}:{level}` where `primary_artifact` is the one with `resolves_first: true`

### Impact Levels (per artifact)

| Level | When to Set | Example |
|-------|------------|---------|
| `major` | Adds/removes top-level structures, changes data model, breaking changes | `SCHEMA:major` -- new schema version |
| `minor` | Adds optional fields, non-breaking enhancements | `API:minor` -- new endpoint added |
| `patch` | Fixes data, corrects errors, non-functional changes | `UIKIT:patch` -- icon fix |
| `none` | No versioned artifacts affected | Documentation, tooling, prompts |

## Per-Artifact Resolution Loop

The resolution algorithm processes each registered artifact in dependency order and computes a target version.

### Algorithm

```
INPUT: artifact_registry, planned_plans (list of plans with impact declarations)

1. ORDER artifacts:
   - resolves_first=true artifacts first
   - then topological sort by parent_artifact dependency
   - ties broken alphabetically

2. FOR EACH artifact A in order:
   a. DISCOVER
      - Glob filesystem using A.glob
      - Parse versions using A.version_parse
      - Identify latest completed version (highest version number)

   b. SCAN
      - Collect all Artifact Impact entries from planned_plans
        that contain A.prefix (e.g., filter for "SCHEMA:*")
      - If bare values exist and A.resolves_first, include those
        (backward compatibility)

   c. COMPUTE target version
      - Find highest impact level among scanned entries:
        major > minor > patch > none
      - Apply version bump:
        - major: increment major, reset minor and patch to 0
        - minor: increment minor, reset patch to 0
        - patch: increment patch
        - none or no entries: target = latest (no bump)

   d. PROVISION
      - IF target != latest:
        - Invoke A.provision with target version
        - If A.parent_artifact exists, use parent's resolved
          directory as base path

   e. RECORD
      - Store A.resolved_target for use by dependent artifacts
      - Store A.resolved_directory for directory_scope resolution

3. RETURN resolved targets for all artifacts
```

### Resolution Order Example

Given artifacts SCHEMA (resolves_first), API (parent: SCHEMA), UIKIT (parent: SCHEMA):

1. SCHEMA resolves first -- discovers v2.3.0, plans declare SCHEMA:major, target becomes v3.0.0
2. API resolves second -- uses SCHEMA's resolved directory as parent; discovers api-v1.5.2, plans declare API:minor, target becomes api-v1.6.0
3. UIKIT resolves third -- uses SCHEMA's resolved directory as parent; no UIKIT impact declared, target stays kit-1.0.0

## Guard Rules

These rules prevent common resolution errors.

### Rule 1: Read-Only Completed Versions

Once an artifact version is marked completed, its files are read-only. New changes require a version bump. Never modify completed version artifacts in place.

### Rule 2: Single Target Per Session

Each artifact resolves to exactly one target version per orchestration session. If multiple planned plans declare different impact levels for the same artifact, the highest level wins.

### Rule 3: Artifact Independence

A plan declaring only `API:minor` does NOT trigger a SCHEMA version bump. Each artifact resolves only from its own prefix in the impact column. If no plans declare `SCHEMA:*` impact, SCHEMA target equals latest (no bump).

### Rule 4: Hierarchical Dependency (Directory Only)

When a parent artifact bumps version, child artifacts use the parent's new directory as their base path. This is a directory dependency, not a version dependency. The child artifact's own version number is unaffected unless plans explicitly declare impact on that child.

Example: SCHEMA bumps from v2 to v3. API's directory_scope changes from `api/v2/` to `api/v3/`, but API's own version number (api-v1.5.2) is unchanged unless plans declare `API:*` impact.

### Rule 5: Registry Completeness

Every prefix used in impact declarations must have a corresponding entry in the artifact registry. An unrecognized prefix is a parse error that halts resolution.

## Session Output: Progressive Disclosure

Resolution results are presented at three tiers of detail.

### Tier 0: Compact Summary (Single Line)

```
Versions: Schema v3.0.0, API api-v1.6.0, UIKit kit-1.0.0
```

Use in status bars, compact summaries, and automated reports.

### Tier 1: Per-Artifact Detail

```
## Version Context
### Schema
- Latest completed: v2.3.0 | Highest impact: SCHEMA:major | Target: v3.0.0
### API
- Latest completed: api-v1.5.2 | Highest impact: API:minor | Target: api-v1.6.0
### UIKit
- Latest completed: kit-1.0.0 | Highest impact: none | Target: kit-1.0.0 (no bump)
```

Default output for orchestration sessions.

### Tier 2: Full Resolution Trace

```
## Resolution Trace
1. SCHEMA: glob "versions/*/schema_*.json" -> [v2.3.0, v2.2.1, v2.2.0, ...]
   Scanned 5 plans: [Plan 42 SCHEMA:major, Plan 45 SCHEMA:minor]
   Highest: major -> target v3.0.0
   Provision: promote_schema.py --target v3.0.0
2. API: glob "api/v*/openapi_*.yaml" -> [api-v1.5.2, api-v1.5.1, ...]
   Parent resolved: SCHEMA v3.0.0 -> directory "versions/v3.0/"
   Scanned 5 plans: [Plan 43 API:minor]
   Highest: minor -> target api-v1.6.0
   Provision: generate_api_spec.sh --target api-v1.6.0 --schema-dir versions/v3.0/
3. UIKIT: glob "ui/dist/kit_*.zip" -> [kit-1.0.0]
   Parent resolved: SCHEMA v3.0.0 -> directory "versions/v3.0/"
   Scanned 5 plans: (none)
   Highest: none -> target kit-1.0.0 (no bump)
   Provision: skipped
```

Available on demand for debugging and audit.

## Worked Examples

### Example A: Secondary-Artifact-Only Session

Plans: Plan 43 (`API:minor`)

- SCHEMA: no SCHEMA:* impact -> target = v2.3.0 (no bump)
- API: API:minor -> target = api-v1.6.0, provisioned in api/v2.3/
- UIKIT: no impact -> target = kit-1.0.0 (no bump)

Result: Only API is provisioned. SCHEMA and UIKIT are untouched.

### Example B: Primary-Artifact-Only Session

Plans: Plan 42 (`SCHEMA:major`)

- SCHEMA: SCHEMA:major -> target = v3.0.0
- API: no API:* impact -> target = api-v1.5.2 (no bump)
- UIKIT: no impact -> target = kit-1.0.0 (no bump)

Result: Only SCHEMA is provisioned. Cascade warnings may fire for API and UIKIT (see [artifact-cascade-staleness](artifact-cascade-staleness.md)).

### Example C: Mixed Session

Plans: Plan 42 (`SCHEMA:major`), Plan 43 (`API:minor`)

- SCHEMA: SCHEMA:major -> target = v3.0.0
- API: API:minor -> target = api-v1.6.0, directory = api/v3.0/ (follows SCHEMA)
- UIKIT: no impact -> target = kit-1.0.0 (no bump)

Result: SCHEMA and API both provisioned. API output goes to new SCHEMA directory.

### Example D: No Version Impact

Plans: Plan 50 (`none`), Plan 51 (`none`)

- All artifacts: no impact -> all targets = latest (no bump)

Result: No provisioning needed.

## See Also

- [artifact-cascade-staleness](artifact-cascade-staleness.md) -- detecting when upstream bumps may cause downstream staleness
- [progressive-disclosure](progressive-disclosure.md) -- general progressive disclosure pattern
