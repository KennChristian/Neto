# TS-001: Module Manifest Validation

## Model

Schema conformance + cross-reference integrity for `module.yaml` files.

## Test Cases

| ID | Case | Invariant |
|----|------|-----------|
| T1 | YAML lint | Every `module.yaml` parses as valid YAML; required keys present: `id`, `name`, `version`, `description`, `prompt` |
| T2 | Unique IDs | No two modules share the same `id` value |
| T3 | Path existence | Every path listed in `templates`, `scripts`, `test_patterns`, `lessons`, and `hooks` exists on disk relative to the module directory |
| T4 | Relevance completeness | Non-core modules (those without `always_active: true`) have a `relevance` section with ≥1 signal type (`file_signals`, `code_signals`, or `tech_signals`) |
| T5 | Threshold bounds | `0 ≤ relevance.threshold ≤ relevance.max_score` |
| T6 | Dependency validity | Every entry in `depends_on` (if present) references an existing module `id` |
| T7 | Bootstrap order | `bootstrap.phase_order` is unique across all modules; core module has no `phase_order` |

## Verification Method

For each `module.yaml` listed in `registry.yaml`:
1. Parse YAML — assert no syntax errors (T1)
2. Collect all `id` values — assert uniqueness (T2)
3. For each path in manifest lists — assert `os.path.exists(module_dir / path)` (T3)
4. If not `always_active` — assert `relevance` key exists with ≥1 signal list (T4)
5. If `relevance` present — assert `0 ≤ threshold ≤ max_score` (T5)
6. If `depends_on` present — assert each entry matches an `id` in registry (T6)
7. Collect all `bootstrap.phase_order` values — assert uniqueness, assert core has none (T7)

## Automation

Can be implemented as a shell script or Python test that:
```bash
# Pseudocode
for module_yaml in $(yq '.modules[]' registry.yaml); do
  yq '.' "$module_yaml" || fail "T1: YAML parse error"
  # ... remaining checks
done
```
