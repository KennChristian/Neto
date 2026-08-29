# docs/guides/ — MANIFEST

Persona-scoped guides. Each guide is written for a specific reader,
opened cold, with no prerequisite reading. They are deliberately
redundant where redundancy serves clarity for that persona.

| File | Persona | One-line purpose |
|---|---|---|
| [GUIDE-firstrun.md](GUIDE-firstrun.md) | First-time developer / operator | Install + configure + smoke-test workflow. Covers the two big pitfalls (wrong file via Streamlit; Whisper download blocking startup), CJ_TEXT_ONLY mode, non-C-drive venv setup, troubleshooting matrix. |
| [GUIDE-end-user.md](GUIDE-end-user.md) | End user (visitor, reader, FLP stakeholder) | What to expect when chatting with the app — what it can answer, what it won't, how it is honest about being an AI. |
| [GUIDE-reviewer.md](GUIDE-reviewer.md) | Reviewer / curator quality-checker | Spot-check checklist for corpus fidelity, topic routing, and voice adherence. |
| [GUIDE-admin.md](GUIDE-admin.md) | Pipeline admin / operator | How to add documents, edit the taxonomy, run the scripts, read the reports. |
| [GUIDE-manager.md](GUIDE-manager.md) | Project manager / FLP lead | Phase status, roadmap interpretation, decision references, risk register. |

## How these guides relate

```
GUIDE-end-user.md   ← talks ABOUT the app (what they'll experience)
GUIDE-reviewer.md   ← talks ABOUT the artifacts (what to inspect)
GUIDE-admin.md      ← talks ABOUT the tooling (how to operate it)
GUIDE-manager.md    ← talks ABOUT the project (where we are, where we're going)
```

A reader following a single role does not need to read the others.
A reviewer who is also a curator may use both GUIDE-reviewer.md and
GUIDE-admin.md — those are aligned to be readable together.

## Conventions

- Each guide opens with a one-line statement of its audience.
- Headings are direct and skim-friendly.
- Cross-references to ADRs / plans / specs are by file path so the
  reader can follow without leaving the doc tree.
- Guides are revised whenever a Phase lands. The version of a guide
  on `main` at any time should be accurate for the current corpus
  and pipeline state.
