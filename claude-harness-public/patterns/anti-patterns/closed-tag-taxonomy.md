# Anti-Pattern: Closed-Tag Taxonomy at Scale

## The Pattern

A project adopts a single closed-tag vocabulary for topical classification of its artifacts (plans, ADRs, docs, tickets). Authors pick one or two tags per artifact from the closed list. Retrieval by tag queries the list. Everything works at first — under 100 artifacts, the cost of mis-tagging is low and the list feels complete.

## Symptoms

- Past ~100 artifacts, authors pick the wrong tag or skip tagging entirely
- New topics "don't fit any existing tag" and authors either invent ad-hoc tags or shoehorn content into the closest existing one
- Retrieval by tag misses relevant artifacts because tagging was lazy, inconsistent, or the artifact legitimately spans multiple topics
- The registry rewrites every few quarters as the topic space shifts, breaking existing tags
- Average tag count per artifact hovers near 1, not the 3–5 that would reflect reality

## Root Cause

Single-projection classification has no redundancy; every tagging decision is a single point of failure. Authors exhibit exclusive-membership bias — they pick the 1–2 most-salient tags even when an artifact genuinely spans 5. The UI of "pick tags from a list" nudges toward minimalism. And closed vocabularies require a governance process that rarely scales past the first reorganization.

## Prevention Rules

1. **Prefer multi-axis orthogonal tagging over single closed tags** — Multiple independent axes (each a small closed vocabulary) replace one big topic list. Each axis answers a different question (stage, depth, layer, concern, persona).
2. **Orthogonality test before adopting an axis** — If two proposed axes correlate >30% across the corpus, they are not independent; merge or drop one.
3. **Retrieval via intersection, not direct lookup** — Future queries load per-axis view files and intersect mentally, giving redundancy against any single miss-tag.
4. **Vocabulary governance per value, not per schema** — Each axis value requires its own record (an "Axis Value Record") explaining why it is distinct from neighbors; growing the vocabulary is atomic and auditable.

## Detection

- Measure tag-to-artifact ratio. If average <2 tags per artifact in a 200+ corpus, you're seeing the pattern.
- Measure retrieval failure rate: have users try to find artifacts they know exist via tag queries; count the misses.
- Survey authors: do they report "I couldn't figure out which tag to use" on more than 10% of new artifacts?

## Origin

Extracted from `rev1_2` (LL-065, ADR-141). The architecture's original design was a single closed topic registry of ~20 topics. Design review surfaced 5 structural weaknesses (single-projection fragility, exclusive-membership bias, query-time translation gap, taxonomy rot, single point of failure). The architecture was redesigned as 5-axis orthogonal tagging before implementation.

## Related

- `decision-guides/multi-axis-vs-flat-taxonomy.md` — the choice framework
- `lessons/` — the meta-lesson that LSH was inspiration, not implementation (rev1_2 LL-066)
