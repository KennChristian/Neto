# docs/test-specs/ — MANIFEST

Test specifications, one per layer of the pipeline. Each spec uses a
hybrid given/when/then + state-machine format. **Specs describe
verification; they do not execute it.** Execution belongs to
implementation work driven by the corresponding plan.

| ID | File | Subject | Style |
|---|---|---|---|
| TS-001 | [TS-001-corpus-generator-contract.md](TS-001-corpus-generator-contract.md) | `scripts/generate_corpus_files.py` — CSV → `.md` + `.json` contract | Given/when/then; state-transition on the row processor |
| TS-002 | [TS-002-topic-map-matchers.md](TS-002-topic-map-matchers.md) | `scripts/build_topic_map.py` — taxonomy + scoring engine | Given/when/then for invariants; precision/recall metric checks; matcher-health thresholds |
| TS-003 | [TS-003-topic-paths-derivation.md](TS-003-topic-paths-derivation.md) | `scripts/apply_topic_paths.py` + `derive_topic_paths()` | State-transition over scoring → ranking → selection |
| TS-004 | [TS-004-voice-card-protocol.md](TS-004-voice-card-protocol.md) | Sonnet composition step — voice card protocol conformance | LLM-as-judge rubric scenarios |
| TS-005 | [TS-005-end-to-end-pipeline-smoke.md](TS-005-end-to-end-pipeline-smoke.md) | Full Phase 1-4 pipeline | Integration / smoke against the six build-kit sanity questions |
| TS-006 | [TS-006-smoke-test-questions.md](TS-006-smoke-test-questions.md) | Full pipeline against 25 in-corpus + 5 adversarial questions | Integration / smoke (with [JSON sidecar](TS-006-smoke-test-questions.json) for the runner) |

## How to use these specs

- **Author**: when writing or reviewing the code each spec covers,
  read the spec first; treat each given/when/then as a constraint
  the implementation must satisfy.
- **Reviewer**: use the spec as your checklist. The spec's "edge
  cases" table is where most bugs live.
- **Executor (later orchestration)**: a spec becomes a test suite
  when an implementation plan lands. The test suite need not be a
  1:1 transcription — but every given/when/then should be answered
  by at least one assertion.
- **Spec evolution**: specs are versioned alongside the artifact they
  describe. A breaking change to a generator function should ship
  with the matching test-spec update in the same commit.

## Coverage map

```
TS-001 ←─── generator (Phase 1)
TS-002 ←─── topic map builder (Phase 2)
TS-003 ←─── topic_paths backfill (Phase 2b)
TS-004 ←─── voice card (Phase 3) + composer (Phase 4)
TS-005 ←─── full pipeline (Phase 1 + 2 + 3 + 4)
```

The unit-level specs (001-003) verify deterministic invariants. The
LLM-grounded spec (004) verifies behavioural conformance. The smoke
spec (005) verifies that all layers compose correctly at runtime.
