# Claude Harness — Lessons Learned

Operational knowledge and prevention rules extracted from harness development and downstream project experiences.

## Prevention Rules

| ID | Rule | Detection | Source |
|----|------|-----------|--------|
| LRN-001 | When adding capability to a framework, ask: "Does this require editing an existing orchestration file?" If yes → needs extension points. | Review PR for edits to bootstrap-prompt.md or orchestration-prompt.md | Monolithic bootstrap scaling |
| LRN-002 | When a bug has ≥2 resolution generations, extract the pattern immediately while context is fresh. Add to `patterns/` in the same PR. | Bug resolution PR without accompanying pattern extraction | Trapped knowledge extraction timing |

## Lessons Index

| ID | File | Topic |
|----|------|-------|
| LRN-001 | [LRN-001-monolithic-bootstrap-scaling.md](./LRN-001-monolithic-bootstrap-scaling.md) | Monolithic bootstrap doesn't scale |
| LRN-002 | [LRN-002-trapped-knowledge-extraction-timing.md](./LRN-002-trapped-knowledge-extraction-timing.md) | Extract learnings during resolution, not after |
