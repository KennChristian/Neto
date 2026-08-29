# Plan-008: Consistency Enforcement Restructuring

**Objective:** Restructure orchestration-prompt.md Section 8 from MANIFEST-only to a generalized consistency enforcement system.
**Scope:** Section 8 rename + split, Section 6.3 checklist update, TOC update.
**Key constraint:** Preserve existing MANIFEST content verbatim under 8.1; ADR-004 justifies the restructuring.

---

## Depends On

- ADR-004 (Dual-Mechanism Consistency Enforcement Pattern)

---

## Steps

### Step 1: Update TOC

In `core/orchestration-prompt.md`, change the Section 8 TOC entry:

- **Before:** `8. MANIFEST.md Indexing System`
- **After:** `8. Consistency Enforcement Systems`

### Step 2: Restructure Section 8

Replace the Section 8 header and add an introductory paragraph:

```
## 8. Consistency Enforcement Systems

The harness uses a dual-mechanism enforcement pattern (ADR-004) for index-like
artifacts: a PostToolUse hook fires on every Write/Edit to detect drift in real
time, paired with a CI-suitable validation script for batch checking. This pattern
currently covers two systems:
```

### Step 3: Create subsection 8.1

Move all existing MANIFEST content under:

```
### 8.1 MANIFEST.md Indexing
```

No content changes — only demote the existing headings by one level.

### Step 4: Create subsection 8.2

Add new subsection:

```
### 8.2 Registry Enforcement

`registry.yaml` is the source of truth for all modules in the harness. It must
stay in sync with `modules/*/module.yaml` files.

#### Enforcement (Dual Mechanism)

1. **PostToolUse hook** (`check-registry.sh`): Fires on Write|Edit. Detects three cases:
   - Module file created/edited but module.yaml not registered in registry.yaml
   - registry.yaml edited but references nonexistent module.yaml
   - module.yaml deleted but still listed in registry.yaml

2. **CI script** (`validate-registry.sh`): Four-pass validation:
   - Pass 1: All registry entries point to existing module.yaml files
   - Pass 2: All module.yaml files are registered
   - Pass 3: Each module.yaml has required fields (id, name, version, description)
   - Pass 4: Module asset references (prompt, hooks) point to existing files

#### Maintenance

When adding a new module directory under `modules/`, create `module.yaml` first,
then add its path to `registry.yaml`. The PostToolUse hook blocks until both are
consistent.
```

### Step 5: Update Section 6.3 Universal Checklist

Add after the existing MANIFEST checklist item:

```
- [ ] registry.yaml consistent with module directories (if module files changed)
```

---

## Failure Modes

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Section 8 renumbering breaks cross-references elsewhere | Grep for `Section 8` or `§8` across harness docs | Search-and-update all references before committing |
| Existing MANIFEST content corrupted during move to 8.1 | Diff 8.1 content against pre-change Section 8 | Keep content verbatim; only change heading levels |
| TOC entry mismatch with actual header | Manual inspection | Verify TOC matches headers after edit |

## Verifiability

- [ ] TOC entry "8. Consistency Enforcement Systems" matches Section 8 header
- [ ] Section 8.1 content is byte-identical to previous Section 8 content (modulo heading level)
- [ ] Section 8.2 accurately describes check-registry.sh behavior (three cases)
- [ ] Section 8.2 accurately describes validate-registry.sh behavior (four passes)
- [ ] Section 6.3 checklist contains registry.yaml item
- [ ] Grep `"MANIFEST.md Indexing System"` returns zero matches across harness
