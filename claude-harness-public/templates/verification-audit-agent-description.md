# Verification Audit Agent — Description Template

> **Purpose:** Template for the YAML `description` field of the verification-audit-agent. Contains 4 example structures with `{PLACEHOLDER}` markers for project-specific content.
>
> **Usage:** The `verifier-creator.md` prompt fills these placeholders during agent generation. The result is collapsed into a single YAML string for the agent's frontmatter.

---

## Description Field Value

```
Use this agent when the coding agent needs to verify that its implementation aligns with the desired outcomes, when new coding tasks are initiated and need outcome-based decomposition, when vague or ambiguous instructions are received and need clarification before proceeding, or when a plan needs to be validated against verifiable milestones before execution begins.

Examples:

<example>
Context: {EXAMPLE_1_CONTEXT}
user: "{EXAMPLE_1_USER_MSG}"
assistant: "Before I start implementing, let me use the verification-audit-agent to decompose this into verifiable outcomes and ensure we have clear acceptance criteria."
<commentary>
Since the instruction is somewhat vague ({EXAMPLE_1_AMBIGUITY}), use the Task tool to launch the verification-audit-agent to clarify requirements and establish verifiable milestones before writing any code.
</commentary>
assistant: "Now let me use the verification-audit-agent to establish the outcome-based verification plan."
</example>

<example>
Context: {EXAMPLE_2_CONTEXT}
user: "{EXAMPLE_2_USER_MSG}"
assistant: "I've completed the refactoring. Let me now use the verification-audit-agent to audit whether the implementation meets all the expected functionality and objectives."
<commentary>
Since a significant piece of code was written, use the Task tool to launch the verification-audit-agent to verify the implementation against the original requirements and verifiable milestones.
</commentary>
</example>

<example>
Context: {EXAMPLE_3_CONTEXT}
user: "{EXAMPLE_3_USER_MSG}"
assistant: "This is a complex task. Let me use the verification-audit-agent to decompose this into verifiable milestones and create an outcome-based execution plan before I begin coding."
<commentary>
Since the task is complex and involves multiple systems ({EXAMPLE_3_SYSTEMS}), use the Task tool to launch the verification-audit-agent to create a structured plan with verifiable checkpoints.
</commentary>
</example>

<example>
Context: {EXAMPLE_4_CONTEXT}
user: "{EXAMPLE_4_USER_MSG}"
assistant: "Before continuing, let me use the verification-audit-agent to verify that the work completed so far aligns with our milestone plan and identify any deviations."
<commentary>
Proactively use the Task tool to launch the verification-audit-agent at natural checkpoints during implementation to ensure continuous alignment with desired outcomes.
</commentary>
</example>
```

---

## Placeholder Reference

| Placeholder | What It Replaces | Source |
|---|---|---|
| `{EXAMPLE_1_CONTEXT}` | Context sentence for the vague requirement scenario | Inferred from project domain |
| `{EXAMPLE_1_USER_MSG}` | User message with ambiguous instruction | Inferred from project features |
| `{EXAMPLE_1_AMBIGUITY}` | Commentary explaining what's vague about the instruction | Inferred from the user message |
| `{EXAMPLE_2_CONTEXT}` | Context sentence for post-implementation scenario | Inferred from project modules |
| `{EXAMPLE_2_USER_MSG}` | User message about completed refactoring or implementation | Inferred from project modules |
| `{EXAMPLE_3_CONTEXT}` | Context sentence for complex multi-system task | Inferred from project architecture |
| `{EXAMPLE_3_USER_MSG}` | User message with multi-system task | Inferred from project data flows |
| `{EXAMPLE_3_SYSTEMS}` | Commentary listing involved systems/services | Inferred from tech stack |
| `{EXAMPLE_4_CONTEXT}` | Context sentence for alignment check scenario | Inferred from project workflows |
| `{EXAMPLE_4_USER_MSG}` | User message about continuing implementation work | Inferred from project features |

## Guidelines for Filling Placeholders

- Each example should reference **real project artifacts** discovered during codebase exploration (file paths, model names, API endpoints, service names)
- Examples should cover **different parts of the codebase** — don't cluster all 4 around the same module
- The assistant responses are **generic** (same for all projects) — only the context, user messages, and commentary are project-specific
- Keep user messages natural — they should sound like something a developer would actually type
- Commentary should explain the **reasoning** for invoking the agent, not just describe the action
