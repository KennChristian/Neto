# Test Pattern: Verification Audit Test Cases

## Purpose

Validate that verification-audit-agents correctly assess implementation work against plan milestones, detect regressions, and produce accurate audit reports.

## When to Use

- After generating a new verification-audit-agent for a project
- When modifying the verification agent template
- As part of harness self-testing

## Test Cases

### TC-1: Plan Criteria Coverage
The agent must verify every criterion listed in a plan's "Verification Criteria" section. No criteria may be silently skipped.

**Verification**: Compare audit report criteria table rows against plan document criteria list. Assert 1:1 mapping.

### TC-2: Regression Detection
When a previously-passing test fails after new work, the agent must flag it as a regression and identify the likely cause.

**Verification**: Provide the agent with test output showing a new failure in a previously-completed plan's test suite. Assert the audit report contains a regression flag.

### TC-3: False Positive Prevention
The agent must not flag issues that are documented as known/accepted in the plan or project documentation.

**Verification**: Provide the agent with test output containing known failures documented in the plan. Assert the audit report does not flag them as new issues.

### TC-4: Cross-Plan Impact Assessment
When work on Plan N could affect Plan M's functionality, the agent must identify and test the cross-plan impact.

**Verification**: Provide the agent with a plan that modifies shared code. Assert the audit report lists affected prior plans and their test status.

### TC-5: Incomplete Work Detection
When a plan is only partially implemented (some verification criteria pass, others fail), the agent must recommend keeping the plan in `pending` status.

**Verification**: Provide partial implementation. Assert audit report status is PARTIAL or FAIL, not PASS.

### TC-6: Audit Report Completeness
Every audit report must include: overall status, per-criterion results table, regression check table, files audited count, issues found count, recommendations, and approval decision.

**Verification**: Parse audit report markdown. Assert all required sections present.

## Anti-Pattern: False Failure

The agent reports a criterion as FAIL when the implementation is actually correct, due to:
- Misreading test output format
- Conflating warnings with errors
- Checking the wrong files or directories
- Using stale cached information

**Prevention**: Agent should re-read relevant files before making judgments. Test output parsing should distinguish errors from warnings explicitly.

## Origin

Generalized from downstream project verification audit experiences. Applicable to any plan-driven development workflow using verification agents.
