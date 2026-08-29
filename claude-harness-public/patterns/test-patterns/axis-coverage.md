# Test Pattern: Axis Coverage

## The Pattern

Verify that a closed vocabulary (axis values, enum members, tag registry) is fully exercised by the corpus: every registered value has at least one artifact using it, and every value used by any artifact is registered. Detect dead enum members and unregistered values.

## When To Use

Any project with a closed vocabulary governing artifact classification — axis values, status enums, category tags, type classifications. Coverage checks catch two failure modes: dead vocabulary (entries that have no users and should be retired) and unregistered values (artifacts using values that bypass governance).

## Invariants

### AC-COV-01 — No Unregistered Values (hard fail)

For every frontmatter value on a closed-vocabulary axis in every artifact:
- The value must exist in the current registry (or equivalent enum source)
- If not: fail with the specific file, field, and offending value
- Rationale: unregistered values bypass governance and cannot be relied on by generators or retrieval

### AC-COV-02 — No Dead Registered Values (warn)

For every registered value in the vocabulary:
- Count the number of artifacts in the corpus that use it
- If zero: warn that the value is dead and should be reviewed
- Rationale: dead values bloat the vocabulary and confuse new authors about what to use

### AC-COV-03 — Superseded Values Have Users or Are Retired

If the vocabulary supports supersession (values can be marked `deprecated` with a pointer to a replacement):
- Every non-retired value must be either `active` with users, or `deprecated` with at least one artifact still using it (for migration detection)
- Retired values must have no users

## Dead-Enum Detection Algorithm

```
for each registered value V on each axis:
    count = number of artifacts whose frontmatter lists V on this axis
    if count == 0:
        emit warning: "dead: {axis}={V} has no users"
    elif V.status == 'deprecated' and count > 0:
        emit info: "deprecation migration pending: {count} artifacts still use {axis}={V}"
```

## Unregistered-Value Detection Algorithm

```
for each artifact:
    for each axis in artifact.frontmatter.axes:
        for each value in axis.values:
            if value not in registry[axis]:
                emit error: "unregistered: {file} has {axis}={value} not in registry"
```

## Exit Codes

- `0` — all coverage checks pass (no unregistered values; dead warnings are non-fatal)
- `2` — at least one unregistered value found (AC-COV-01 fails)
- With `--strict`: warnings become errors; dead values fail the run

## Reporting

Output is per-axis, grouped:

```
axis=stage: 5 values, 5 in use, 0 dead
axis=depth: 4 values, 4 in use, 0 dead
axis=layer: 10 values, 8 in use, 2 dead
  dead: layer=sgs (no users)
  dead: layer=bng (no users)
axis=concern: 10 values, 10 in use, 0 dead
```

This format makes it easy to spot over-engineered vocabularies (many dead values = vocabulary grew past actual need) and under-governed ones (many unregistered values = authors bypassing the registry).

## Integration With Generators

If the project generates per-value view files (e.g., `docs/_views/by-layer/grammar.md`), the coverage check and the view generator share the same source of truth (the registry). A dead value still gets a view file, but the view file displays "No artifacts currently tagged" — making the dead enum visible at retrieval time as well.

## Origin

`rev1_2` (Plan 232, TS-126). Invariants AC-COV-01 and AC-COV-02 are direct lifts from the project's axis coverage test spec.

## Related

- `anti-patterns/closed-tag-taxonomy.md` — why closed vocabularies need coverage checks
- `decision-guides/multi-axis-vs-flat-taxonomy.md` — where this pattern fits in the architecture
- `test-patterns/frontmatter-schema-validator.md` — complementary schema validation
