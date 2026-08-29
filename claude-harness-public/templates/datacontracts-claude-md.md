# Data Contracts — CLAUDE.md Template

> **Usage:** Fill placeholders and save as `docs/datacontracts/CLAUDE.md`.

---

```markdown
# Data Contracts

## Conventions

{CONVENTIONS}

## Validate

{VALIDATE_COMMANDS}

## Contract Inventory

{CONTRACT_INVENTORY}

## Versioning Quick Reference

| Change type | Version bump | Examples |
|-------------|-------------|---------|
| Breaking schema change (column removed, type changed, renamed) | MAJOR | `1.0.0` → `2.0.0` |
| New column/field added, new quality rule | MINOR | `1.0.0` → `1.1.0` |
| Description fix, label correction, rule threshold tweak | PATCH | `1.0.0` → `1.0.1` |

## Adding a New Contract

1. Choose the archetype template from `claude-harness/templates/`:
   - `odcs-contract-csv.yaml` — Persisted CSV/Parquet files
   - `odcs-contract-db-table.yaml` — Database tables/views
   - `odcs-contract-api-response.yaml` — REST/GraphQL API responses
   - `odcs-contract-inmemory-config.yaml` — Typed runtime configs
2. Copy the template to `docs/datacontracts/{kebab-name}.odcs.yaml`
3. Fill all `{PLACEHOLDER}` values from code inspection
4. Select quality rules from `claude-harness/templates/odcs-quality-rules-catalog.md`
5. Set `status: draft`, then promote to `active` after review
6. Update the Contract Inventory table above
7. If a drift hook is configured, add the output path mapping

## Reference

{REFERENCE_LINKS}
```
