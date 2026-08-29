# LRN-002: Trapped Knowledge Extraction Timing

## Symptom

A downstream project (kinyen-equiplot) accumulated 40 bug reports over several months of development. Many bugs recurred across 2-4 resolution generations, revealing structural anti-patterns. By the time extraction into reusable patterns was attempted, the original context was stale — the developer had moved on, and the nuanced "why" behind each pattern was harder to reconstruct.

## Root Cause

No convention existed for when to extract reusable learnings from project-specific incidents. Pattern extraction was treated as a post-project activity rather than an ongoing practice integrated into the bug resolution workflow.

## Resolution

ADR-003 established the cross-project pattern library. The `patterns/` directory in claude-harness provides a home for extracted patterns, and the contributor guide defines the extraction process and quality gates.

## Prevention

When resolving a bug that has **≥2 resolution generations** (i.e., it was fixed, recurred, and fixed again), extract the pattern immediately while context is fresh. Add the generalized pattern to `patterns/` in the same PR as the bug fix.

Include "Is this pattern generalizable?" as a checklist item in the bug resolution workflow.

## Recommendation

Integrate pattern extraction into the resolution workflow, not as a separate post-hoc activity. The cost of extraction is lowest when the developer is actively holding the full context of the bug, its root cause, and its prevention strategy.
