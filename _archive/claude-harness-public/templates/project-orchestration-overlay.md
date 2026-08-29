# {PROJECT_NAME} — Orchestration Overlay

> **Purpose:** Project-specific companion to the generic orchestration prompt. Contains health check commands, model assignments, and verification items unique to this project.
>
> **Usage:** Referenced by the orchestration prompt. Update this file as the project evolves.

---

## Health Check Commands

Run after every plan to confirm nothing broke.

```bash
# 1. Infrastructure health — all services/processes running
{INFRA_HEALTH_CMD}

# 2. Build system clean — no pending migrations, no stale builds
{BUILD_CLEAN_CMD}

# 3. System checks pass — framework-level validation
{SYSTEM_CHECK_CMD}

# 4. All tests pass — full test suite
{TEST_CMD}

# 5. Cross-boundary checks — API contracts, type safety
{CROSS_BOUNDARY_CMD}
```

---

## Model Assignment Table

Scored using the complexity rubric from the orchestration prompt.

| Plan | C&S | Algo | Orch | UI | Novel | Total | Model |
|------|-----|------|------|----|-------|-------|-------|
| 01   | {1-5} | {1-5} | {1-5} | {1-5} | {1-5} | {sum} | {Haiku/Sonnet/Opus} |

---

## Project-Specific Verification Checklist

Additional items to check beyond the universal checklist in the orchestration prompt:

- [ ] {Project-specific check 1}
- [ ] {Project-specific check 2}
- [ ] {Project-specific check 3}

---

## Synthetic Test Data

Seed commands, fixture locations, and data isolation strategies for this project.

### Seed Command

```bash
{SEED_CMD: e.g., python manage.py seed_data, npm run seed, cargo run --bin seed}
```

### Fixture Locations

| Directory/File | Purpose |
|----------------|---------|
| `{FIXTURE_PATH}` | {Description of test fixtures} |

### Data Isolation

{Describe cross-tenant/cross-org/cross-user isolation testing strategy, if applicable.}

---

## Integration Test Scenarios

End-to-end tests that validate cross-plan functionality. Run after major milestones.

### Test 1: {Scenario Name}
**Plans covered:** {list}
{Description of the test scenario and expected outcomes.}
