# PLAN-0003: One-time offline embedding audit of the hand-curated taxonomy

* Status: draft
* Phase: 6
* Owner: TBD
* Depends on: Phases 1-3 complete; runtime can be in flight
  ([PLAN-0001](PLAN-0001-runtime-app-haiku-router-sonnet-composer.md))
* Verified by: report-only audit; no runtime change unless findings
  warrant a new ADR
* Related ADRs:
  [0003](../decisions/0003-reject-embeddings-for-v1.md) (the no-
  embeddings-at-runtime decision this audit explicitly does not
  challenge)

## 1. Goal

Run a **one-shot, offline** embedding-based sanity check on the
hand-curated taxonomy in `corpus/voice/topic_map.json`. The audit's
purpose is to surface failure modes the curator missed — *not* to
introduce a runtime embedding index.

The output is a report at `reports/embedding_audit.json` describing:

1. **Within-topic cohesion**: are the documents assigned to topic X
   actually similar to each other?
2. **Between-topic overlap**: which topics are statistically
   indistinguishable? Candidates for merger.
3. **Orphan-doc detection**: docs whose embeddings are dissimilar
   from all of their assigned topic-paths' other docs — likely
   misrouted.
4. **Under-routed-doc detection**: docs whose embeddings are similar
   to a topic they are *not* routed to — candidates for adding that
   topic to their `secondary` path.

The audit runs once, against the current taxonomy, with a defined
embedding model and a snapshot date. It is **not part of the runtime
pipeline** and is **not** re-run automatically. Findings translate to
manual curation decisions, not auto-applied changes.

## 2. Scope

**In scope**
1. Embed every doc's body or `one_paragraph_summary` (decision in
   §4) with a documented model (e.g., `text-embedding-3-small` or an
   open-source equivalent).
2. Compute per-topic centroid; compute within-topic mean similarity
   and between-topic centroid similarity matrix.
3. Flag docs with primary-topic similarity ≥1σ below the topic's
   mean (orphan-doc candidates).
4. Flag docs with similarity to a non-assigned topic ≥1σ above the
   median (under-routed candidates).
5. Flag topic pairs with centroid similarity ≥0.85 (merger
   candidates).
6. Write `reports/embedding_audit.json` + a human-readable
   `reports/embedding_audit_summary.md`.

**Out of scope**
- Auto-applying any flag as a `topic_paths` edit.
- Integrating embeddings into runtime retrieval (rejected by
  [ADR-0003](../decisions/0003-reject-embeddings-for-v1.md)).
- Embedding the topic *definitions* themselves (only the docs).
- Continuous re-embedding on every taxonomy edit.

## 3. Workstream A — Model selection

Decide and document in a new ADR:
- Embedding model (name, version, dimensionality)
- Provider (Anthropic embeddings TBD / OpenAI / local sentence-
  transformers)
- Whether to embed body or summary (see §4)

Constraints:
- Token budget: ≤$5 total cost for the one-shot run.
- Deterministic snapshot: model version pinned; run is reproducible.

## 4. Workstream B — Embedding target choice

Two options for what to embed per doc:

1. **Body** — full canonical text of the `.md` (typically 600-2,500
   words). Captures the full signal but is dominated by length.
2. **`one_paragraph_summary`** — the curator's 100-word distillation.
   Captures intent but is curator-mediated (and so partially
   correlated with the matchers we are auditing).

Recommendation: **embed the body**, then also embed the summary as
a control. Flag any topic where body-centroid and summary-centroid
disagree by more than the typical between-doc distance — that's a
signal that the curator's summary doesn't capture the doc's actual
content.

## 5. Workstream C — Similarity computations

Standard cosine similarity in the embedding space. Per topic `T`
with member docs `D_T`:

- Centroid: `μ_T = mean(embeddings[d] for d in D_T)`
- Within-topic mean similarity:
  `mean(cos(embeddings[d], μ_T) for d in D_T)`
- Within-topic std: `std(...)`
- Per doc-topic similarity: `cos(embeddings[d], μ_T)`

Flag thresholds (initial; tune after first run):
- **Orphan**: `cos(d, μ_T) < mean(T) - σ(T)` for `d ∈ D_T`.
- **Under-routed**: `cos(d, μ_T') > median_topic_sim(d) + σ(T')`
  for `T' ∉ topic_paths(d)`.
- **Merger candidate**: `cos(μ_T1, μ_T2) > 0.85`.

## 6. Workstream D — Report generation

`reports/embedding_audit.json`:
```json
{
  "model": "text-embedding-3-small",
  "dimensions": 1536,
  "snapshot_date": "...",
  "n_docs": 79,
  "n_topics": 35,
  "per_topic": {
    "rule_of_law": {
      "doc_count": 30,
      "within_topic_mean_sim": 0.61,
      "within_topic_std": 0.07,
      "orphan_docs": ["CA024"]
    }
  },
  "topic_pair_similarities": [
    {"a": "rule_of_law", "b": "constitutional_doctrine", "cos": 0.79},
    ...
  ],
  "merger_candidates": [...],
  "under_routed_candidates": [
    {"doc_id": "CC005", "suggest_secondary": ["faith_journey"]}
  ]
}
```

`reports/embedding_audit_summary.md`: human-readable digest with the
top-N findings of each category, each with a recommendation.

## 7. Failure modes

| Failure mode | Detection | Response |
|---|---|---|
| Embedding API down | Job retries | Resume from last-saved checkpoint |
| Doc embedding fails (too long) | Per-doc try/except | Skip + log; report covers it |
| All topic pairs similar (taxonomy is collapsed) | Sanity threshold | Halt + reviewer note: "audit suggests taxonomy is undifferentiable; review thresholds" |
| Zero orphans / zero merger candidates (looks suspicious) | Compare to expected base rate | Lower σ threshold; rerun reporting only |

## 8. Edge cases

- **Topic with 1 doc** (e.g., `death_penalty_and_echegaray`) — no
  within-topic variance computable; report N/A.
- **Topic with 0 docs** (e.g., `robot_identity_meta`) — no member
  embeddings; topic is excluded from cohesion stats but still gets
  pair-similarity entries.
- **Body has placeholder text** (`<!-- TEXT TO BE INSERTED -->`) —
  embed the title + summary instead; flag in audit notes.

## 9. Acceptance

- `reports/embedding_audit.json` + `summary.md` produced for the
  current corpus.
- Reviewer reviews the summary against
  [GUIDE-reviewer.md](../guides/GUIDE-reviewer.md) §"Embedding audit
  review" checklist.
- Findings classified as: actionable (file taxonomy edits per
  [PLAN-0007](PLAN-0007-topic-map-evolution-process.md)), ignore-with-
  reason, or escalate to ADR.

## 10. Out-of-scope discoveries to surface

If the audit finds that the hand-curated taxonomy correlates
poorly with embedding-based similarity, this is *information*, not
a direction. A follow-up ADR may be warranted to:
- Add new topics to capture an obvious cluster the curator missed.
- Merge two topics whose embeddings are indistinguishable but whose
  matchers stayed separate by curator intent.

Re-running this audit after such changes is its own decision; if so,
update this plan to remove the "one-shot" framing and write a new
ADR justifying continuous audit.
