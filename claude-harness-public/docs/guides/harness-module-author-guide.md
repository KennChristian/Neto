# Harness Module Author Guide

How to create a new capability module for claude-harness.

## When to Create a Module

Create a new module when:
- You have a coherent capability that applies to some (not all) projects
- The capability has its own templates, scripts, or prompts
- It makes sense to activate/deactivate the capability based on project characteristics

Do NOT create a module when:
- The capability applies to all projects (put it in `core/` instead)
- It's a single template or script without supporting assets (add to existing module)
- It's project-specific knowledge (put in the downstream project, not the harness)

## Module Directory Structure

```
modules/{module-name}/
├── module.yaml              # REQUIRED — Module manifest
├── prompt.md                # REQUIRED — Main capability prompt
├── templates/               # Optional — Templates for downstream projects
│   └── {template-files}
├── scripts/                 # Optional — Enforcement or utility scripts
│   └── {script-files}
├── hooks/                   # Optional — Claude Code hook fragments
│   └── settings-fragment.json
├── test-patterns/           # Optional — Reusable test cases
│   └── {test-pattern-files}
└── lessons/                 # Optional — Module-specific anti-patterns
    └── anti-patterns.md
```

## module.yaml Schema

```yaml
# REQUIRED fields
id: my-module                    # Unique identifier (kebab-case)
name: My Module                  # Human-readable name
version: 1.0.0                   # Semantic version
description: >                   # What this module does
  One paragraph description.

# REQUIRED for non-core modules
relevance:
  file_signals:                  # Glob patterns to match against project files
    - pattern: "**/*.csv"
      locations: ["outputs/"]    # Optional: restrict to specific directories
      weight: 3                  # Score contribution if matched
  code_signals:                  # Regex patterns to grep in source files
    - pattern: "CREATE TABLE"
      case_insensitive: false    # Optional, default false
      weight: 3
  tech_signals:                  # Technology identifiers
    - tech: "postgresql"
      weight: 2
  threshold: 4                   # Minimum score to ACTIVATE
  max_score: 16                  # Sum of all weights (for display)

# REQUIRED
bootstrap:
  phase_name: "My Module"        # Display name in bootstrap
  phase_order: 12                # Execution order (core phases are 1-9)

prompt: prompt.md                # Main prompt file (relative to module dir)

# Optional lists — paths relative to module dir
templates:
  - template-file.md
scripts:
  - script-file.sh
hooks:
  - settings-fragment.json
test_patterns:
  - test-pattern-file.md
lessons:
  - anti-patterns.md
```

## Relevance Signal Design

### Choosing Signals

- **file_signals**: Use when the module's relevance correlates with specific file types or output patterns
- **code_signals**: Use when the module's relevance correlates with code patterns (SQL DDL, framework imports, etc.)
- **tech_signals**: Use when the module's relevance correlates with technology choices

### Calibrating Weights

- Strong indicators (high confidence): weight 3
- Medium indicators: weight 2
- Weak indicators (suggestive but not conclusive): weight 1

### Calibrating Thresholds

- Set threshold so that a project with ONE strong signal gets SUGGEST (below threshold but non-zero)
- Set threshold so that a project with TWO medium signals gets ACTIVATE (meets threshold)
- Test against known project profiles (see TS-002 for examples)

## Hook Fragment Format

Hook fragments are JSON objects that follow the Claude Code `settings.json` schema. During bootstrap, fragments from activated modules are merged into the project's `.claude/settings.json`.

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "bash scripts/my-check.sh"
          }
        ]
      }
    ]
  }
}
```

## Registration in registry.yaml

After creating the module, add it to `registry.yaml`:

```yaml
modules:
  - modules/my-module/module.yaml
```

## Pre-Merge Checklist

- [ ] `module.yaml` passes TS-001 validation (required fields, unique ID, paths exist)
- [ ] Relevance scoring tested against ≥3 project profiles (ACTIVATE, SUGGEST, SKIP cases)
- [ ] `prompt.md` has no references to old template paths
- [ ] All template/script paths in `module.yaml` exist on disk
- [ ] Test patterns contain zero project-specific terms
- [ ] Module registered in `registry.yaml`
