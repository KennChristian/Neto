# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## {PROJECT_NAME}

{PROJECT_DESCRIPTION}

### Tech Stack

{TECH_STACK}

### Commands

```bash
{COMMANDS}
```

### Directory Structure

```
{DIRECTORY_STRUCTURE}
```

### Key Conventions

{KEY_CONVENTIONS}

### Deep Docs

{DEEP_DOCS}

### MANIFEST.md Maintenance

When creating or deleting a source file, update the nearest ancestor `MANIFEST.md` to keep file indexes current. A PostToolUse hook on Write|Edit will remind you if a new file is missing from its MANIFEST. Run `./scripts/validate-manifests.sh` to check all MANIFESTs.

### Planning Protocol

For architectural decisions:
1. Create ADR in `{DECISIONS_DIR}/` using next sequential number
2. Follow MADR 4.0 template from `{DECISIONS_DIR}/0001-use-madr.md`
3. Required sections: Context, Decision Drivers, Considered Options, Decision Outcome, Consequences
4. Update the ADR index table in the relevant CLAUDE.md
