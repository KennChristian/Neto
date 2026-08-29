# Plan-006: Backward Compatibility

## Objective

Ensure existing consumers are not broken by the restructuring.

## Dependencies

- Plans 001-005

## Scope

1. Create 4 root-level symlinks:
   - `orchestration-prompt.md` → `core/orchestration-prompt.md`
   - `bootstrap-prompt.md` → `core/bootstrap-prompt.md`
   - `verifier-creator.md` → `modules/verification/prompt.md`
   - `data-contracts-prompt.md` → `modules/data-contracts/prompt.md`
2. Create `MIGRATION.md` with path mapping table and migration instructions
3. Update `README.md` with new structure documentation
4. Update downstream project references (optional — symlinks cover it)

## Verification Criteria

- [ ] `ls -la` shows symlinks at root level
- [ ] `cat orchestration-prompt.md` returns content (symlink resolves)
- [ ] `git ls-files` tracks symlinks
- [ ] README.md documents new structure

## Failure Modes

- Windows symlink issues → document in MIGRATION.md, offer copy alternative
- CI shallow clone → document workaround
