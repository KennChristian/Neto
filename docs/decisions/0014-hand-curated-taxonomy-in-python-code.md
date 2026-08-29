# ADR-0014: Hand-curated taxonomy lives in Python code, not external YAML/JSON

* Status: accepted
* Date: 2026-05-26
* Deciders: Janet

## Context and Problem Statement

Phase 2 produces `corpus/voice/topic_map.json` — a 35-topic curated
taxonomy used by the runtime router to map user questions to source
documents. The taxonomy needs three things:

1. **Topic definitions** (id, display_name, definition, tier, theme
   anchor, default_register, wit_calibration).
2. **Matcher rules** — the keywords / entity names whose presence in a
   doc puts that doc under that topic.
3. **Per-topic statistics** computed *over the corpus* (doc_count,
   doc_ids, date_range, type_distribution, top_signature_phrases).

(1) and (2) are curatorial inputs (humans write them). (3) is derived
mechanically by walking the corpus.

The question is where (1) and (2) live: as a separate human-edited
data file (`taxonomy.yaml` or `taxonomy.json`), or **inside** the
build script as a Python data structure that gets compiled together
with the matching engine.

## Decision Drivers

* **Edit ergonomics**: the most common change is "add a topic" or
  "tighten one matcher term"; that should be a one-line edit, not a
  cross-file edit.
* **Atomicity**: a matcher tweak ought to ship together with the
  taxonomy entry it tightens — single diff, single review.
* **Test-spec coverage**: matcher behaviour is testable
  ([TS-002](../test-specs/TS-002-topic-map-matchers.md)); the test
  spec references the taxonomy directly.
* **Schema evolution**: the matcher format is likely to evolve as new
  signal types appear (regex matchers, score weights, theme
  constraints). Code-resident schemas evolve via type hints and code
  review; data-file schemas need separate validation.
* **Reviewer velocity**: a curator who is also comfortable in Python
  (the FLP project team) reviews the diff in one place.

## Considered Options

1. **Python list of dicts in `scripts/build_topic_map.py` (chosen)** —
   `TAXONOMY: list[dict[str, Any]] = [{"id": "rule_of_law", ...}, ...]`.
2. **External YAML at `corpus/voice/taxonomy.yaml`** — loaded by the
   build script; topic_map.json is derived from both the YAML and the
   corpus walk.
3. **External JSON at `corpus/voice/taxonomy.json`** — same as YAML
   but JSON.
4. **External JSON that *is* the topic_map.json** — humans curate the
   topic-level fields and the stats fields are merged in by a build
   step.

## Decision Outcome

Chosen option: **Python list in `scripts/build_topic_map.py`**.

The taxonomy occupies the top ~350 lines of the script. Each topic
entry is a single Python dict literal with a comment header that
groups topics by theme (`# ===== Theme A — Liberty / Rule of Law =====`).
Adding a topic is one dict literal; tightening a matcher is one
keyword string edit.

The runtime `corpus/voice/topic_map.json` is a **derived artifact** —
rebuilt by running `python scripts/build_topic_map.py`. It is checked
into git for runtime consumption (zero-cost startup), but its
authoritative source is the Python.

### Consequences

* Good: single-file edit covers most curation tasks. A "tighten the
  `asean_law_association` matcher" diff is contained in one
  10-line block.
* Good: type hints (`dict[str, Any]`) and IDE-level lint surface
  schema mistakes immediately. A missing `theme_anchor` field shows
  up as an AttributeError on the next run, not silent matcher misfire.
* Good: the matching engine and the data live in the same file, so
  the test spec [TS-002](../test-specs/TS-002-topic-map-matchers.md)
  imports `TAXONOMY` directly without parsing intermediate files.
* Bad: a non-Python curator (e.g., an FLP communications staffer
  drafting new topic names) needs to learn the dict-literal syntax.
  Mitigated by the consistent comment-headed structure and a worked
  example in
  [GUIDE-admin.md](../guides/GUIDE-admin.md) and
  [PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md).
* Bad: diffs of `topic_map.json` (the derived artifact) appear
  in git history alongside Python changes. Acceptable —
  treat them as build outputs that ship for runtime speed.
* Neutral: ports easily to external YAML later if the curator
  audience expands. The Python literal *is* the JSON the build emits
  for the per-topic fields, so the migration is a deserialiser swap.

## Pros and Cons of the Options

### Python list in build script (chosen)

* Good, because edits are atomic and reviewable in one file.
* Good, because no separate schema-validation step.
* Good, because IDE-level type signals.
* Bad, because the curator must touch a code file.

### External YAML

* Good, because human-friendly indentation, no quote noise.
* Bad, because two-file edits for any matcher-and-engine change.
* Bad, because schema drift between YAML and the engine that consumes
  it is a real failure mode (YAML lints don't enforce
  semantic constraints like *"matchers.keywords must be a list of
  lower-case strings"*).

### External JSON

* Good, because JSON is machine-validatable with a schema file.
* Bad, because verbose for handwriting — every key is quoted; trailing
  commas error; comments are not allowed.
* Bad, because the same two-file-edit overhead as YAML.

### Human-curated topic_map.json

* Good, because one file is both source and runtime artifact.
* Bad, because per-topic *statistics* (doc_count, doc_ids) would have
  to be either hand-maintained (impossibly tedious) or rebuilt by a
  derivation step — which puts us back at a derived artifact.

## More Information

- Implementation: `scripts/build_topic_map.py` lines 60-400ish (the
  `TAXONOMY` list).
- The derivation algorithm
  (matcher scoring → stats aggregation) is documented in
  [ADR-0015](0015-topic-paths-derivation-rules.md).
- Process for adding/editing topics:
  [PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md).
- Admin walk-through: [GUIDE-admin.md](../guides/GUIDE-admin.md).
