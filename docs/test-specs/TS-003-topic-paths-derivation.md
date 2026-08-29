# TS-003: `topic_paths` derivation — determinism, thresholds, tie-breaking

* Status: draft
* Verifies:
  [ADR-0015](../decisions/0015-topic-paths-derivation-rules.md)
* Subject: `scripts/apply_topic_paths.py` calling
  `derive_topic_paths()` in `scripts/build_topic_map.py`
* Style: model-based — state-transition over scoring → ranking →
  selection

## 1. Model

```
doc_scores[doc_id] = {topic_id: int_score for every topic}
                       │
                       │ sort by (-score, tier_rank)
                       ▼
                  ranked list of (topic_id, score)
                       │
                       ├── primary  = up to 2 with score ≥ 2
                       ├── secondary = up to 3 with score ≥ 1
                       └── fallback (if primary empty): promote rank 1
```

`tier_rank = {anchor: 0, core: 1, subordinate: 2, meta: 9}` —
lower wins ties.

## 2. Given / When / Then — selection rules

### 2.1 Top scorer with score ≥ 2 is primary

**Given** doc with scores `{rule_of_law: 4, constitutional_doctrine:
3, due_process: 1}`,
**When** `derive_topic_paths` runs,
**Then** `primary == ["rule_of_law", "constitutional_doctrine"]`,
`secondary == ["due_process"]`.

### 2.2 Score-1 topic never lands in primary

**Given** scores `{topic_x: 1, topic_y: 1, topic_z: 1}` (all = 1),
**When** derived,
**Then** `primary` falls through the ≥2 filter; fallback rule
promotes the best `tier_rank` of them to primary (1 doc only);
secondary gets the next two.

### 2.3 Tier tie-break: anchor wins over core

**Given** scores `{anchor_topic: 3, core_topic: 3}` (tied),
**When** derived,
**Then** `primary == ["anchor_topic", "core_topic"]` in that order
(anchor first).

### 2.4 Tier tie-break: core wins over subordinate

**Given** scores `{core_topic: 2, subordinate_topic: 2}`,
**Then** `primary == ["core_topic", "subordinate_topic"]`.

### 2.5 Meta tier never beats normal tiers at equal score

**Given** scores `{rule_of_law: 2, robot_identity_meta: 2}` (the
META hits the doc),
**When** derived,
**Then** `primary == ["rule_of_law", "robot_identity_meta"]` —
rule_of_law (anchor, rank 0) beats meta (rank 9).

### 2.6 No-empty-primary guarantee

**Given** every score == 0 for some pathological doc (no enrichment,
no signal),
**When** derived,
**Then** `primary == []` and `secondary == []`. This is the only
case where `primary` may be empty; the apply step warns on this
condition.

### 2.7 No-empty-primary fallback when scores are nonzero but all <2

**Given** scores `{topic_x: 1}` (only one matcher anywhere; no topic
crosses ≥2),
**When** derived,
**Then** `primary == ["topic_x"]`, `secondary == []`.

### 2.8 Cap at 2 primary, 3 secondary

**Given** 10 topics with score ≥2 each,
**When** derived,
**Then** `len(primary) == 2`, `len(secondary) == 3`. The other 5
hits are absent from `topic_paths`.

## 3. Determinism

**Given** identical inputs (corpus + TAXONOMY) running twice in
fresh processes,
**When** `apply_topic_paths.py` runs,
**Then** every `.json` ends with bit-identical `topic_paths` arrays.

## 4. Integration with the full corpus (current state)

Once the apply step runs against the 79-doc corpus and the 35-topic
taxonomy:

- **Zero docs have `primary == []`** (verified end of Phase 2 by
  `apply_topic_paths.py` summary line).
- **Every doc's `primary[0]`** appears in the corresponding topic's
  `doc_ids` in `topic_map.json` — round-trip consistency.

## 5. Edge cases

| Case | Expected behavior |
|---|---|
| Doc has score 0 for every topic | `primary == []`, warn logged |
| Doc has many score-2 topics tied at same tier | First-by-id-alphabetical breaks the final tie (Python's stable sort) |
| Topic_map.json is missing | `apply_topic_paths.py` errors out clearly; no .json files modified |
| A doc's `id` in topic_map's `doc_ids` doesn't appear in any corpus file | Stale entry in topic_map — re-run `build_topic_map.py` to refresh |
| Curator deletes a topic that some doc had in `primary` | Re-run apply step → that doc's `primary` recomputed without the deleted topic |

## 6. Golden-file regression

The 79 docs' current `topic_paths` are the golden file as of
end-of-Phase-2. After a taxonomy edit, the regression test:

1. Snapshot every doc's `topic_paths` before the edit.
2. Apply the edit.
3. Diff each doc's `topic_paths` against the snapshot.
4. Report: docs unchanged, docs whose primary changed, docs whose
   secondary changed.

Reviewers approve the diff in the
[PLAN-0007](../implementation-plans/PLAN-0007-topic-map-evolution-process.md)
process before merging.

## 7. Observability

`scripts/apply_topic_paths.py` prints:
```
[apply] N files updated of M; K with empty primary path
```

`K > 0` is a yellow flag — surfaces docs that need attention.

## 8. Out-of-scope

- Whether the chosen primary topics are the *right* topics (curator
  judgment, covered by reviewer pass).
- Whether the runtime router *picks* one of the primary topics
  (runtime behavior, covered by
  [TS-004](TS-004-voice-card-protocol.md) §"Router routing
  accuracy").
