# Decision Guide: Progressive Disclosure for LLM Context Efficiency

## The Decision

How should project documentation be layered to optimize LLM (Large Language Model) context window usage while maintaining completeness?

## When This Applies

- Projects using LLM-based coding assistants (Claude Code, Copilot, Cursor, etc.)
- Projects with substantial documentation (>500 lines across all docs)
- Teams where LLM context window limits cause important information to be truncated
- Projects where documentation is read both by humans and LLMs

## Options

### Option A: Single Comprehensive Document
Put all documentation in one file (e.g., a large README.md or CLAUDE.md).

- **When to choose**: Very small projects with minimal documentation (<100 lines total)
- **Pros**: Simple. Everything in one place.
- **Cons**: Exceeds LLM context limits quickly. Irrelevant information dilutes relevant context. No scoping by work area.

### Option B: Three-Layer Progressive Disclosure (L0/L1/L2)
Layer documentation into three tiers:
- **L0 (root)**: Always loaded. Project identity, commands, directory tree, conventions. ~100 lines max.
- **L1 (subdirectory)**: Auto-loaded when working in that directory. Subsystem-specific conventions.
- **L2 (on-demand)**: Read explicitly when needed. Specs, schemas, reference material.

- **When to choose**: Most projects with more than trivial documentation
- **Pros**: LLM always has project context (L0) plus relevant subsystem context (L1). Expensive reference material loaded only when needed. Scales to large projects.
- **Cons**: Requires discipline to maintain layering. Risk of information duplication across layers.

### Option C: Dynamic Context Assembly
Use tooling to dynamically assemble context based on the current task (e.g., retrieval-augmented generation over project docs).

- **When to choose**: Very large projects with extensive documentation, teams with RAG infrastructure
- **Pros**: Maximum context relevance. Scales to massive doc sets.
- **Cons**: Requires infrastructure. Retrieval quality varies. Harder to debug context issues.

## Recommendation

Default to **Option B** (L0/L1/L2) for most projects. Key rules:
- L0 contains routing information (pointers to L1/L2), not detailed content
- L0 must stay under 100 lines to preserve context for actual code
- L1 files never duplicate L0 content — they extend it for their subsystem
- L2 references in L0/L1 are marked `(on-demand)` to signal they're not auto-loaded

## Origin

Derived from downstream-project ADR-011. Generalized: applicable to any project using LLM coding assistants.
