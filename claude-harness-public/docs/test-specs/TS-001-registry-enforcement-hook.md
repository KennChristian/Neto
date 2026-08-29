# TS-001: Registry Enforcement Hook Behavior

**Objective:** Verify check-registry.sh correctly detects all three drift cases.
**Scope:** PostToolUse hook behavior for Write|Edit on module and registry files.
**Method:** State-based model testing — define states and transitions.

---

## State Model

### States

| State | Description |
|-------|-------------|
| S0: Consistent | All module.yaml files registered in registry.yaml; all registry entries point to existing files |
| S1: Unregistered Module | A module.yaml exists in modules/ but is not listed in registry.yaml |
| S2: Dangling Reference | registry.yaml lists a module.yaml that does not exist on disk |
| S3: Stale Entry | A module.yaml was deleted but registry.yaml still references it |

### Transitions (tool_input events)

| From | Event | To | Hook Behavior |
|------|-------|----|---------------|
| S0 | Write new `modules/foo/module.yaml` | S1 | Exit 2: "module.yaml is not listed in registry.yaml" |
| S0 | Edit `modules/foo/bar.py` (module.yaml exists, registered) | S0 | Exit 0: no action |
| S0 | Edit `modules/foo/bar.py` (module.yaml exists, NOT registered) | S1 | Exit 2: "module.yaml is not listed in registry.yaml" |
| S0 | Edit registry.yaml to add nonexistent module | S2 | Exit 2: "references missing module files" |
| S0 | Edit registry.yaml to remove existing module | S1 | Exit 2: "Unregistered modules found" |
| S1 | Edit registry.yaml to add the module | S0 | Exit 0: consistent |
| S0 | Delete module.yaml (registry still references it) | S3 | Exit 2: "was deleted but is still listed" |
| S3 | Edit registry.yaml to remove the entry | S0 | Exit 0: consistent |

### Invariant

After any sequence of transitions, if the system is in S0, running `validate-registry.sh` must output "PASSED" with exit 0. If in S1/S2/S3, it must output "FAILED" with exit 1.

---

## Scenarios

### Scenario 1: New module creation (happy path)
1. Create `modules/new-mod/module.yaml` with required fields
2. **Expected:** Hook fires, exit 2, message says "not listed in registry.yaml"
3. Add `modules/new-mod/module.yaml` to registry.yaml
4. **Expected:** Hook fires, exit 0

### Scenario 2: Registry cleanup after module deletion
1. Delete `modules/old-mod/module.yaml`
2. Edit any file (triggers hook)
3. **Expected:** Hook detects stale registry entry (if file_path was the deleted module.yaml)
4. Remove entry from registry.yaml
5. **Expected:** Hook fires on registry edit, validates all remaining entries exist, exit 0

### Scenario 3: Typo in registry.yaml path
1. Edit registry.yaml, add `modules/typo-mod/module.yaml` (does not exist)
2. **Expected:** Hook fires, exit 2, message says "references missing module files"

### Scenario 4: File outside modules/ (no-op)
1. Edit `core/orchestration-prompt.md`
2. **Expected:** Hook fires, file is not in modules/, exit 0

### Scenario 5: File outside harness (no-op)
1. Edit a file with no ancestor registry.yaml
2. **Expected:** Hook cannot find harness root, exit 0
