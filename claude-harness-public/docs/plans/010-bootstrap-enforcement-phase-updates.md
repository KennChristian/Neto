# Plan-010: Bootstrap Enforcement & Phase Updates

**Objective:** Update bootstrap-prompt.md to include registry enforcement in Phase 8, planning module in the phase table, and orchestration prompt in completion.
**Scope:** Phase 8 expansion, Module Phase Order table, Activated Module Phases note, Completion section.
**Key constraint:** Bootstrap references orchestration prompt sections; Plans 008/009 must be executed first.

---

## Depends On

- Plan-008 (orchestration Section 8 restructured)
- Plan-009 (orchestration Section 4.3 and 10.1 updated)

---

## Steps

### Step 1: Rename and expand Phase 8

Rename header:
- **Before:** `## Phase 8: Set Up Enforcement`
- **After:** `## Phase 8: Set Up Consistency Enforcement`

Add steps 6-8 after existing step 5:

```
6. **Generate `scripts/check-registry.sh`:**
   - Copy from `core/scripts/check-registry.sh`
   - Make executable (`chmod +x`)

7. **Generate `scripts/validate-registry.sh`:**
   - Copy from `core/scripts/validate-registry.sh`
   - Make executable (`chmod +x`)

8. **Merge module hook fragments:**
   For each activated module that declares `hooks` in its `module.yaml`:
   - Read `hooks/{fragment-name}` from the module directory
   - Merge hook entries into the `.claude/settings.json` generated in step 5
   - Deduplicate matchers — combine hooks under the same matcher/event
   Example: the planning module contributes a PreToolUse hook on EnterPlanMode
```

### Step 2: Update Module Phase Order table

Replace the current table with:

```
| Order | Module | Phase Name |
|-------|--------|------------|
| 9 | planning | Planning Mode — injects planning protocol into CLAUDE.md, installs PreToolUse hook on EnterPlanMode |
| 10.5 | data-contracts | Data Contracts — runs relevancy qualification, artifact discovery, contract scaffolding, governance setup, integration |
| 11 | verification | Verification Agent — runs codebase exploration, interview, scenario generation, agent assembly, validation |
```

### Step 3: Add module type distinction to Activated Module Phases

After step 4 ("Add relevant Deep Docs entries to root CLAUDE.md"), add:

```
**Module type distinction:** Modules serve different roles during bootstrap:
- **Context modules** (e.g., planning) inject operational context (hooks, CLAUDE.md
  sections) that shape how future sessions behave
- **Artifact modules** (e.g., data-contracts) generate project artifacts (schemas,
  contracts) during bootstrap
- **Agent modules** (e.g., verification) generate autonomous agents for later use

The module's `prompt.md` describes its specific bootstrap behavior.
```

### Step 4: Update Completion section

Add to Core Infrastructure list:
```
- scripts/check-registry.sh
- scripts/validate-registry.sh
```

Update Next Steps item 4:
```
4. Start executing plans using the orchestration prompt
   (see `core/orchestration-prompt.md`, Section 4.3 for plan-to-execution handoff)
```

---

## Failure Modes

| Failure | Detection | Mitigation |
|---------|-----------|------------|
| Phase 8 step numbering conflicts with existing steps | Count steps in Phase 8 before and after | Verify sequential numbering 1-8 |
| Module Phase Order table out of sync with module.yaml phase_order values | Compare table values against each module.yaml | Grep for `phase_order` in all module.yaml files |
| Hook fragment merging instructions are ambiguous | Test with a fresh bootstrap on a clean project | Provide explicit example (planning module's PreToolUse) |

## Verifiability

- [ ] Phase 8 header says "Consistency Enforcement"
- [ ] Phase 8 includes steps for check-registry.sh and validate-registry.sh
- [ ] Phase 8 includes hook fragment merging step with example
- [ ] Module Phase Order table includes planning module at order 9
- [ ] Activated Module Phases section distinguishes module types
- [ ] Completion section lists registry enforcement scripts
- [ ] Completion section references orchestration prompt Section 4.3
