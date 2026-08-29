# Decision Guide: Requirements-to-Artifact Traceability

## The Decision

How should a project track the provenance of requirements claims from authoritative sources (SOWs, client briefs) through derived artifacts (data dictionaries, API specs, system designs) so that interpretation errors are detectable and source drift is caught automatically?

## When This Applies

- Projects where requirements come from external sources (client SOWs, RFPs, regulatory documents)
- Projects where multiple artifacts (data model, API spec, system design) derive from the same source
- Projects using git submodules for source document management
- Projects where LLM agents synthesize source text into derived artifacts (interpretation drift risk)
- Projects where source documents are updated by external parties without notification

## The Core Problem

LLM agents and human architects both **synthesize** when they read source documents — they paraphrase, combine, and interpret. This synthesis can subtly change meaning. Without a mechanism to compare the synthesis against the original text, interpretation errors propagate silently through all derived artifacts.

Additionally, source documents in external repos or submodules evolve independently. Without version pinning and drift detection, derived artifacts silently become stale.

## Options

### Option A: Inline Text References

Cite sources in prose: "per CMS SOW Section 4.2.4" or "REQ-F-069".

- **When to choose**: Small projects with stable requirements and a single author
- **Pros**: Simple. No tooling. Familiar.
- **Cons**: No machine-readable provenance. No drift detection. No way to verify the reference is accurate without manually reading the source. If the source changes, no alert.

### Option B: Requirements Traceability Matrix (traditional)

A table mapping Requirement ID → Design Component → Test Case.

- **When to choose**: Regulated environments requiring formal traceability matrices
- **Pros**: Established practice. Auditors understand it. Covers the full V-model.
- **Cons**: Maps to requirement IDs, not to what the requirement actually says. If someone misinterpreted REQ-F-069, the matrix link doesn't help catch it. No version pinning. No automated drift detection.

### Option C: Source Registry + Claims Matrix + Drift Detection (Recommended)

A four-component system:

1. **Source Registry** — records authoritative document paths with git commit hash pinning and stakeholder dependency maps
2. **Claims Matrix** — separates "Interpretation" (what we claim) from "Verbatim Quote" (exact source text) with line references
3. **Artifact Traceability** — each derived artifact entry references a Claim ID (CLM-NNN), enabling bidirectional trace
4. **Drift Detection Scripts** — automated comparison of pinned commit hash vs. current submodule state

- **When to choose**: Projects with external source documents that evolve, multiple derived artifacts, LLM-assisted synthesis, or multiple stakeholders consuming the same sources
- **Pros**:
  - Verbatim quotes enable human audit of interpretation accuracy
  - Git hash pinning makes drift detection deterministic
  - Per-stakeholder impact reporting targets notifications
  - Bidirectional traceability: source → claims → artifacts AND artifacts → claims → source
  - Machine-verifiable: scripts can grep quotes against pinned source
- **Cons**: More infrastructure (registry file, claims matrix, 3-4 scripts). Initial claim extraction effort. Claims matrix must be maintained when sources change.

## Recommendation

Default to **Option C** for any project where:
- Requirements come from an external source that has its own version history
- Multiple technical artifacts derive from the same source
- An LLM agent assists in interpreting requirements

The key insight: **never trust a synthesis without seeing the quote.** The claims matrix makes the original source text visible alongside the interpretation, enabling human audit at the point where errors are introduced.

## Implementation Pattern

### Source Registry (`docs/requirements/source-registry.md`)

```markdown
### SRC-001: {Document Name}
- authoritative_path: {submodule/path/to/document.md}
- submodule: {submodule_name}
- submodule_commit: {40-char git hash}
- submodule_pin_date: {YYYY-MM-DD}
- source_version_alias: {short alias, e.g., CMS-SOW@4624dec}
- derived_documents:
  - {path to derived doc 1}
  - {path to derived doc 2}

#### Stakeholder Dependency Map
| Stakeholder | Artifact | Consumed Sections | Action If Section Changes |
```

### Claims Matrix (`docs/traceability/claims-matrix.md`)

```markdown
| Claim ID | Interpretation | Source ID | Section | Line | Verbatim Quote | Source Version | Verified | By | Date |
```

Key design: **two separate columns** for Interpretation vs. Verbatim Quote. The human audits by comparing the two.

### Artifact Traceability Column

Add to any derived artifact:
```markdown
| Attribute/Endpoint/Component | ... | traceability |
|------------------------------|-----|-------------|
| component_type | ... | CLM-014 |
| /templates | ... | CLM-026 |
| Tenant Resolver | ... | CLM-008 |
| section_flow | ... | grammar-derived |
```

Entries without a SOW claim use a domain-specific label (e.g., `grammar-derived`, `architecture-derived`) to distinguish SOW-mandated from internally-motivated.

### Scripts

| Script | Purpose |
|--------|---------|
| `detect_source_drift.py` | Compare submodule hash vs. registry pin. Report per-stakeholder impact. |
| `verify_claims.py` | Grep verbatim quotes in source at pinned commit. Report PASS/DRIFT/FAIL. |
| `update_source_registry.py` | Update registry pins after submodule pull. |

## Related Patterns

- **Data Provenance** (`data-provenance.md`) — verifies input file identity via checksums. Complementary: data provenance protects pipeline inputs, requirements traceability protects design interpretation.
- **Progressive Disclosure** (`progressive-disclosure.md`) — traceability has its own tiers: Tier 0 (artifact version), Tier 1 (claims references), Tier 2 (verbatim quotes), Tier 3 (source diffs).
