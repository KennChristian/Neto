## Retrieval Protocol (for future Claude sessions)

Before grep-scanning `docs/`, read `docs/RETRIEVAL.md`. Use the 4-tier
protocol to narrow candidates from the markdown corpus to 2–3 relevant
files for ≤15K tokens per query. Do NOT browse MANIFESTs or scan by ID —
use the per-axis views under `docs/_views/` (generated; see the
`docs-retrieval` harness module for the architecture).
