# docs-retrieval module — Lessons

Three generalized lessons extracted from the originating project (`rev1_2`
form-grammar-scoring) while designing and operationalizing the multi-axis
retrieval architecture.

## Lesson 1 — Manifest schema drift from column addition

**What happened:** A project adopted the harness `manifest-md.md` template
(which has `File | Purpose` columns) and extended it with a project-specific
`Status` column. No writer contract was established for the new column.
Over ~200 plans, the Status column diverged from the actual plan status
tracked elsewhere. The divergence was structural, not a discipline failure:
there was no single writer and no reconciliation step.

**What to do differently:** Never extend a harness template without also
declaring a writer contract. If the new fact can be derived from elsewhere
(frontmatter, a source-of-truth file), make the MANIFEST a generated view
with a hash header rather than a hand-authored file with extra columns.
Validators must reject MANIFEST schemas that deviate from the template
without authorization.

### Origin
Extracted from `rev1_2` / LL-064-manifest-schema-drift-from-column-addition.
Occurred after ~200 plans accumulated with divergent Status across MANIFEST
and `00-index.md`.

---

## Lesson 2 — Closed-tag taxonomy collapse at scale

**What happened:** The initial retrieval design proposed a single closed
topic registry of ~20 topics. Every artifact would carry a `topics: [...]`
frontmatter field drawn from the closed list. Design review surfaced five
structural weaknesses:

1. Single-projection fragility — one wrong tag makes an artifact invisible.
2. Exclusive-membership bias — authors pick 1–2 salient tags even when the
   artifact spans 5.
3. Query-time translation gap — user query language ≠ tag language.
4. Taxonomy rot — closed vocabularies need governance that rarely scales.
5. Single point of failure — one classification axis has no redundancy.

**What to do differently:** Prefer multi-axis orthogonal tagging (3–5
independent axes, each with its own closed vocabulary). Retrieval via
intersection across axes gives redundancy. Each axis value gets its own
record (Axis Value Record) with rationale and orthogonality check, so the
vocabulary grows atomically and auditably rather than via periodic rewrites.

### Origin
Extracted from `rev1_2` / LL-065-closed-tag-taxonomy-collapse-at-scale and
ADR-141. The refutation happened at design review; the replacement design
is what this module ships.

---

## Lesson 3 — LSH as architectural inspiration, not implementation

**What happened:** ADR-141 drew on Locality-Sensitive Hashing (LSH) from
big-data ML as an architectural inspiration — specifically, the idea of
"multiple independent hash projections with intersection-based similarity."
An earlier draft proposed literally transplanting LSH mechanisms (vector
spaces, hash families) into a markdown docs corpus. That transplant would
have added vector-space infrastructure that doesn't fit the substrate: the
corpus is human-readable markdown, not feature vectors.

**What to do differently:** When borrowing architectural ideas across
paradigms, separate the principle (multi-projection intersection yields
robust similarity) from the mechanism (hash functions on vectors). Keep the
principle; discard the mechanism if it doesn't fit the target substrate.
In this case, the principle became "multi-axis frontmatter with intersection
lookup"; the mechanism became "hand-curated axis values in YAML."

### Origin
Extracted from `rev1_2` / LL-066-lsh-as-architectural-inspiration-not-implementation.
The meta-lesson applies to any architectural borrowing across paradigms.
