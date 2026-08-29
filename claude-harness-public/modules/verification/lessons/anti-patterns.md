# Verification Module Anti-Patterns

Lessons extracted from downstream projects about common pitfalls in verification audit workflows.

## AP-1: False Failure from Stale Context

**The Pattern**: The verification agent judges implementation against outdated information — cached file contents, previous session's test results, or superseded plan criteria — rather than reading current state.

**Symptoms**: Agent reports FAIL for criteria that are actually satisfied. Manual inspection contradicts the agent's findings. Re-running the agent produces different results.

**Root Cause**: Agent relies on context from earlier in the conversation or previous sessions without re-reading current file state. Memory and context can become stale during long sessions.

**Prevention**: Agent must re-read all relevant files and re-run all relevant commands before issuing a verdict. Audit reports should include timestamps and file hashes to prove freshness.

## AP-2: Warning-as-Error Conflation

**The Pattern**: Test output contains warnings (deprecation notices, advisory messages, non-zero-but-acceptable conditions) that the agent interprets as test failures.

**Symptoms**: Agent reports test failures that don't appear when tests are run manually. The "failing" tests actually pass with warnings. Test count in agent report doesn't match actual test count.

**Root Cause**: Insufficient parsing of test output. Agent pattern-matches for negative keywords ("warning", "deprecated", "skip") without distinguishing them from actual errors.

**Prevention**: Agent should parse test output using the test framework's structured output format (e.g., pytest's `-v` output, jest's JSON reporter). Distinguish exit codes, error counts, and warning counts explicitly.

## AP-3: Wrong Scope Verification

**The Pattern**: The agent verifies files or tests from a different plan or module than the one under audit, producing misleading pass/fail verdicts.

**Symptoms**: Audit report references files not mentioned in the plan. Agent reports issues in code that wasn't modified by the current plan. Regression check covers unrelated modules.

**Root Cause**: Insufficient scoping of verification to the plan's declared file set and test suite. Agent uses broad globs or runs all tests without filtering.

**Prevention**: Agent should explicitly list which files and tests are in scope based on the plan document's "Files Created/Modified" and "Test" sections. Out-of-scope findings should be noted separately, not as plan criteria failures.

## AP-4: Approval Without Evidence

**The Pattern**: The agent approves a plan (PASS verdict) based on assertion rather than demonstrated evidence — e.g., "tests should pass" without actually running them, or "file exists" without verifying contents.

**Symptoms**: Audit report says PASS but subsequent work reveals the plan was incomplete. Report lacks concrete evidence (test output, file contents, command results).

**Root Cause**: Agent shortcuts verification by reasoning about expected behavior instead of observing actual behavior.

**Prevention**: Every criterion in the audit report must cite specific evidence: a command output, a file read result, or a concrete observation. "Should" and "would" language in verdicts indicates insufficient verification.

## Origin

Extracted from kinyen-equiplot verification audit experiences (BUG-028 through BUG-032 patterns). Generalized to remove domain-specific terminology.
