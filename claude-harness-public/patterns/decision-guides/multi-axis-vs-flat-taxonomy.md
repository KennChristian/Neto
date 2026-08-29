# Decision Guide: Multi-Axis vs. Flat Taxonomy

## The Decision

When classifying artifacts (plans, ADRs, docs, tickets) for retrieval, should you use a single flat taxonomy (one tag field with a closed vocabulary) or multi-axis orthogonal tagging (N independent axes, each with its own closed vocabulary)?

## When This Applies

Any project with ≥50 artifacts where retrieval cost is a concern and grep-scanning the full corpus is becoming expensive (for humans or for agents operating under a token budget).

## Options

### Option 1 — Flat Taxonomy (single tag field)

- **Pros:** Simple to bootstrap; one registry file; works well under 100 artifacts; low cognitive load for authors.
- **Cons:** Fails past ~100 artifacts due to exclusive-membership bias (authors pick 1–2 tags even when an artifact spans 5); taxonomy rot as topic space drifts; single-projection fragility (one wrong tag and the artifact is invisible); retrieval translation gap (query language vs. tag language).
- **Sweet spot:** <50 artifacts, single-author, low-churn topic space.

### Option 2 — Multi-Axis Orthogonal Tagging (N independent axes)

- **Pros:** Scales to 5000+ artifacts; redundancy against mis-tagging (intersection across axes catches miss on any one axis); forces authors to consider each axis independently, reducing minimalism bias; vocabulary governance is atomic (per-value records, not per-schema rewrites).
- **Cons:** Higher upfront design cost (must define the axes, prove orthogonality); higher author cognitive load at first (more fields to fill); requires a generator and validator to be useful in practice.
- **Sweet spot:** ≥100 artifacts, multi-author, topic space that keeps evolving.

## Recommendation

- **<50 artifacts:** Flat taxonomy. The overhead of multi-axis is not justified.
- **50–100 artifacts:** Flat is still fine if topic churn is low; measure retrieval failure rate before investing in multi-axis.
- **≥100 artifacts:** Multi-axis. The failure modes of flat taxonomy (documented in `anti-patterns/closed-tag-taxonomy.md`) become structural; fixes at the item level don't converge.
- **Always:** Before picking, measure — count artifacts, measure average tag count per artifact, survey authors about tagging confusion.

## Design Steps for Multi-Axis

1. **Identify candidate axes** from existing prose — what questions does the project actually ask about its artifacts? Common axes: stage (lifecycle), layer (what does this modify), concern (what topic), persona (for whom), depth (how abstract).
2. **Prove orthogonality** — any two axes must have <30% value-pair correlation across a sample. Correlated axes waste retrieval power.
3. **Author per-value records** — each axis value gets a record (an AVR, "Axis Value Record") with rationale, example artifacts, and orthogonality check against other axes.
4. **Build generators and validators** — registry from records, per-axis view files from frontmatter, validator for schema + reference integrity.

## Origin

`rev1_2` (ADR-141). Initial design was a flat closed-tag registry (~20 topics). Design review refuted it in favor of 5-axis orthogonal tagging. Subsequent operation confirmed the multi-axis choice at 556 artifacts.

## Related

- `anti-patterns/closed-tag-taxonomy.md` — failure mode of Option 1 at scale
- `anti-patterns/manifest-schema-drift.md` — sibling failure mode (drift in the governance layer)
- `test-patterns/axis-coverage.md` — verification that every axis value is in use
